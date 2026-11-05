"""Continuous bottleneck widths on the public 2.5D route grid with refinement."""
import hashlib
import heapq
import math
import numpy as np
from scipy.ndimage import distance_transform_edt
from .continuous_brief_planar_route import endpoint
from .continuous_surface import topology_defects
from .l2_brief_route import build_grid


def evidence_scene(road,obstacles):
    def obj(mesh,role=None):
        v,f=mesh;t=v[f];topology=topology_defects(v,f,weld_m=1e-6)
        result={'type':'MESH','visible_render':True,'faces':len(f),'surface_triangles':t,
            'bounds':[t.min(axis=(0,1)).tolist(),t.max(axis=(0,1)).tolist()],
            'closed':topology['boundary_edges']==0 and topology['nonmanifold_edges']==0}
        if role:result['role']=role
        return result
    objects={'road':obj(road,'road')}
    objects.update({str(i)+':'+name:obj(mesh) for i,(name,mesh) in enumerate(obstacles) if len(mesh[1])})
    return {'scene':{'objects':objects}}


def widest(floor,free,distances,start,goal,origin,cell,p):
    yy,xx=np.nonzero(free);xy=np.column_stack((xx,yy))*cell+origin+cell/2
    candidates=[]
    for point in (start,goal):
        mask=(np.linalg.norm(xy-point[:2],axis=1)<=p['max_snap'])
        mask&=np.abs(floor[yy,xx]-point[2])<=p['max_step']+p['surface_epsilon']
        candidates.append((yy[mask],xx[mask]))
    if any(not len(v[0]) for v in candidates):return None,'Endpoint cannot snap at the published distance/height tolerance',0
    targets=np.zeros(free.shape,bool);targets[candidates[1]]=True
    best=np.full(free.shape,-1.);pending=[];visited=0
    for y,x in zip(*candidates[0]):
        value=float(distances[y,x]);best[y,x]=value;heapq.heappush(pending,(-value,int(y),int(x)))
    limit=p['max_step']+p['max_slope']*cell
    while pending:
        minus,y,x=heapq.heappop(pending);value=-minus
        if value<best[y,x]:continue
        visited+=1
        if targets[y,x]:return value,None,visited
        for dy,dx in ((-1,0),(1,0),(0,-1),(0,1)):
            ny,nx=y+dy,x+dx
            if (0<=ny<free.shape[0] and 0<=nx<free.shape[1] and free[ny,nx]
                    and abs(floor[ny,nx]-floor[y,x])<=limit):
                other=min(value,float(distances[ny,nx]))
                if other>best[ny,nx]:best[ny,nx]=other;heapq.heappush(pending,(-other,ny,nx))
    return None,'Complete public 2.5D grid has no traversable endpoint connection',visited


def array_sha(array):return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def measure(road,obstacles,starts,goals,parameters,evidence):
    p={**parameters,'road_role':'road'}
    if not len(road[1]) or not starts or not goals:
        return {'status':'absent','reason':'Required road or nominated endpoint patches absent','evidence':evidence}
    scene=evidence_scene(road,obstacles);points=[(s['id'],endpoint(s),g['id'],endpoint(g)) for s in starts for g in goals]
    cell=p['cell_size'];rounds=[]
    for iteration in range(12):
        floor,free,origin=build_grid(scene,p,cell);distances=distance_transform_edt(free)*cell
        rows=[];uncertain=False
        for sid,start,gid,goal in points:
            row={'start_entity':sid,'goal_entity':gid,'start_world_m':None if start is None else start.tolist(),
                'goal_world_m':None if goal is None else goal.tolist()}
            if start is None or goal is None:
                rows.append({'status':'absent','reason':'Actual endpoint surface absent',**row});continue
            radius,reason,visited=widest(floor,free,distances,start,goal,origin,cell,p)
            if radius is None:
                rows.append({'status':'absent','reason':reason,'visited_cells':visited,**row});continue
            lower=max(0.,2*(radius-cell*math.sqrt(2)));upper=2*(radius+cell*math.sqrt(2))
            allowed=.99*p['min_width'];half=.01*p['min_width']
            lo_error=max(allowed-lower,0.)/half;hi_error=max(allowed-upper,0.)/half
            interval=[2.**-lo_error,2.**-hi_error];uncertain|=interval[1]-interval[0]>.001
            rows.append({'status':'measured',**row,'actual_grid_bottleneck_width_m':2*radius,
                'width_interval_m':[lower,upper],'continuous_score_interval':interval,'visited_cells':visited,
                'allowed_width_m':allowed,'half_scale_m':half,'normalized_errors':[lo_error]})
        rounds.append({'cell_size_m':cell,'grid_shape':list(floor.shape),'origin_world_xy_m':origin.tolist(),
            'floor_sha256':array_sha(floor),'free_sha256':array_sha(free),'distance_sha256':array_sha(distances),
            'road_cells':int(np.isfinite(floor).sum()),'free_cells':int(free.sum()),'endpoint_pairs':rows})
        if not uncertain:break
        cell/=2
    else:raise ValueError('Continuous height-field route uncertainty remains after twelve refinements')
    return {'status':'measured','quantities':rows,'evidence':evidence,'parameters':parameters,'grid_rounds':rounds,
        'registration':'none','scope':'Complete triangles, thin/vertical obstacles and closed solids on the published four-neighbor height-field grid',
        'limitations':'Finite 2.5D grid with published step/slope and endpoint rules. Width interval uses the inherited raster uncertainty; capacity exhaustion remains technical missingness.',
        'score_precision':.001,'width_policy':'Conservative endpoint-pair bottleneck with refinement when the continuous score interval is wider than 0.001'}
