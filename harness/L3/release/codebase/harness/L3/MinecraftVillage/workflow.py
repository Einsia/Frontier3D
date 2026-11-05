"""Compile a curator's on-foot route into the fixed semantic workflow.

Routes JSON has keys to_house, to_crop, to_furnace, to_storage, return_house. Each value
is an ordered list of {position_cm:[x,y,z], open_door:optional_required_id}.
Positions must be verified in the running scene; straight-line walk_to does
not perform pathfinding. This file is evaluator input, never model input.
"""
import argparse
from pathlib import Path
from .protocol import *


def compile_workflow(bindings, routes):
    validate_bindings(bindings);steps=[]
    def add(op, name=None, **kw):steps.append(dict(op=op,name=name or f's{len(steps):04}',**kw))
    def walk(point):add('walk_to',target_cm=vector(point),seconds=15)
    def aim(target):
        if target in DOORS+CHESTS:add('look_entity',target=target)
        else:add('look',target_cm=bindings['entities'][target]['look_cm'])
    def use(target,action):
        aim(target);add('interact',target=target,action=action);add('wait',seconds=1.2 if action=='use' else .5)
    def route(name):
        if name not in routes or not routes[name]:raise ValueError('Missing curated route: '+name)
        for point in routes[name]:
            walk(point['position_cm'])
            if point.get('open_door'):
                if point['open_door'] not in DOORS: raise ValueError('Unknown route door')
                use(point['open_door'],'use');add('wait',seconds=1)
    route('to_house');walk(bindings['entities']['house01.chest']['approach_cm'])
    use('house01.chest','use');use('house01.chest','take');add('capture','seed_acquired')
    route('to_crop');walk(bindings['entities']['farm.crop01']['approach_cm'])
    use('farm.crop01','harvest');use('farm.crop01','plant');add('capture','crop_replanted')
    route('to_furnace');walk(bindings['entities']['smithy01.furnace']['approach_cm'])
    aim('smithy01.furnace');add('interact',target='smithy01.furnace',action='process')
    add('wait',seconds=.3);add('capture','furnace_active');add('wait',seconds=3);add('capture','processed')
    route('to_storage');walk(bindings['entities']['storehouse.chest']['approach_cm'])
    use('storehouse.chest','use');use('storehouse.chest','take');add('capture','storage_visited')
    route('return_house');walk(bindings['entities']['house01.chest']['approach_cm'])
    use('house01.chest','take');add('capture','returned_storage')
    return validate_plan({'version':1,'kind':'e2e','curation_status':routes.get('curation_status','unverified'),'steps':steps})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bindings',type=Path,required=True);p.add_argument('--routes',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();write_json(a.output,compile_workflow(read_json(a.bindings),read_json(a.routes)))
