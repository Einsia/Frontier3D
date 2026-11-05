"""Count separate thick planar outline bodies from complete triangle topology."""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely.geometry import Polygon, MultiPoint
from shapely.ops import unary_union


def parts(vertices,faces):
    v=np.asarray(vertices,float);f=np.asarray(faces,int)
    if not len(f):return []
    _,inverse=np.unique(v,axis=0,return_inverse=True);indexed=inverse[f]
    # Complete triangle equality removes duplicate evaluated instances. Mesh
    # names, object splits and vertex order do not define counted outlines.
    _,unique=np.unique(np.sort(indexed,axis=1),axis=0,return_index=True);f=f[unique];indexed=indexed[unique]
    edges=np.concatenate([indexed[:,[0,1]],indexed[:,[1,2]],indexed[:,[2,0]]])
    size=int(inverse.max())+1
    _,labels=connected_components(coo_matrix((np.ones(len(edges)),(edges[:,0],edges[:,1])),shape=(size,size)).tocsr(),directed=False)
    groups=labels[indexed[:,0]];result=[]
    for group in np.unique(groups):
        indices=np.flatnonzero(groups==group);selected=f[indices];ids,local=np.unique(selected,return_inverse=True)
        result.append((v[ids],local.reshape(-1,3)))
    return result


def planar_frame(vertices):
    points=np.unique(vertices,axis=0);center=points.mean(0)
    _,_,basis=np.linalg.svd(points-center,full_matrices=False)
    projected=(points-center)@basis.T
    return center,basis,np.ptp(projected,axis=0)


def measure(vertices,faces,*,minimum_span_m,precision_m=1e-6):
    if minimum_span_m<=0 or precision_m<=0:raise ValueError('Positive reference scale and numerical precision needed')
    if len(faces)>500000:raise ValueError('Outline topology budget exceeded; no sampled fallback')
    components=[];observations=[];candidates=[]
    for index,(v,f) in enumerate(parts(vertices,faces)):
        if len(v)<4:continue
        center,basis,span=planar_frame(v)
        row={'part_index':index,'vertices':len(v),'triangles':len(f),'center_m':center.tolist(),
             'plane_basis':basis.tolist(),'principal_spans_m':span.tolist()}
        if min(span[:2])<minimum_span_m:
            observations.append({**row,'qualifies':False,'reason':'Below the frozen minimum outline span'});continue
        if not 10*precision_m<span[2]<=.15*min(span[:2]):
            observations.append({**row,'qualifies':False,'reason':'Requires positive thickness and an approximately planar body'});continue
        xy=(v-center)@basis[:2].T;triangles=xy[f]
        first=triangles[:,1]-triangles[:,0];second=triangles[:,2]-triangles[:,0]
        areas=np.abs(first[:,0]*second[:,1]-first[:,1]*second[:,0])*.5
        polygons=[Polygon(t) for t in triangles[areas>precision_m**2]]
        union=unary_union(polygons).buffer(precision_m).buffer(-precision_m)
        polygons=list(union.geoms) if union.geom_type=='MultiPolygon' else [union] if union.geom_type=='Polygon' else []
        holes=[float(Polygon(ring).area) for polygon in polygons for ring in polygon.interiors]
        hull_area=float(union.convex_hull.area);largest=max(holes,default=0.)
        # Authored outline strokes can have open endpoints. Sparsity in the
        # projected convex envelope supports both open and closed contours.
        occupied=float(union.area);fraction=occupied/hull_area if hull_area else 1.
        qualifies=hull_area>0 and fraction<=.4
        observations.append({**row,'qualifies':qualifies,'projected_hull_area_m2':hull_area,
            'projected_occupied_area_m2':occupied,'projected_occupied_fraction':fraction,
            'hole_areas_m2':holes,'largest_hole_fraction':largest/hull_area if hull_area else 0.,
            'reason':'Sparse thick planar stroke body' if qualifies else 'Projection is predominantly filled'})
        if qualifies:candidates.append((observations[-1],v,center,basis,union.convex_hull))
    for row,v,center,basis,hull in candidates:
        containers=[]
        for outer,ov,oc,ob,oh in candidates:
            if outer is row or outer['projected_hull_area_m2']<=row['projected_hull_area_m2']:continue
            parallel=abs(float(basis[2]@ob[2]))>=.98
            close_plane=abs(float((center-oc)@ob[2]))<=2*max(row['principal_spans_m'][2],outer['principal_spans_m'][2])
            projected=MultiPoint((v-oc)@ob[:2].T).convex_hull
            if parallel and close_plane and oh.buffer(precision_m).covers(projected):containers.append(outer['part_index'])
        row['containing_outer_parts']=containers
        if containers:
            row['qualifies']=False;row['reason']='Interior detail contained in a larger coplanar outline body'
        else:components.append(row)
    return {'status':'measured','count':len(components),'components':components,'observations':observations,
        'parameters':{'minimum_span_m':minimum_span_m,'precision_m':precision_m,'maximum_occupied_fraction':.4,
            'maximum_relative_depth':.15,'minimum_thickness_m':10*precision_m},
        'registration':'none','candidate_names_or_mesh_object_count_used_as_answers':False,
        'scope':'Outer outline body count; subject identity, emission, internal details and placement remain separate target requirements'}
