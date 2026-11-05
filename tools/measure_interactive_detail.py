"""Dedicated mechanism detail: hash-bound geometry over the complete public cycle.

Observed names locate semantic roles; all motion scores use actual evaluated
geometry, not names, Python source, reference pose fitting or judge estimates.
Undefined role layouts receive zero under the explicit candidate policy.
"""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from copy import deepcopy

import json

from pathlib import Path

import re

import numpy as np

from orchestrator.tasks import sha256, write_json

from src.evaluator.candidate_robustness import VERSION

from src.evaluator.continuous_hinge_kinematics import measure as kinematics

from src.evaluator.continuous_v2_tasks import measure as atom_score

from tools.native_scene import inspect

from tools.evaluate_linear_candidate import pin

FRAMES = list(range(1, 122, 10))+[1]

PROTOCOL = 'interactive-mechanism-detail-v1'

def normalized(name):
    return ' '+re.sub(r'[^a-z0-9\u4e00-\u9fff]+', ' ', name.lower())+' '

def has(name, words):
    return any(word in normalized(name) for word in words)

def locate_roles(snapshot):
    objects = [o for o in snapshot['objects'] if o.get('geometry')]
    names = [o['object'] for o in objects]
    if len(set(names)) != len(names): raise ValueError('Instance identities are ambiguous')
    centres = {o['object']: np.mean(o['bounds_m'], axis=0) for o in objects}
    door = [n for n in names if has(n, ('door', '门框', '门芯', '门板', '门扇'))
            and not has(n, ('hinge', 'strut', 'support', 'bracket', 'receiver', 'lug', 'eye',
                            'joint', 'socket', 'ball', '铰', '撑杆', '接头'))]
    cabinet = [n for n in names if has(n, ('cabinet', 'carcass', '柜体', '柜板', 'cavity'))
               and not has(n, ('hinge', 'strut', 'bracket', 'eye', 'joint', 'socket'))]
    hinges = [n for n in names if has(n, ('hinge', '铰链', '门轴'))
              and has(n, ('barrel', 'pin', 'axis', 'pivot', '轴', '筒'))]
    if len(hinges) != 2:
        hinges = [n for n in names if has(n, ('hinge', '铰链', '门轴'))
                  and not has(n, ('leaf', 'plate', 'screw', 'bolt', '叶', '螺'))]
    if not door or not cabinet or len(hinges) != 2:
        raise ValueError('Required door/cabinet/two hinge roles absent or undefined')
    barrels = [n for n in names if has(n, ('strut', 'support', 'gas', '撑杆', '气撑'))
               and has(n, ('barrel', 'cylinder', 'sleeve', 'tube', '筒', '外管'))
               and not has(n, ('bracket', 'eye', 'joint', 'socket', 'cap', 'lug'))]
    rods = [n for n in names if has(n, ('strut', 'support', 'gas', '撑杆', '气撑'))
            and has(n, ('rod', 'piston', 'shaft', '内杆', '活塞'))
            and not has(n, ('bracket', 'eye', 'joint', 'socket', 'cap', 'lug', 'sleeve'))]
    if len(barrels) != 2 or len(rods) != 2:
        raise ValueError('Two distinct barrel/rod assemblies absent or undefined')
    # Pair by observed closed-state position, without moving or fitting parts.
    barrels.sort(key=lambda n: (centres[n][0], n)); rods.sort(key=lambda n: (centres[n][0], n))
    struts = []
    for i, (barrel, rod) in enumerate(zip(barrels, rods)):
        struts.append(dict(id=('left', 'right')[i], barrel=[barrel], rod=[rod],
            barrel_main=barrel, rod_main=rod, cabinet_receivers=cabinet, cabinet_ball=False,
            door_receivers=door, door_ball=False))
    return dict(door=door, hinges=sorted(hinges), struts=struts)

def score_inspection(inspection, params):
    snapshots = inspection['snapshots']
    if [s['frame'] for s in snapshots] != FRAMES: raise ValueError('Incomplete mechanism frame population')
    roles = locate_roles(snapshots[0])
    names = set(roles['door']+roles['hinges'])
    for side in roles['struts']:
        for key in ('barrel', 'rod', 'cabinet_receivers', 'door_receivers'): names.update(side[key])
    states = []
    for snapshot in snapshots:
        by_name = {o['object']: o for o in snapshot['objects'] if o.get('geometry')}
        if names-set(by_name): raise ValueError('Required role geometry disappears during animation')
        state = {}
        for name in sorted(names):
            pointer = by_name[name]['geometry']; pin(pointer['path'], pointer['sha256'])
            with np.load(pointer['path'], allow_pickle=False) as data:
                vertices, faces = data['vertices_m'].copy(), data['triangles'].copy()
            if not np.isfinite(vertices).all(): raise ValueError('Nonfinite mechanism geometry')
            state[name] = (vertices, faces)
        states.append(state)
    raw = kinematics(states, FRAMES, roles,
        point_half_scale=params['point_error_half_scale_over_span'],
        rigid_half_scale=params['rigid_shape_half_scale_over_span'])
    for quantity in raw['quantities']:
        if quantity.get('status') == 'technical_failure':
            quantity.update(status='absent', reason='Undefined generated mechanism: '+str(quantity.get('reason')))
    raw['evidence'] = [{'scene': inspection['scene']}]
    value = atom_score({'method': 'normalized_error_kernel'}, raw)
    if value is None: raise ValueError('Undefined kinematic measurements')
    return value, roles, raw

def measure(scene, folder, params):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    path = folder/'mechanism.json'
    if path.exists():
        result = json.loads(path.read_text()); verify_result(result, scene, params); return pin(path)
    pin(scene['path'], scene['sha256'])
    # Native inspection runs in an isolated process and never executes source.
    # Worker/API/filesystem failures propagate as recoverable infrastructure.
    inspected = inspect(scene, folder/'inspection', FRAMES)
    write_json(folder/'inspection.json', inspected)
    try:
        value, roles, raw = score_inspection(inspected, params)
        reason = None
    except (ValueError, KeyError, IndexError, FloatingPointError, np.linalg.LinAlgError) as error:
        value, roles, raw, reason = 0., None, None, str(error)
    result = dict(protocol=PROTOCOL, policy=VERSION, scene=scene, params=params, frames=FRAMES,
        inspection=pin(folder/'inspection.json'), score=value, roles=roles, observations=raw,
        undefined_reason=reason, registration='none', model_calls=0, candidate_code_executed=False)
    write_json(path, result)
    return pin(path)

def verify_result(result, scene, params):
    if (result.get('protocol') != PROTOCOL or result['scene'] != scene or result['params'] != params
            or result['frames'] != FRAMES): raise ValueError('Mechanism measurement contract changed')
    pin(scene['path'], scene['sha256']); pointer = result['inspection']; pin(pointer['path'], pointer['sha256'])
    inspected = json.loads(Path(pointer['path']).read_text())
    if inspected['scene'] != scene or not inspected['source_unchanged']: raise ValueError('Mechanism scene binding changed')
    for snapshot in inspected['snapshots']:
        for obj in snapshot['objects']:
            geometry=obj.get('geometry')
            if geometry:pin(geometry['path'],geometry['sha256'])
    if result['observations'] is not None:
        expected = atom_score({'method': 'normalized_error_kernel'}, result['observations'])
        if expected != result['score']: raise ValueError('Kinematic arithmetic differs')
    elif result['score'] != 0 or not result.get('undefined_reason'):
        raise ValueError('Undefined mechanism must carry a zero and reason')
