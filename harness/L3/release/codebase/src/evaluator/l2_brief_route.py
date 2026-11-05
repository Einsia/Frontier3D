"""Height-field path measurements with explicit resolution and capacity limits.

Uses complete triangle evidence. Thin/vertical surfaces and low obstacles are
included; adjacent projected floors must also connect in height. This is a 2.5D
grid method, not certification of arbitrary stacked floors or full 3D motion.
"""
from collections import deque

import numpy as np
from scipy.ndimage import distance_transform_edt

from .l2_metrics import _inside,entities
from .l2_reference_numeric import triangles
from .metrics import MissingEvidence,_register


def patch(triangle,origin,cell,shape,padding=0):
    low=np.maximum(0,np.floor((triangle[:,:2].min(axis=0)-origin-padding)/cell).astype(int))
    high=np.minimum(np.array(shape[::-1])-1,np.ceil((triangle[:,:2].max(axis=0)-origin+padding)/cell).astype(int))
    if np.any(high<low):return None
    x,y=np.meshgrid(np.arange(low[0],high[0]+1),np.arange(low[1],high[1]+1))
    points=np.stack((x,y),axis=-1)*cell+origin+cell/2
    return np.s_[low[1]:high[1]+1,low[0]:high[0]+1],points


def near_triangle(points,triangle,radius):
    mask=_inside(points,triangle)
    for a,b in zip(triangle[:,:2],np.roll(triangle[:,:2],-1,axis=0)):
        edge=b-a;t=np.clip(np.sum((points-a)*edge,axis=-1)/max(float(edge@edge),1e-30),0,1)
        mask|=np.linalg.norm(points-a-t[...,None]*edge,axis=-1)<=radius
    return mask


def build_grid(evidence,p,cell):
    roads=entities(evidence,p['road_role'])
    if not roads:raise MissingEvidence('Real route surface geometry is required')
    members=[m for g in roads for m in g['members']]
    surface=np.concatenate([triangles(o,evidence) for _,o in members])
    origin=surface[:,:,:2].min(axis=(0,1))-2*cell
    shape=np.ceil((surface[:,:,:2].max(axis=(0,1))+2*cell-origin)/cell).astype(int)[::-1]
    if np.prod(shape)>4_000_000:raise MissingEvidence('Route grid exceeds four-million-cell capacity; no coarse pass')
    floor=np.full(shape,-np.inf)
    for t in surface:
        normal=np.cross(t[1]-t[0],t[2]-t[0])
        if abs(normal[2])<=1e-12:continue
        item=patch(t,origin,cell,shape)
        if item is None:continue
        index,xy=item;inside=_inside(xy,t)
        z=t[0,2]-((xy-t[0,:2])*normal[:2]).sum(axis=-1)/normal[2]
        floor[index]=np.maximum(floor[index],np.where(inside,z,-np.inf))
    blocked=np.zeros(shape,bool);excluded={n for n,_ in members};radius=cell/np.sqrt(2)
    for name,obj in evidence['scene']['objects'].items():
        if name in excluded or obj.get('type')!='MESH' or not obj.get('visible_render') or not obj.get('faces'):continue
        mesh=triangles(obj,evidence);nearest=np.full(shape,np.inf);nearest_normal=np.zeros(shape)
        center=mesh.reshape(-1,3).mean(axis=0)
        relative=mesh-center
        signed_volume=float(np.einsum('ij,ij->i',relative[:,0],np.cross(relative[:,1],relative[:,2])).sum()/6)
        orientation=1 if signed_volume>=0 else -1
        for t in mesh:
            item=patch(t,origin,cell,shape,radius)
            if item is None:continue
            index,xy=item;ground=floor[index];valid=np.isfinite(ground)
            if not valid.any():continue
            near=near_triangle(xy,t,radius);normal=np.cross(t[1]-t[0],t[2]-t[0])
            if abs(normal[2])>1e-12:
                height=t[0,2]-((xy-t[0,:2])*normal[:2]).sum(axis=-1)/normal[2]
                error=np.linalg.norm(normal[:2])/abs(normal[2])*radius
                low=np.maximum(height-error,float(t[:,2].min()));high=np.minimum(height+error,float(t[:,2].max()))
                exact=_inside(xy,t)&valid&(height>ground+p['surface_epsilon'])
                closer=exact&(height<nearest[index]);nearest[index]=np.where(closer,height,nearest[index])
                nearest_normal[index]=np.where(closer,orientation*normal[2],nearest_normal[index])
            else:low,high=float(t[:,2].min()),float(t[:,2].max())
            blocked[index]|=valid&near&(high>ground+p['surface_epsilon'])&(low<ground+p['clearance_height'])
        # A point already inside an oriented closed solid is blocked even when
        # its top face lies above the clearance band. Detached roof/floor shells
        # are not filled by a single global min/max height interval.
        if obj.get('closed'):
            blocked|=np.isfinite(floor)&np.isfinite(nearest)&(nearest_normal>0)
    free=np.isfinite(floor)&~blocked
    return floor,free,origin


def reachable(mask,floor,start,goal,origin,cell,p):
    endpoint=[]
    yy,xx=np.nonzero(mask);xy=np.column_stack((xx,yy))*cell+origin+cell/2
    if not len(xy):return False
    for selected in (start,goal):
        indices=set()
        for entity in selected:
            center=(entity['low']+entity['high'])/2
            nearby=(np.linalg.norm(xy-center[:2],axis=1)<=p['max_snap'])
            nearby&=np.abs(floor[yy,xx]-center[2])<=p['max_step']+p['surface_epsilon']
            indices.update((int(y),int(x)) for y,x in zip(yy[nearby],xx[nearby]))
        endpoint.append(indices)
    pending=deque(endpoint[0]);seen=set(pending);target=endpoint[1]
    step=p['max_step']+p['max_slope']*cell
    while pending:
        y,x=pending.popleft()
        if (y,x) in target:return True
        for dy,dx in ((-1,0),(1,0),(0,-1),(0,1)):
            other=(y+dy,x+dx)
            if (0<=other[0]<mask.shape[0] and 0<=other[1]<mask.shape[1] and mask[other]
                    and other not in seen and abs(floor[other]-floor[y,x])<=step):
                seen.add(other);pending.append(other)
    return False


@_register('l2_brief_route','road_role start_role goal_role min_width cell_size max_snap clearance_height surface_epsilon max_step max_slope','clearance_roles')
def route(check,evidence,spec):
    p=dict(check.params);start=entities(evidence,p['start_role']);goal=entities(evidence,p['goal_role'])
    if not start or not goal:raise MissingEvidence('Geometric route endpoint patches are required')
    for role in p.get('clearance_roles',[]):
        selected=entities(evidence,role)
        if not selected:raise MissingEvidence('Geometry for vehicle clearance is required: '+role)
        p['clearance_height']=max(p['clearance_height'],*(float(g['dimensions'][2]) for g in selected))
    cell=p['cell_size'];floor,free,origin=build_grid(evidence,p,cell)
    distance=distance_transform_edt(free)*cell
    threshold=p['min_width']*.99/2
    # Explicit uncertainty band from raster cells. Never silently round a
    # borderline path up to a passing width.
    safe=free&(distance-cell*np.sqrt(2)>=threshold)
    optimistic=free&(distance+cell*np.sqrt(2)>=threshold)
    passed=all(reachable(safe,floor,[a],[b],origin,cell,p) for a in start for b in goal)
    uncertain=not passed and all(reachable(optimistic,floor,[a],[b],origin,cell,p) for a in start for b in goal)
    details={'connected_with_clear_width':passed,'min_width_m':p['min_width'],'cell_size_m':cell,
        'width_uncertainty_bound_m':2*np.sqrt(2)*cell,'clearance_height_m':p['clearance_height'],
        'road_cells':int(np.isfinite(floor).sum()),'free_cells':int(free.sum()),'resolution_limited':uncertain,
        'required_endpoint_pairs':len(start)*len(goal),
        'scope':'Complete triangles rasterized as a 2.5D route; explicit step/slope/clearance and finite grid resolution',
        'threshold_status':'pilot_not_calibrated'}
    if uncertain:raise MissingEvidence('Route width lies within grid uncertainty; finer case-specific sampling required')
    return float(passed),details
