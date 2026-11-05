"""Apply historical L2 seed scene signatures to retained new-task executions."""
import os

import argparse

import fcntl

from pathlib import Path

import sys

import time

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from tools.experiment_identity import tested_model

from orchestrator.l2_inspection import inspect_scene

from src.agent_judge.protocol import read_json as read

from src.evaluator.l2_case_compare import align_evaluated_roundoff

from src.evaluator.l2_mesh_order import reproduction_fields

from tools.evaluate_linear_candidate import atomic, pin

from tools.run_new_tasks import jobdir, verify_task

def signature(scene):
    objects = {name: {key: obj.get(key) for key in (
        'type', 'parent', 'visible_render', 'location', 'rotation', 'scale',
        'geometry_sha256', 'evaluated_geometry_sha256', 'material_sha256',
        'data_sha256', 'constraints_sha256')} for name, obj in scene['objects'].items()}
    for name, obj in scene['objects'].items():
        objects[name].update(reproduction_fields(obj))
    return {'objects': objects, **{key: scene.get(key) for key in (
        'world_sha256', 'render_settings_sha256', 'saved_frame', 'unit_scale', 'cameras', 'audit')}}

def run(root, task_id):
    campaign = read(root / 'campaign.json')
    row = next(row for row in campaign['records'] if row['task_id'] == task_id)
    if row['level'] != 2:
        raise ValueError('L2 scene contract required')
    verify_task(root, row)
    source = jobdir(root, tested_model(root), task_id)
    manifest_path = source / 'legacy_execution/variants.json'
    manifest = read(manifest_path)
    if manifest['status'] != 'completed' or manifest['generation'] != pin(source / 'generation_state.json'):
        raise ValueError('Complete bound executions required')
    bindings = {'variants': pin(manifest_path), 'implementation': {name: pin(ROOT / name) for name in (
        'tools/measure_effort_l2_reproducibility.py', 'orchestrator/l2_inspection.py',
        'src/evaluator/l2_case_blender.py',
        'src/evaluator/l2_case_collector.py', 'src/evaluator/l2_case_compare.py',
        'src/evaluator/l2_mesh_order.py')}}
    folder = source / 'legacy_reproducibility'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'case.lock').open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        observations = {}
        for seed in ('primary', 'seed-0', 'seed-1', 'seed-2'):
            scene = manifest['variants'][seed]['scene.blend']
            pin(scene['path'], scene['sha256'])
            receipt = folder / seed / 'receipt.json'
            expected = {'scene': scene, 'implementation': bindings['implementation']}
            if receipt.exists():
                saved = read(receipt)
                cached = saved['source_bindings']
                # Native facts depend on the collector, not this reporting wrapper.
                # Always recompute signatures below using the current implementation.
                collectors = {name: pointer for name, pointer in expected['implementation'].items()
                              if name not in {'tools/measure_effort_l2_reproducibility.py','orchestrator/l2_runner.py'}}
                if (cached['scene'] != scene or any(cached['implementation'].get(name) != pointer
                                                   for name, pointer in collectors.items())):
                    raise ValueError('Native inspection binding changed')
                pin(saved['facts']['path'], saved['facts']['sha256'])
                for pointer in saved['inspection_files']:
                    pin(pointer['path'], pointer['sha256'])
                facts = read(Path(saved['facts']['path']))
            else:
                facts = inspect_scene(Path(scene['path']), folder / seed / 'inspection',
                    Path(campaign['blender']), runtime='local', image=None,
                    deadline=time.monotonic() + 930, timeout=900)
                atomic(folder / seed / 'facts.json', facts)
                atomic(receipt, {'source_bindings': expected, 'facts': pin(folder / seed / 'facts.json'),
                    'inspection_files': [pin(p) for p in sorted((folder / seed / 'inspection/output').rglob('*')) if p.is_file()]})
            observations[seed] = facts
            atomic(folder / 'status.json', {'status': 'running', 'inspected': list(observations)})
        primary = observations['primary']
        expected_signature = signature(primary['scene'])
        results = {}
        for seed, facts in observations.items():
            comparable, roundoff = align_evaluated_roundoff(facts['scene'], primary['scene'],
                directory=facts.get('geometry_root'), reference_directory=primary.get('geometry_root'))
            results[seed] = {'passed': signature(comparable) == expected_signature,
                'roundoff': roundoff, 'receipt': pin(folder / seed / 'receipt.json')}
        result = {'task_id': task_id, 'source_bindings': bindings, 'per_variant': results,
            'measurement_status': 'passed' if all(r['passed'] for r in results.values()) else 'failed',
            'model_calls': 0, 'scope': 'Historical L2 native seed signatures; authored-image integrity remains separate'}
        atomic(folder / 'report.json', result)
        return result
