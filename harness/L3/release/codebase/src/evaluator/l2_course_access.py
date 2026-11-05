"""Actual mini-golf start access and obstacle placement from complete geometry."""
import numpy as np
from scipy.ndimage import distance_transform_edt

from .l2_brief_relations import course_assignments,groups,validate as validate_relations
from .l2_brief_route import build_grid,reachable
from .l2_reference_numeric import triangles
from .metrics import MissingEvidence,_register


COMMON='lane_role ball_role cup_role obstacle_role contact_tolerance_m parallel_tolerance_degrees end_fraction obstacle_min_progress'


def clip_polygon(points,normal,limit):
    """Clip a convex 2D/3D polygon to dot(point,normal) <= limit."""
    result=[]
    for a,b in zip(points,np.roll(points,-1,axis=0)):
        da=float(a@normal-limit);db=float(b@normal-limit)
        if da<=0:result.append(a)
        if (da<=0)!=(db<=0):result.append(a+(b-a)*(da/(da-db)))
    return np.asarray(result,float).reshape(-1,len(normal))


def clip_surface(surface,normal,limit):
    pieces=[]
    for triangle in surface:
        polygon=clip_polygon(triangle,normal,limit)
        for i in range(1,len(polygon)-1):pieces.append([polygon[0],polygon[i],polygon[i+1]])
    return np.asarray(pieces,float).reshape(-1,3,3)


def area(polygon):
    if len(polygon)<3:return 0.
    return abs(float(np.sum(polygon[:,0]*np.roll(polygon[:,1],-1)-polygon[:,1]*np.roll(polygon[:,0],-1)))/2)


def frame(row):
    origin,length,_,axis,_=row['frame']
    direction=axis*(1 if (row['cup_point'][:2]-row['ball_point'][:2])@axis>0 else -1)
    return direction,origin-direction*length,length*2


def path_overlaps_course(path,row,tolerance):
    """Intersect full projected triangles beyond the allowed start seam."""
    direction,start,_=frame(row);limit=float(start@direction+tolerance)
    lane=row['surface'][:,:,:2]
    edges1=lane[:,1]-lane[:,0];edges2=lane[:,2]-lane[:,0]
    cross=edges1[:,0]*edges2[:,1]-edges1[:,1]*edges2[:,0]
    lane=lane[np.abs(cross)>1e-12];cross=cross[np.abs(cross)>1e-12]
    low=lane.min(1);high=lane.max(1);pairs=0
    for source in path:
        polygon=clip_polygon(source[:,:2],-direction,-limit)
        if area(polygon)<=1e-10:continue
        candidates=np.nonzero(np.all(high>=polygon.min(0)-1e-9,axis=1)&np.all(low<=polygon.max(0)+1e-9,axis=1))[0]
        pairs+=len(candidates)
        if pairs>1_000_000:raise MissingEvidence('Visitor/course overlap exceeds one million triangle pairs')
        for index in candidates:
            clipped=polygon
            for a,b in zip(lane[index],np.roll(lane[index],-1,axis=0)):
                edge=b-a;normal=np.array([edge[1],-edge[0]])*np.sign(cross[index])
                clipped=clip_polygon(clipped,normal,float(a@normal))
                if len(clipped)<3:break
            overlap=area(clipped)
            if overlap>1e-8:return {'passed':False,'overlap_witness_area_m2':overlap,'triangle_pairs_checked':pairs}
    return {'passed':True,'overlap_witness_area_m2':0.,'triangle_pairs_checked':pairs}


@_register('l2_course_visitor_route',COMMON+' visitor_role min_width cell_size max_step max_slope surface_epsilon clearance_height seam_overlap_m')
def visitor_route(check,evidence,spec):
    p=check.params;rows,errors=course_assignments(evidence,p)
    if errors:return 0.,{'errors':errors,'actual_starts':[]}
    paths=groups(evidence,p['visitor_role']);surface=np.concatenate([s for _,s in paths])
    outside=[{'lane':r['lane']['id'],**path_overlaps_course(surface,r,p['seam_overlap_m'])} for r in rows]
    if not all(r['passed'] for r in outside):return 0.,{'outside_lanes':outside,'actual_starts':[]}
    # Only explicitly selected members may enter the evaluator's route layer.
    # A candidate can author any role string, including this internal spelling.
    objects={name:{**obj,'role':None} for name,obj in evidence['scene']['objects'].items()}
    for entity,_ in paths:
        for name,_ in entity['members']:objects[name].update(role='__visitor_network',entity='__visitor_network')
    starts=[]
    for i,row in enumerate(rows):
        direction,start,length=frame(row)
        padding=p['min_width']/2+2*np.sqrt(2)*p['cell_size']
        strip=clip_surface(row['surface'],np.array([*direction,0.]),float(start@direction+length*p['end_fraction']+padding))
        if not len(strip):raise MissingEvidence('Actual lane start surface required')
        name='__evaluator_start_strip_'+str(i)
        while name in objects:name+='_'  # Candidate names cannot replace evaluator-owned geometry.
        objects[name]={'type':'MESH','role':'__visitor_network','entity':'__visitor_network',
            'visible_render':True,'faces':len(strip),'bounds':[strip.min((0,1)).tolist(),strip.max((0,1)).tolist()],
            'surface_triangles':strip.tolist()}
        for name,_ in row['balls'][0][0]['members']:objects.pop(name)
        xy=row['ball_point'][:2];z=float(row['index'].top([xy])[0]);point=np.array([*xy,z])
        starts.append({'low':point,'high':point})
    selected={**evidence,'scene':{**evidence['scene'],'objects':objects}}
    parameters={**p,'road_role':'__visitor_network','max_snap':2*p['cell_size']}
    floor,free,origin=build_grid(selected,parameters,p['cell_size'])
    distance=distance_transform_edt(free)*p['cell_size'];radius=p['min_width']*.99/2
    safe=free&(distance-p['cell_size']*np.sqrt(2)>=radius)
    optimistic=free&(distance+p['cell_size']*np.sqrt(2)>=radius)
    passed=all(reachable(safe,floor,[starts[0]],[goal],origin,p['cell_size'],parameters) for goal in starts)
    uncertain=not passed and all(reachable(optimistic,floor,[starts[0]],[goal],origin,p['cell_size'],parameters) for goal in starts)
    if uncertain:raise MissingEvidence('Actual visitor access width lies within the published grid uncertainty')
    return float(passed),{'connected_actual_starts':bool(passed),'actual_starts':[
        {'lane':row['lane']['id'],'ball':row['balls'][0][0]['id'],'point':point['low'].tolist()} for row,point in zip(rows,starts)],
        'outside_lanes':outside,'endpoint_markers_used':False,'min_width_m':p['min_width'],
        'clearance_height_m':p['clearance_height'],'cell_size_m':p['cell_size'],
        'width_uncertainty_m':2*np.sqrt(2)*p['cell_size'],'free_cells':int(free.sum()),
        'scope':'Common visitor network plus actual first-end lane regions, reaching each real ball start; balls excluded as endpoint occupants. Finite 2.5D grid, not general 3D motion.',
        'threshold_status':'published_pilot_pending_calibration'}


@_register('l2_course_obstacle_placement',COMMON+' windmill_role castle_role')
def obstacle_placement(check,evidence,spec):
    p=check.params;rows,errors=course_assignments(evidence,p)
    if errors:return 0.,{'errors':errors,'placements':[]}
    direction,_,_=frame(rows[0]);left=np.array([-direction[1],direction[0]])
    if any(frame(row)[0]@direction<np.cos(np.radians(p['parallel_tolerance_degrees'])) for row in rows):
        raise MissingEvidence('A common start-to-cup direction is required to define left/right')
    ordered=sorted(rows,key=lambda r:float(r['frame'][0]@left),reverse=True)
    results=[]
    for role,target in [(p['windmill_role'],ordered[0]),(p['castle_role'],ordered[1])]:
        selected=groups(evidence,role);matches=[]
        for entity,surface in selected:
            vertices=np.unique(surface.reshape(-1,3),axis=0)
            feet=vertices[vertices[:,2]<=vertices[:,2].min()+p['contact_tolerance_m']]
            if len(feet)>20_000:raise MissingEvidence('Obstacle base exceeds 20,000 full vertices')
            assigned=[]
            for row in rows:
                height=row['index'].top(feet[:,:2])
                if bool(np.all(np.isfinite(height)&(np.abs(height-feet[:,2])<=p['contact_tolerance_m']))):assigned.append(row['lane']['id'])
            matches.append({'entity':entity['id'],'base_vertices':len(feet),'matching_lanes':assigned,
                'passed':assigned==[target['lane']['id']]})
        results.append({'role':role,'required_lane':target['lane']['id'],'instances':matches,
            'passed':len(selected)==1 and all(r['passed'] for r in matches)})
    return float(all(r['passed'] for r in results)),{'placements':results,
        'lane_order_left_to_right':[r['lane']['id'] for r in ordered],
        'left_definition':'Left while looking from actual ball starts toward cups; independent of object names and world axes',
        'scope':'Geometric base on the specified lane; openings checked separately, no windmill/castle semantic classification',
        'threshold_status':'published_pilot_pending_calibration'}


def validate(check):
    validate_relations(check);p=check.params
    if check.metric=='l2_course_visitor_route':
        limits={'min_width':(.01,10),'cell_size':(.005,.1),'max_step':(0,.1),'max_slope':(0,2),
            'surface_epsilon':(1e-6,.01),'clearance_height':(.1,3),'seam_overlap_m':(0,.05)}
        for key,(low,high) in limits.items():
            if type(p[key]) not in (int,float) or not np.isfinite(p[key]) or not low<=p[key]<=high:
                raise ValueError('Invalid visitor access parameter: '+key)
        if p['cell_size']>p['min_width']/8:raise ValueError('Grid cannot resolve visitor width')
