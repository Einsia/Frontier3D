"""Freeze door probe height from independent ground rays, never from action outcomes."""
import copy
import math
from .protocol import DOORS, validate_plan, vector


def crossing_binding(bindings, target):
    b=bindings['entities'][target]
    for key in ['crossing_from_cm','crossing_to_cm']:vector(b[key])
    return b


def ground_plan(bindings):
    steps=[]
    for target in DOORS:
        try:b=crossing_binding(bindings,target)
        except (KeyError,TypeError,ValueError):continue
        for side,key in [('front','crossing_from_cm'),('back','crossing_to_cm')]:
            x,y,z=b[key]
            steps.append({'op':'ray','name':target.replace('.','_')+'_'+side,
                          'from_cm':[x,y,z+100],'to_cm':[x,y,z-300]})
    if not steps:steps=[{'op':'wait','name':'no_valid_crossing_coordinates','seconds':.1}]
    return validate_plan({'version':1,'kind':'views','steps':steps})


def apply_ground_observations(bindings, observations):
    calibrated=copy.deepcopy(bindings);evidence={}
    for target in DOORS:
        try:b=crossing_binding(bindings,target)
        except (KeyError,TypeError,ValueError) as error:
            evidence[target]={'status':'submission_contract_failure','error':str(error),'probe_center_z_cm':None}
            continue
        rows=[]
        for side,key in [('front','crossing_from_cm'),('back','crossing_to_cm')]:
            event=observations.get(target.replace('.','_')+'_'+side,{})
            point=event.get('point_cm',[]);normal=event.get('normal',[])
            valid=(event.get('accepted') is True and event.get('blocked') is True and
                   len(point)==3 and len(normal)==3 and all(isinstance(v,(int,float)) and math.isfinite(v) for v in point+normal) and
                   normal[2]>=.7 and abs(point[2]-(b[key][2]-85))<=100 and event.get('hit')!=target)
            rows.append({'side':side,'valid':bool(valid),'observation':event})
        if all(r['valid'] for r in rows):
            height=max(r['observation']['point_cm'][2] for r in rows)+85+3
            for key in ['crossing_from_cm','crossing_to_cm']:calibrated['entities'][target][key][2]=height
        else:height=None
        evidence[target]={'status':'ground_height_calibrated' if height is not None else 'unresolved_ground',
                          'probe_center_z_cm':height,'capsule_half_height_cm':85,'floor_clearance_cm':3,'rays':rows,
                          'closed_probe_must_still_hit_target':True}
    return calibrated,evidence
