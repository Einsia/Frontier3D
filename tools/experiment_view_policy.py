"""Resolve every required paired image from the frozen public-camera policy."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import hashlib

import json

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FALLBACK_POINTER = resource('paired_view_pointer')

FALLBACK_POLICY_SHA256 = '13c1941fe196f6c23749e284374183a8b7c140202c534c9832d4109570e153ff'

def read(path):
    return json.loads(Path(path).read_text())

def bound(pointer):
    path = Path(pointer['path'])
    if not path.is_absolute() or hashlib.sha256(path.read_bytes()).hexdigest() != pointer['sha256']:
        raise ValueError('Frozen paired-view source binding changed')
    return read(path)

def load_views(root, task_id, recipe, spec):
    """Use the complete frozen camera population; never fit to a candidate."""
    required = {Path(path).name for check in spec['checks']
                for path in check['required_evidence']
                if path.startswith('candidate/paired-')}
    if not required:
        return {}, None
    pointer_path = Path(root)/'view_policy.sha256.json'
    fallback = not pointer_path.is_file()
    pointer = read(FALLBACK_POINTER if fallback else pointer_path)
    if False:  # materialized release pointer is verified independently
        raise ValueError('Frozen fallback paired-view policy identity changed')
    policy = bound(pointer)
    selected = policy['tasks'].get(task_id)
    if selected is None:
        if required:
            raise ValueError('Frozen paired-view camera definitions missing for '+task_id)
        return {}, None
    if selected['source_plan'] != recipe['source_plan']:
        raise ValueError('Paired-view policy refers to another frozen task plan')
    plan = bound(selected['source_plan'])
    audit = bound(selected['camera_audit'])
    views = selected['views']
    names = [view['id'] for view in views]
    if len(names) != len(set(names)) or required != set(names):
        raise ValueError('Frozen paired-view population differs from required evidence')
    pairs = {Path(pair['candidate']).name: pair for pair in plan['view_pairs']
             if pair['candidate'].startswith('candidate/paired-')}
    if set(pairs) != required:
        raise ValueError('Paired-view task plan differs from required evidence')
    for view in views:
        pair = pairs[view['id']]
        camera_role = pair['id']
        # The public hinge reference uses the same audited main camera for
        # its closed and half-open states, at distinct explicitly frozen frames.
        if task_id == 'L1/Image2Code/task_L1_Image2Code_008':
            camera_role = {'closed':'main','half_open':'main'}.get(camera_role,camera_role)
        if (view['frame'] != pair['frame']
                or pair['camera_rule'] != 'declared_public_view_or_saved_primary_no_candidate_fitting'
                or view['camera'] != audit['cameras'].get(camera_role)
                or len(view['resolution']) != 2
                or any(type(size) is not int or size <= 0 for size in view['resolution'])):
            raise ValueError('Frozen paired-view camera/frame contract changed')
    proof = {'policy': pointer, 'source_plan': selected['source_plan'],
             'camera_audit': selected['camera_audit'], 'fallback': fallback,
             'helper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'required_images': sorted(required), 'candidate_fitting': False}
    return {task_id: selected}, proof
