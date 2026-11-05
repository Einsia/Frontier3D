"""Probe alternate target-perimeter poses only after a valid ground-ray miss."""
import math
from .geometry_routes import actor_vertices
from .protocol import CHESTS, CROPS, FURNACES, BLOCKS

def ground_hit(event, pawn_ground):
    if not event.get('accepted'):
        raise ValueError('Ground query not accepted by observer')
    if pawn_ground and event.get('collision_channel') != 'pawn':
        raise ValueError('Ground query channel not executed by observer')
    return bool(event.get('blocked') and event.get('normal', [0,0,0])[2] >= .7)

def perimeter_probes(export, bindings, unresolved):
    vertices=actor_vertices(export); steps=[]; options={}
    for target,field,name in unresolved:
        if field!='approach_cm' or target not in CHESTS+CROPS+FURNACES+BLOCKS:
            continue
        vs=vertices[target];lo,hi=vs.min(0),vs.max(0);center=(lo+hi)/2
        original=bindings['entities'][target][field]
        candidates=[]
        for axis in [0,1]:
            other=1-axis
            for side in [-1,1]:
                for gap in [55.,80.,110.]:
                    for fraction in [.25,.5,.75]:
                        p=list(center);p[axis]=float((lo[axis] if side<0 else hi[axis])+side*gap)
                        p[other]=float(lo[other]+fraction*(hi[other]-lo[other]));p[2]=original[2]
                        if math.dist(p[:2],center[:2]) <= 250:
                            candidates.append(p)
        candidates.sort(key=lambda p:(math.dist(p[:2],original[:2]),tuple(p)))
        options[name]=[]
        for i,p in enumerate(candidates):
            probe=name+'_fallback_'+str(i)
            options[name].append({'name':probe,'position_cm':p})
            steps.append({'op':'ray','collision_channel':'pawn','name':probe,
                          'from_cm':[p[0],p[1],p[2]+100],
                          'to_cm':[p[0],p[1],p[2]-300]})
    return steps,options

def choose_ground(options, events):
    # Order is fixed by geometry and distance, never by an interaction score.
    selected=None
    for option in options:
        event=events[option['name']]
        hit=ground_hit(event, True)
        if hit and selected is None:
            p=option['position_cm']
            point=event['point_cm']
            if math.dist(p[:2], point[:2]) > .1:
                raise ValueError('Ground hit outside probe ray')
            selected={'position_cm':[p[0],p[1],point[2]+88],
                      'probe':option['name'],'event':event}
    return selected
