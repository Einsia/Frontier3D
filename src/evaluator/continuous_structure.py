"""Area-based topology and solid defects from complete world-metre triangles.

The result contains raw affected-face populations. Semantic part assignment and
task aggregation belong to the caller. Surface intersection uses float64 AABBs
and the validated triangle predicate, including coplanar overlap. Resource or
precision exhaustion remains a technical missing measurement.
"""
from collections import defaultdict
from itertools import islice
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from .continuous_surface import triangle_areas
from .l1_mesh import improper_intersection
from .continuous_triangle_pairs import possible_intersections,shared_vertex_only

POLICY = {'weld_m':1e-9, 'intersection_epsilon_m':1e-9, 'max_pairs':2000000,
          'degenerate_area_m2':1e-18, 'version':'continuous-structure-v2'}


def overlapping_pairs(xyz, epsilon=1e-9):
    """Enumerate every overlapping triangle AABB exactly once in float64."""
    if not len(xyz): return
    low,high=xyz.min(1),xyz.max(1); centres=(low+high)/2; nodes=[]
    def build(ids):
        index=len(nodes); nodes.append(None)
        lo,hi=low[ids].min(0),high[ids].max(0)
        if len(ids)<=16: nodes[index]=(lo,hi,None,None,ids)
        else:
            axis=np.ptp(centres[ids],axis=0).argmax(); middle=len(ids)//2
            order=np.argpartition(centres[ids,axis],middle)
            a,b=build(ids[order[:middle]]),build(ids[order[middle:]])
            nodes[index]=(lo,hi,a,b,None)
        return index
    build(np.arange(len(xyz))); pending=[(0,0)]
    while pending:
        left,right=pending.pop(); a,b=nodes[left],nodes[right]
        if np.any(a[0]>b[1]+epsilon) or np.any(b[0]>a[1]+epsilon): continue
        if a[4] is not None and b[4] is not None:
            x,y=np.meshgrid(a[4],b[4],indexing='ij'); x,y=x.ravel(),y.ravel()
            keep=(x!=y) if left!=right else (x<y)
            keep&=(low[x]<=high[y]+epsilon).all(1)&(low[y]<=high[x]+epsilon).all(1)
            for i,j in zip(x[keep],y[keep]): yield (int(min(i,j)),int(max(i,j)))
        elif left==right: pending.extend(((a[2],a[2]),(a[2],a[3]),(a[3],a[3])))
        elif b[4] is not None or (a[4] is None and np.max(a[1]-a[0])>=np.max(b[1]-b[0])):
            pending.extend(((a[2],right),(a[3],right)))
        else: pending.extend(((left,b[2]),(left,b[3])))


def signed_winding(xyz, points):
    result=[]
    for point in points:
        a,b,c=(xyz[:,i]-point for i in range(3))
        la,lb,lc=(np.linalg.norm(v,axis=1) for v in (a,b,c))
        numerator=np.einsum('ij,ij->i',a,np.cross(b,c))
        denominator=la*lb*lc+np.einsum('ij,ij->i',a,b)*lc+np.einsum('ij,ij->i',b,c)*la+np.einsum('ij,ij->i',c,a)*lb
        result.append(float(np.arctan2(numerator,denominator).sum()/(2*np.pi)))
    return result


def geometry_defects(vertices, triangles, *, policy=None):
    policy={**POLICY,**(policy or {})}
    v,f=np.asarray(vertices,float),np.asarray(triangles)
    areas=triangle_areas(v,f); total=float(areas.sum()); epsilon=policy['intersection_epsilon_m']
    if not len(f) or total<=0:
        return {'status':'absent','reason':'No positive-area delivery surface','topology_defect_fraction':1.,
                'solid_defect_fraction':1.,'surface_area_m2':total,'policy':policy}
    # Weld only at fixed numerical precision; retain original representative
    # coordinates rather than moving the complete mesh onto a quantized grid.
    _,first,inverse=np.unique(np.round(v/policy['weld_m']).astype(np.int64),axis=0,return_index=True,return_inverse=True)
    welded=v[first]; faces=inverse[f]; xyz=welded[faces]
    directed=np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]])
    keys,edge_ids,counts=np.unique(np.sort(directed,axis=1),axis=0,return_inverse=True,return_counts=True)
    orientation=np.where(directed[:,0]<directed[:,1],1,-1)
    sums=np.bincount(edge_ids,weights=orientation,minlength=len(keys))
    bad_edges=(counts!=2)|(sums!=0)|(keys[:,0]==keys[:,1])
    collapsed=(faces[:,0]==faces[:,1])|(faces[:,1]==faces[:,2])|(faces[:,0]==faces[:,2])
    degenerate=(areas<=policy['degenerate_area_m2'])|collapsed|(triangle_areas(welded,faces)<=policy['degenerate_area_m2'])
    top_bad=bad_edges[edge_ids].reshape(3,-1).any(0)|degenerate
    # Connected components use edge adjacency. Vertex fans are checked below,
    # so two shells touching at a point cannot masquerade as a single part.
    owner=np.tile(np.arange(len(f)),3); order=np.argsort(edge_ids,kind='stable')
    starts=np.r_[0,np.cumsum(counts)]; graph_a=[]; graph_b=[]
    vertex_links=defaultdict(list)
    for i,(a,b) in enumerate(keys):
        incident=owner[order[starts[i]:starts[i+1]]]
        for j in incident[1:]:
            graph_a.extend([int(incident[0]),int(j)]); graph_b.extend([int(j),int(incident[0])])
        for vertex in (a,b): vertex_links[int(vertex)].append(incident.tolist())
    graph=coo_matrix((np.ones(len(graph_a)),(graph_a,graph_b)),shape=(len(f),len(f))).tocsr()
    count,labels=connected_components(graph,directed=False)
    nonmanifold=[]
    for vertex,links in vertex_links.items():
        incident={x for edge in links for x in edge}
        if not incident: continue
        local=defaultdict(set)
        for edge in links:
            for x in edge[1:]: local[edge[0]].add(x);local[x].add(edge[0])
        visited=set(); pending=[next(iter(incident))]
        while pending:
            x=pending.pop()
            if x in visited: continue
            visited.add(x);pending.extend(local[x]-visited)
        if visited!=incident:
            nonmanifold.append(vertex);top_bad[list(incident)]=True
    intersection_bad=np.zeros(len(f),bool); hits=[]; pairs=0; broad_pairs=0
    usable=np.flatnonzero(~degenerate)
    population=overlapping_pairs(xyz[usable],epsilon)
    while True:
        batch=list(islice(population,4096))
        if not batch:break
        broad_pairs+=len(batch);indices=usable[np.asarray(batch)]
        indices=indices[~shared_vertex_only(welded,faces[indices[:,0]],faces[indices[:,1]],epsilon)]
        indices=indices[possible_intersections(xyz[indices[:,0]],xyz[indices[:,1]],epsilon)]
        for i,j in indices:
            pairs+=1
            if pairs>policy['max_pairs']:
                return {'status':'technical_failure','reason':'Complete intersection pair budget exceeded',
                    'candidate_pairs':pairs,'broad_phase_pairs':broad_pairs,'solid_defect_fraction':None,
                    'topology_defect_fraction':float(areas[top_bad].sum()/total),'surface_area_m2':total,'policy':policy}
            if improper_intersection(welded,faces[i],faces[j],epsilon):
                intersection_bad[[i,j]]=True;hits.append([int(i),int(j)])
    orientation_bad=np.zeros(len(f),bool); components=[]; ambiguous=False
    for label in range(count):
        ids=np.flatnonzero(labels==label); area=float(areas[ids].sum())
        row={'id':label,'triangles':len(ids),'area_m2':area,'closed_consistent':not bool(top_bad[ids].any()),
             'triangle_indices':ids.tolist()}
        # Open/intersecting shells already contribute their affected area.
        # For a closed, non-intersecting shell, a normal-offset winding test
        # distinguishes exterior walls, cavity walls and reversed shells.
        if row['closed_consistent'] and not intersection_bad[ids].any():
            i=int(ids[np.argmax(areas[ids])]); tri=xyz[i]
            normal=np.cross(tri[1]-tri[0],tri[2]-tri[0]); normal/=np.linalg.norm(normal)
            altitude=2*areas[i]/np.linalg.norm(np.roll(tri,-1,axis=0)-tri,axis=1).max()
            offset=min(altitude/100, max(64*epsilon,float(np.ptp(v,axis=0).max())*1e-7))
            if offset<=8*epsilon:
                ambiguous=True;row['orientation_status']='technical_precision_limit'
            else:
                point=tri.mean(0);winding=signed_winding(xyz[usable],[point-offset*normal,point+offset*normal])
                row.update(normal_probe_offset_m=float(offset),signed_winding_inside_outside=winding,
                           orientation_status='measured')
                row['orientation_matches_solid']=abs(winding[0]-1)<1e-5 and abs(winding[1])<1e-5
                if not row['orientation_matches_solid']:orientation_bad[ids]=True
        components.append(row)
    solid_bad=top_bad|intersection_bad|orientation_bad
    return {'status':'technical_failure' if ambiguous else 'measured',
        'reason':'Closed shell orientation precision unresolved' if ambiguous else None,
        'surface_area_m2':total, 'topology_defect_fraction':float(areas[top_bad].sum()/total),
        'solid_defect_fraction':None if ambiguous else float(areas[solid_bad].sum()/total),
        'topology_defect_area_m2':float(areas[top_bad].sum()),'solid_defect_area_m2':float(areas[solid_bad].sum()),
        'boundary_edges':int((counts==1).sum()),'nonmanifold_edges':int((counts>2).sum()),
        'inconsistent_edges':int(((counts==2)&(sums!=0)).sum()),'nonmanifold_vertices':nonmanifold,
        'candidate_pairs':pairs,'broad_phase_pairs':broad_pairs,'intersecting_pairs':hits,'components':components,
        'precision_collapsed_triangles':np.flatnonzero(collapsed).tolist(),
        'topology_defect_triangles':np.flatnonzero(top_bad).tolist(),
        'intersection_defect_triangles':np.flatnonzero(intersection_bad).tolist(),
        'orientation_defect_triangles':np.flatnonzero(orientation_bad).tolist(),
        'solid_defect_triangles':np.flatnonzero(solid_bad).tolist(),
        'largest_component_area_fraction':max(c['area_m2'] for c in components)/total,
        'policy':policy,'registration':'none','physics_scoring':False}
