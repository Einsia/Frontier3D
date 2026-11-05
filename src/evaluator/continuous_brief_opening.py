"""Interior aperture dimensions and complete-scene bounded passage probes."""
import math
import numpy as np
from .continuous_brief_numeric import actual_entities, interval_error, population, missing
from .continuous_numeric import line_intersections
from .continuous_sceneedit_surface import join
from .continuous_surface import triangle_areas, topology_defects


def positive(mesh, origin, direction):
    hits=line_intersections(*mesh,origin,direction)
    return hits[hits>1e-8]


def axes(mesh):
    """Area moments are invariant to subdivision and triangle/vertex ordering."""
    v,f=mesh;t=v[f];weights=triangle_areas(v,f);total=float(weights.sum())
    if total<=1e-12:return None
    xy=t[:,:,:2];sums=xy.sum(axis=1)
    center=np.sum(weights[:,None]*sums/3,axis=0)/total
    moment=(np.einsum('ni,nj->nij',sums,sums)+np.einsum('nki,nkj->nij',xy,xy))/12
    covariance=np.sum(weights[:,None,None]*moment,axis=0)/total-np.outer(center,center)
    eigenvalues,basis=np.linalg.eigh(covariance)
    if eigenvalues[-1]-eigenvalues[0]<=1e-10*max(eigenvalues[-1],1.):
        raise ValueError('Opening footprint has no unique principal width axis; explicit reviewed section required')
    a=basis[:,-1]
    if a[np.argmax(np.abs(a))]<0:a=-a
    width=np.array([*a,0.]);depth=np.cross([0.,0.,1.],width)
    projected=np.column_stack((t.reshape(-1,3)@width,t.reshape(-1,3)@depth))
    midpoint=(projected.min(axis=0)+projected.max(axis=0))/2
    return width,depth,midpoint[0]*width+midpoint[1]*depth,float(np.ptp(projected[:,1]))


def measure(check,roles,minimum_entities,scene_objects,evidence):
    p=check['params'];selected,selection=actual_entities(roles.get(p['role'],[]))
    support=join([e['mesh'] for e in roles.get(p['support_role'],[])])
    # Closed shells require an interior test even when both probe endpoints lie
    # inside one solid and its surface intersections lie outside the segment.
    objects=[]
    for identity,mesh in scene_objects:
        if not len(mesh[1]):continue
        topo=topology_defects(*mesh,weld_m=1e-6)
        points=mesh[0][mesh[1]].reshape(-1,3)
        objects.append((identity,mesh,topo['boundary_edges']==0 and topo['nonmanifold_edges']==0,
                        points.min(axis=0),points.max(axis=0)))
    quantities=[]
    for entity in population(selected,minimum_entities[p['role']]):
        if entity is None or not len(support[1]):
            quantities.append(missing('Required opening or local support surface absent'));continue
        mesh=entity['mesh'];basis=axes(mesh)
        if basis is None:
            quantities.append(missing('Opening has no actual area',entity=entity['id']));continue
        width_axis,depth_axis,center,depth=basis;points=mesh[0][mesh[1]].reshape(-1,3)
        # A partly embedded foundation starts inside the support solid. Casting
        # down from that foundation would hit its underside, treating the
        # basement as the walkable floor. Use the actual upper support envelope
        # at this XY, as in the published single-floor height-field protocol.
        center[2]=max(float(points[:,2].max()),float(support[0][support[1]][:,:,2].max()))+1.
        hits=positive(support,center,[0.,0.,-1.])
        base={'entity':entity['id'],'width_axis':width_axis.tolist(),'depth_axis':depth_axis.tolist(),
              'footprint_center_world_m':center.tolist(),'opening_depth_m':depth,
              'support_ray_origin_world_m':center.tolist(),
              'support_policy':'Highest actual support surface at the opening XY; no foundation-minimum or underside proxy'}
        if not len(hits):
            quantities.append(missing('Actual ground below opening absent',**base));continue
        ground=float(center[2]-hits[0]);center[2]=ground+1e-5
        above=positive(mesh,center,[0.,0.,1.])
        if not len(above):
            quantities.append(missing('Actual lintel or arch above opening center absent',ground_height_m=ground,**base));continue
        height=float(above[0]+1e-5);side=center.copy();side[2]=ground+min(height*.01,.01)
        left,right=positive(mesh,side,-width_axis),positive(mesh,side,width_axis)
        base.update(ground_height_m=ground,interior_height_m=height,side_probe_world_m=side.tolist(),
                    left_hits_m=left.tolist(),right_hits_m=right.tolist())
        if not len(left) or not len(right):
            quantities.append(missing('An actual interior side boundary is absent at the public low section',**base));continue
        width=float(left[0]+right[0]);observations=[interval_error(width,p['min_width'],None,p['relative_tolerance'])]
        if p['min_height'] is not None:observations.append(interval_error(height,p['min_height'],None,p['relative_tolerance']))
        probe_height=p['min_height'] if p['min_height'] is not None else height*.5
        probe_width=p['min_width'];tolerance=p['relative_tolerance'];probes=[]
        for x in np.linspace(-.5,.5,11)*probe_width*(1-tolerance):
            for z in np.linspace(.01,.99,11)*probe_height*(1-tolerance):
                if p['passage_shape']=='ball':
                    radius=probe_width*(1-tolerance)/2
                    if x*x+(z-radius)**2>radius*radius:continue
                elif p['passage_shape']!='rectangle':raise ValueError('Unknown passage shape')
                start=center+width_axis*x-depth_axis*(depth/2+1e-4);start[2]=ground+z
                blockers=[]
                end=start+depth_axis*(depth+2e-4)
                for identity,other,closed,low,high in objects:
                    if np.any(np.minimum(start,end)>high+1e-8) or np.any(np.maximum(start,end)<low-1e-8):continue
                    hits=positive(other,start,depth_axis)
                    crossing=bool(len(hits) and hits[0]<depth+2e-4)
                    # Off-axis parity avoids double intersections at a mesh
                    # seam on the prescribed travel axis. Boundary tangencies
                    # are conservative at the declared complete-mesh precision.
                    inside=(closed and np.all(start>=low-1e-8) and np.all(start<=high+1e-8)
                            and len(positive(other,start,[.81231,.32717,.48291]))%2==1)
                    if crossing or inside:blockers.append({'object':identity,'first_hit_m':float(hits[0]) if len(hits) else None,'starts_inside':bool(inside)})
                probes.append({'origin_world_m':start.tolist(),'segment_length_m':depth+2e-4,'blockers':blockers})
        if not probes:raise ValueError('Public passage probe population empty')
        fraction=sum(not r['blockers'] for r in probes)/len(probes)
        base.update(interior_width_m=width,observations=observations,passage_probes=probes,
                    sampled_clear_fraction=fraction,required_width_m=probe_width,required_height_m=p['min_height'])
        if not fraction:
            quantities.append(missing('Every prescribed through-depth passage probe is blocked',**base));continue
        error=max(o['normalized_error'] for o in observations)-math.log2(fraction)
        quantities.append({'status':'measured','normalized_errors':[error],**base,
            'aggregation':'Worst interior dimension error multiplied by the complete bounded-probe clear fraction'})
    return {'status':'measured','quantities':quantities,'evidence':evidence,'native_check':check,'entity_selection':selection,
        'coordinate_space':'world_metres','registration':'none','scope':'Area-weighted opening axes, actual interior surfaces and at most 121 complete-scene passage rays',
        'limitations':'Finite probes retain the published sampling contract; openings with ambiguous footprint orientation need an explicit section.'}
