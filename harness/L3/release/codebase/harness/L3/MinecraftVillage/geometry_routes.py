"""Derive test poses from exported geometry, not candidate approach hints."""
import copy
import math
from collections import defaultdict
import numpy as np
from .protocol import DOORS,CHESTS,CROPS,FURNACES,BLOCKS
from .algorithm_workflow import GridPlanner


def retarget_removed_block(plan, snapshot, target):
    """Aim at observed surviving geometry before repeated remove and place.

    The snapshot is evaluator-owned runtime evidence after the first removal.
    Candidate state strings and component names do not determine selection.
    """
    entity = next((e for e in snapshot['entities'] if e['id'] == target), None)
    components = [c for c in (entity or {}).get('components', [])
                  if c.get('visible') and c.get('collision')
                  and 'bounds_center_cm' in c and 'bounds_extent_cm' in c]
    audit = {'method': 'observed_surviving_geometry_v1', 'target': target,
             'retargeted': False, 'visible_collision_components': len(components)}
    if not components:
        audit['reason'] = 'No visible collidable target geometry remains after removal.'
        return copy.deepcopy(plan), audit
    def area(c):
        x, y, z = c['bounds_extent_cm']
        return x*y + x*z + y*z
    component = max(components, key=area)
    point = list(component['bounds_center_cm'])
    result = copy.deepcopy(plan)
    steps = []
    for step in result['steps']:
        if step.get('name') in {'action_2', 'action_3'}:
            steps.append({'op': 'look', 'name': step['name']+'_retarget', 'target_cm': point[:]})
        steps.append(step)
    result['steps'] = steps
    audit.update(retargeted=True, component=component.get('name'), look_cm=point)
    return result, audit


def actor_vertices(export):
    rows=defaultdict(list)
    for it in export['instances']:
        vs=np.asarray(export['meshes'][it['mesh']]['vertices_cm'],float)
        vs=vs@np.asarray([it['axis_x'],it['axis_y'],it['axis_z']])+it['origin_cm']
        rows[it['actor']].append(vs)
    return {k:np.concatenate(v) for k,v in rows.items()}


def derive_bindings(export,bindings,initial):
    result=copy.deepcopy(bindings);e=result['entities'];vertices=actor_vertices(export)
    points=[initial['pawn_position_cm']]+[v['approach_cm'] for v in e.values()]
    ground=float(np.median([p[2]-85 for p in points[1:]]))
    planner=GridPlanner(export,points,ground);audit={}
    def free(point):
        c=planner.cell(point)
        return all(0<=c[i]<planner.blocked.shape[i] for i in [0,1]) and not planner.blocked[c]
    for target in DOORS:
        vs=vertices[target];center=(vs.min(0)+vs.max(0))/2
        xy=vs[:,:2]-center[:2];_,vectors=np.linalg.eigh(xy.T@xy)
        normal=vectors[:,0]
        hint=np.array(e[target]['crossing_to_cm'])-e[target]['crossing_from_cm']
        if normal@hint[:2]<0:normal=-normal
        half=float(np.max(np.abs(xy@normal)))
        options=[]
        for extra in [60.,80.,100.,120.]:
            distance=max(90.,half+extra)
            a=np.r_[center[:2]-normal*distance,e[target]['crossing_from_cm'][2]]
            b=np.r_[center[:2]+normal*distance,e[target]['crossing_to_cm'][2]]
            options.append((a,b))
        a,b=next(((a,b) for a,b in options if free(a) and free(b)),options[0])
        tangent=np.array([-normal[1],normal[0]])
        halfspan=float(np.max(np.abs(xy@tangent)))
        old=copy.deepcopy(e[target]);e[target].update(approach_cm=a.tolist(),look_cm=center.tolist(),crossing_from_cm=a.tolist(),crossing_to_cm=b.tolist(),test_lane_offset_cm=(tangent*halfspan*.5).tolist())
        audit[target]={'source':'initial_exported_actor_geometry','original':old,'derived':copy.deepcopy(e[target]),'free_crossing_endpoints':[bool(free(a)),bool(free(b))]}
    for target in CHESTS+CROPS+FURNACES+BLOCKS:
        vs=vertices[target];lo,hi=vs.min(0),vs.max(0);center=(lo+hi)/2
        if target in CHESTS+FURNACES:
            door=target.split('.')[0]+'.door';start=e[door]['crossing_to_cm']
        else:start=initial['pawn_position_cm']
        candidates=[];proposals=[];perimeter=[]
        for axis in [0,1]:
            other=1-axis
            for side in [-1,1]:
                for gap in [55.,80.,110.]:
                    for fraction in [.25,.5,.75]:
                        p=center.copy();p[axis]=(lo[axis] if side<0 else hi[axis])+side*gap
                        p[other]=lo[other]+fraction*(hi[other]-lo[other]);p[2]=e[target]['approach_cm'][2]
                        perimeter.append(p.tolist())
                        if free(p):proposals.append((math.dist(p[:2],start[:2])+math.dist(p[:2],center[:2]),p.tolist()))
        for _,p in sorted(proposals,key=lambda x:x[0]):
            try:route=planner.route(start,p)
            except ValueError:continue
            actual=np.array(route[-1]);distance=math.dist(actual[:2],center[:2])
            if distance>250:continue
            cost=sum(math.dist(a[:2],b[:2]) for a,b in zip([start]+route,route))
            candidates.append((cost+distance,actual.tolist()))
            if len(candidates)>=8:break
        old=copy.deepcopy(e[target])
        if candidates:point=min(candidates,key=lambda x:x[0])[1]
        else:
            # A disconnected conservative grid does not establish a candidate
            # failure. Local fixtures do not require a route from the door:
            # choose a free perimeter pose and let the real ray/range checks
            # decide. The uninterrupted workflow separately walks to this pose.
            if not proposals:
                cells=np.argwhere(~planner.blocked)
                if not len(cells):
                    # A merged mesh AABB can conservatively cover the whole
                    # grid. Keep a geometry-derived test pose; ground rays and
                    # actual collision/range checks must still validate it.
                    point=min(perimeter,key=lambda p:math.dist(p[:2],center[:2]))
                else:
                    xy=cells*planner.resolution+planner.origin
                    idx=int(np.argmin(np.linalg.norm(xy-center[:2],axis=1)))
                    point=[float(xy[idx,0]),float(xy[idx,1]),float(e[target]['approach_cm'][2])]
            else:
                point=min(proposals,key=lambda item:math.dist(item[1][:2],center[:2]))[1]
        e[target].update(approach_cm=point,look_cm=center.tolist())
        audit[target]={'source':'reachable_exported_actor_perimeter','original':old,'derived':copy.deepcopy(e[target]),'reachable_candidates':len(candidates),
            'route_status':'planned' if candidates else 'planner_unresolved',
            'pose_selection':('reachable_perimeter' if candidates else
                              'unverified_geometry_perimeter' if not proposals and not np.any(~planner.blocked)
                              else 'nearest_free_perimeter'),
            'scoring':'Runtime ray, range, movement and state observations only; planner failure is not a failed check.'}
    return result,{'method':'geometry_derived_interaction_poses_v1','targets':audit,'candidate_approach_hints_are_not_scoring_evidence':True}
