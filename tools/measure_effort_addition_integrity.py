"""Reuse the legacy saved-camera consistency gate on all new L1 deliveries.

This measures one validity gate only. Material and geometry checks remain
separate; texture permissions come from each new task's public contract.
"""
import os

import argparse

import fcntl

from pathlib import Path

import sys

from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from tools.experiment_identity import tested_model

from PIL import Image

from src.agent_judge.protocol import read_json as read

from src.evaluator.l1_image_pair import consistency

from src.evaluator.l1_edit_validity import combine, gate

from tools.evaluate_linear_candidate import atomic, pin

from tools.run_new_tasks import verify_task, jobdir

from tools.saved_scene_render import saved_render

from tools.watch_effort_historical import affected

def compare(artifacts, rendered, receipt, params):
    view = dict(rendered['view'])
    for name in ('image', 'mask'):
        pointer = view[name]
        pin(pointer['path'], pointer['sha256'])
        view[name], view[name + '_sha256'] = pointer['path'], pointer['sha256']
    view.update(source_sha256=artifacts['scene.blend']['sha256'], inspector_execution=receipt)
    evidence = {'views': {'primary': view}, 'artifacts': {
        'scene.blend': artifacts['scene.blend'],
        'main.png': {**artifacts['main.png'], 'validation_io': artifacts['main.png']}}}
    spec = SimpleNamespace(scene='scene.blend', render_views=[{'id': 'primary', 'frame': 1}])
    _, details = consistency(SimpleNamespace(params={**params, 'view': 'primary'}), evidence, spec)
    return gate('passed' if details['passed'] else 'failed', details=details)

def run(root, task_id):
    campaign = read(root / 'campaign.json')
    row = next(r for r in campaign['records'] if r['task_id'] == task_id)
    if row['level'] != 1:
        raise ValueError('L1 saved primary camera contract required')
    verify_task(root, row)
    source = jobdir(root, tested_model(root), task_id)
    if affected(source):
        raise ValueError('Environment recovery required')
    generation = read(source / 'generation_state.json')
    manifest_path = source / 'legacy_execution/variants.json'
    manifest = read(manifest_path)
    if generation['status'] != 'completed' or manifest['status'] != 'completed':
        raise ValueError('Complete accepted executions required')
    if manifest['generation'] != pin(source / 'generation_state.json'):
        raise ValueError('Generation changed')
    policy = ROOT / 'data/3dbench/tasks/L1/Image2Code-SingleView/task_L1_Image2Code-SingleView_001/harness/eval_spec.json'
    original = read(policy)
    check = next(c for checks in original['checks'].values() for c in checks if c['metric'] == 'main_render_consistency')
    params = check['params']
    folder = source / 'legacy_integrity'
    folder.mkdir(parents=True, exist_ok=True)
    bindings = {'generation': manifest['generation'], 'variants': pin(manifest_path), 'legacy_policy': pin(policy),
                'implementation': {n: pin(ROOT / n) for n in (
                    'src/evaluator/l1_image_pair.py', 'src/evaluator/l1_image_blender.py',
                    'src/evaluator/continuous_image_saved_blender.py', 'tools/measure_effort_addition_integrity.py')}}
    with (folder / 'case.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        results, receipts = {}, {}
        for seed in ('primary', 'seed-0', 'seed-1', 'seed-2'):
            artifacts = manifest['variants'][seed]
            for pointer in artifacts.values():
                pin(pointer['path'], pointer['sha256'])
            with Image.open(artifacts['main.png']['path']) as image:
                resolution = list(image.size)
            rendered, receipt = saved_render(artifacts['scene.blend'], folder / seed, 1, resolution)
            results[seed] = compare(artifacts, rendered, receipt, params)
            receipts[seed] = receipt
            atomic(folder / 'status.json', {'status': 'running', 'finished_variants': list(results)})
        status = combine(r['measurement_status'] for r in results.values())
        result = {'task_id': task_id, 'gate': 'main_render_consistency', 'measurement_status': status,
                  'per_variant': results, 'render_receipts': receipts, 'source_bindings': bindings,
                  'model_calls': 0, 'scope': 'Saved primary image consistency only; other validity gates remain separate'}
        atomic(folder / 'render_consistency.json', result)
        atomic(folder / 'status.json', {'status': status, 'finished_variants': list(results)})
        return result
