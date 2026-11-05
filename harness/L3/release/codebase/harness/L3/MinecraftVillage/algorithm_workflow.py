"""Geometry-derived routes and one uninterrupted resource workflow.

The conservative 2.5D planner proposes paths; actual pawn movement verifies them.
Failure to find a path is planner-unresolved, never proof of an unusable scene.
"""
import heapq
import math
import numpy as np
from scipy.ndimage import binary_dilation

from .algorithm_reference import world_bounds
from .protocol import DOORS, validate_plan, read_json
from .inventory import counts


def door_walk_plan(bindings):
    """Test matched closed/open/reclosed paths through center and side lanes."""
    steps=[];checks=[]
    def add(op,name,**kw):steps.append(dict(op=op,name=name,**kw))
    for i,target in enumerate(DOORS):
        b=bindings['entities'][target];offset=b.get('test_lane_offset_cm')
        offsets=[[0.,0.]] if offset is None else [[0.,0.],offset,[-v for v in offset]]
        lanes=[]
        for k,delta in enumerate(offsets):
            start=list(b['crossing_from_cm']);end=list(b['crossing_to_cm'])
            for axis in [0,1]:start[axis]+=delta[axis];end[axis]+=delta[axis]
            lanes.append({'prefix':f'd{i}_l{k}','start':start,'destination':end})
        for state in ['closed','open','reclosed']:
            prefix=f'd{i}_{state}'
            if state!='closed':
                add('fixture',prefix+'_approach',purpose='local_test_setup',position_cm=b['approach_cm'])
                add('look_entity',prefix+'_aim',target=target)
                add('interact',prefix+'_action',target=target,action='use')
                add('wait',prefix+'_settle',seconds=1.5)
            for lane in lanes:
                prefix=lane['prefix']+'_'+state
                add('fixture',prefix+'_from',purpose='local_test_setup',position_cm=lane['start'])
                add('walk_to',prefix+'_walk',target_cm=lane['destination'],seconds=4)
                add('snapshot',prefix+'_end');add('capture',prefix+'_view')
        checks.append({'target':target,'lanes':lanes})
    return validate_plan({'version':1,'kind':'local','steps':steps}),checks


def diagnose_doors(folder,checks):
    rows={}
    for check in checks:
        lanes=check.get('lanes',[check]);observations=[]
        for lane in lanes:
            states={}
            for state in ['closed','open','reclosed']:
                f=read_json(folder/(lane['prefix']+'_'+state+'_end.json'))
                error=math.dist(f['pawn_position_cm'][:2],lane['destination'][:2])
                states[state]={'error_cm':error,'reached':error<=50,'position_cm':f['pawn_position_cm']}
            opened=states['open']['reached']
            observations.append({'prefix':lane['prefix'],'closed_barrier':opened and not states['closed']['reached'],
                'opened_passage':opened,'closed_again':opened and not states['reclosed']['reached'],
                'actual_walk_through':opened,'observations':states})
        best=max(observations,key=lambda a:(a['opened_passage'],a['closed_barrier']+a['closed_again']))
        rows[check['target']]={**best,'all_lanes':observations}
    return {'status':'measured','method':'actual_character_matched_three_lanes_v2','targets':rows,
            'scope':'Same matched path must demonstrate closed/open/reclosed behavior; center plus two geometry-derived side lanes.'}


class GridPlanner:
    def __init__(self, export, points, ground_z, resolution=12.5, radius=35.):
        self.resolution=resolution
        p=np.asarray(points);self.origin=np.floor((p[:,:2].min(0)-500)/resolution)*resolution
        high=np.ceil((p[:,:2].max(0)+500)/resolution)*resolution
        shape=np.ceil((high-self.origin)/resolution).astype(int)+1
        if np.prod(shape)>2_000_000:raise ValueError('Planner extent exceeds fixed budget')
        occupied=np.zeros(tuple(shape),bool)
        self.ground_z=ground_z
        self.heights=np.full(tuple(shape),ground_z,dtype=float)
        bounds=[]
        for item in export['instances']:
            if item['actor'] in DOORS or not item.get('blocks_pawn'):continue
            v=np.asarray(export['meshes'][item['mesh']]['vertices_cm'],float)
            a=np.asarray([item['axis_x'],item['axis_y'],item['axis_z']])
            v=v@a+item['origin_cm'];lo,hi=v.min(0),v.max(0)
            x0,y0=np.floor((lo[:2]-self.origin)/resolution).astype(int)
            x1,y1=np.ceil((hi[:2]-self.origin)/resolution).astype(int)
            x0,y0=max(0,x0),max(0,y0);x1,y1=min(shape[0]-1,x1),min(shape[1]-1,y1)
            if x0>x1 or y0>y1:continue
            region=(slice(x0,x1+1),slice(y0,y1+1))
            if item.get('role') in {'terrain','path'}:
                self.heights[region]=np.maximum(self.heights[region],hi[2])
            else:bounds.append((lo,hi))
        for lo,hi in bounds:
            # Inflate continuous bounds before rasterization. Rounding outward
            # first and dilating again incorrectly closes legitimate doorways.
            a=np.ceil((lo[:2]-radius-self.origin)/resolution).astype(int)
            b=np.floor((hi[:2]+radius-self.origin)/resolution).astype(int)
            a=np.maximum(a,0);b=np.minimum(b,shape-1)
            if np.any(a>b):continue
            region=(slice(a[0],b[0]+1),slice(a[1],b[1]+1))
            # Terrain-relative vertical occupancy avoids labelling a pawn
            # standing on a raised landform as embedded in an obstacle.
            floor=self.heights[region]
            occupied[region]|=(hi[2]>floor+45)&(lo[2]<floor+175)
        self.blocked=occupied

    def cell(self,point):return tuple(np.rint((np.asarray(point[:2])-self.origin)/self.resolution).astype(int))

    def nearby_free(self,point):
        c=self.cell(point);candidates=[]
        n=int(math.floor(100/self.resolution))
        for dx in range(-n,n+1):
            for dy in range(-n,n+1):
                if (dx*dx+dy*dy)*self.resolution**2>10000:continue
                a=(c[0]+dx,c[1]+dy)
                if 0<=a[0]<self.blocked.shape[0] and 0<=a[1]<self.blocked.shape[1] and not self.blocked[a]:
                    candidates.append((dx*dx+dy*dy,a))
        if not candidates:raise ValueError('Planner endpoint blocked within 100 cm snap budget')
        return min(candidates)[1]

    def route(self,start,end):
        s,g=self.nearby_free(start),self.nearby_free(end)
        heap=[(0,0,s)];cost={s:0};parent={};expanded=0
        while heap:
            _,d,u=heapq.heappop(heap)
            if d!=cost.get(u):continue
            if u==g:break
            expanded+=1
            if expanded>500000:raise ValueError('Planner expansion budget exhausted')
            for dx,dy in [(1,0),(-1,0),(0,1),(0,-1)]:
                v=(u[0]+dx,u[1]+dy)
                if not(0<=v[0]<self.blocked.shape[0] and 0<=v[1]<self.blocked.shape[1]) or self.blocked[v]:continue
                dh=self.heights[v]-self.heights[u]
                if dh>45 or dh < -200:continue
                nd=d+1
                if nd<cost.get(v,math.inf):
                    cost[v]=nd;parent[v]=u;heapq.heappush(heap,(nd+abs(v[0]-g[0])+abs(v[1]-g[1]),nd,v))
        else:raise ValueError('No conservative grid route found')
        path=[g]
        while path[-1]!=s:path.append(parent[path[-1]])
        path.reverse();keep=[path[0]]
        for i in range(1,len(path)-1):
            if (path[i][0]-path[i-1][0],path[i][1]-path[i-1][1])!=(path[i+1][0]-path[i][0],path[i+1][1]-path[i][1]):keep.append(path[i])
        keep.append(g)
        points=[[*((np.asarray(c)*self.resolution)+self.origin),end[2]] for c in keep]
        # The public approach is a hint, not an instruction to stand inside a
        # table. Use its nearest free point; the real interaction ray and range
        # checks decide whether the target is reachable from that point.
        return [list(map(float,p)) for p in points]


def make_workflow(export,bindings,initial):
    e=bindings['entities'];spawn=initial['pawn_position_cm']
    points=[spawn]+[v['approach_cm'] for v in e.values()]
    z=float(np.median([p[2]-85 for p in points[1:]]))
    planner=GridPlanner(export,points,z)
    steps=[];route_records=[];planner_fallbacks=[];current=list(spawn);opened=set()
    def add(op,name=None,**kw):
        name=name or f's{len(steps):04d}';steps.append(dict(op=op,name=name,**kw));return name
    def walk(point,label):
        nonlocal current
        try:route=planner.route(current,point)
        except ValueError as error:
            # Preserve a real movement trial when the conservative proposal
            # planner cannot connect endpoints. No teleport or inferred failure:
            # the character still attempts the segment under engine collision.
            route=[list(point)]
            planner_fallbacks.append({'label':label,'start_cm':list(current),
                                      'target_cm':list(point),'reason':str(error),
                                      'probe':'direct_collision_constrained_walk'})
        for p in route:
            distance=math.dist(current[:2],p[:2])
            if distance<15:continue
            # Bound segment duration and length while preserving the polyline.
            start=list(current);n=max(1,math.ceil(distance/2000))
            for i in range(1,n+1):
                target=(np.asarray(start)+(np.asarray(p)-start)*i/n).tolist()
                name=add('walk_to',target_cm=target,seconds=min(30.,max(2.,math.dist(current[:2],target[:2])/350+2)))
                add('snapshot',name+'_end');route_records.append({'step':name,'target_cm':target,'label':label})
                current=target
        if route:current=list(route[-1])
    def use(target,action):
        if target in DOORS or target.endswith('.chest'):add('look_entity',target=target)
        else:add('look',target_cm=e[target]['look_cm'])
        add('interact',target=target,action=action);add('wait',seconds=1.5 if action=='use' else .5)
    def enter(door):
        walk(e[door]['crossing_from_cm'],door+'_outside')
        if door not in opened:use(door,'use');opened.add(door)
        walk(e[door]['crossing_to_cm'],door+'_inside')
    def leave(door):walk(e[door]['crossing_from_cm'],door+'_exit')
    def checkpoint(name):add('snapshot',name);add('capture',name+'_view')
    checkpoint('chain_initial')
    enter('house01.door');walk(e['house01.chest']['approach_cm'],'seed_chest')
    use('house01.chest','use');use('house01.chest','take');checkpoint('seed_taken')
    use('house01.chest','take');checkpoint('seed_repeated');leave('house01.door')
    walk(e['farm.crop01']['approach_cm'],'crop');checkpoint('crop_before')
    use('farm.crop01','harvest');checkpoint('crop_harvested')
    use('farm.crop01','plant');checkpoint('crop_replanted')
    enter('smithy01.door');walk(e['smithy01.furnace']['approach_cm'],'furnace');checkpoint('before_processing')
    add('look',target_cm=e['smithy01.furnace']['look_cm']);add('interact',target='smithy01.furnace',action='process')
    add('wait',seconds=.3);checkpoint('furnace_active');add('wait',seconds=3);checkpoint('processed')
    use('smithy01.furnace','process');checkpoint('process_repeated');leave('smithy01.door')
    enter('storehouse.door');walk(e['storehouse.chest']['approach_cm'],'storage')
    use('storehouse.chest','use');use('storehouse.chest','take');checkpoint('storage_taken');leave('storehouse.door')
    enter('house01.door');walk(e['house01.chest']['approach_cm'],'return_house')
    use('house01.chest','take');checkpoint('house_revisited');leave('house01.door')
    walk(e['farm.crop01']['approach_cm'],'return_crop');use('farm.crop01','harvest');checkpoint('immature_reharvest')
    plan=validate_plan({'version':1,'kind':'e2e','steps':steps})
    return plan,{'planner':'terrain_relative_AABB_Astar_v1','resolution_cm':12.5,'radius_cm':35,
                 'ground_z_cm':z,'approach_snap_budget_cm':100,'routes':route_records,'teleports':0,'planner_fallbacks':planner_fallbacks,
                 'scope':'Runtime follows planner-proposed routes; failure is not proof that every possible path is blocked.'}


def diagnose(folder,metadata):
    from .resource_chain import diagnose as chain_diagnose
    resource=chain_diagnose(folder)
    rows=[]
    for r in metadata['routes']:
        frame=read_json(folder/(r['step']+'_end.json'))
        error=math.dist(frame['pawn_position_cm'][:2],r['target_cm'][:2])
        rows.append({**r,'observed_cm':frame['pawn_position_cm'],'error_cm':error,'passed':error<=50})
    frames=[read_json(folder/'initial.json')]+[read_json(p) for p in sorted(folder.glob('trajectory_*.json'))]+[read_json(folder/'final.json')]
    speeds=[math.dist(a['pawn_position_cm'],b['pawn_position_cm'])/(b['time']-a['time']) for a,b in zip(frames,frames[1:]) if b['time']>a['time']]
    no_teleport=max(speeds,default=0)<1500
    inv=resource['inventory'];complete=all(r['passed'] for r in rows) and no_teleport and inv['failed']==0 and inv['unresolved']==0
    complete=complete and all(resource['geometry_checks'].get(k) is True for k in ['harvest_changes_visible_crop','plant_restores_visible_crop','replanted_crop_persists'])
    return {'status':'measured','continuous_walk_verified':complete,'waypoints':rows,
            'route_success_fraction':sum(r['passed'] for r in rows)/len(rows) if rows else None,
            'no_teleport_observed':no_teleport,'max_observed_speed_cm_s':max(speeds,default=0),
            'workflow_success':complete,'resource_chain':resource,
            'limitation':'One fixed geometry-derived route; failure does not prove no alternative route exists.'}
