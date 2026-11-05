"""Collect geometry, loadability and portable dependencies on retained variants."""
import os

import argparse

import fcntl

import os

from pathlib import Path

import subprocess

import sys

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from tools.experiment_identity import tested_model

from src.agent_judge.protocol import read_json as read

from src.evaluator.l1_edit_validity import combine, gate

from tools.evaluate_linear_candidate import atomic, pin

from tools.run_l1_strict_review import collect_native, BLENDER

from tools.run_new_tasks import verify_task, jobdir

from tools.watch_effort_historical import affected

from tools.effort_addition_files import file_contract

def dependencies(scene, folder):
    folder.mkdir(parents=True, exist_ok=True)
    worker = ROOT / 'src/evaluator/addition_dependencies_blender.py'
    request = {'scene': scene, 'output': str(folder / 'result.json')}
    if not (folder / 'result.json').exists():
        atomic(folder / 'request.json', request)
        with (folder / 'worker.log').open('w') as stream:
            process = subprocess.run([str(BLENDER), '-b', '--factory-startup', '--disable-autoexec',
                '--threads', '2', '--python-exit-code', '1', '--python', str(worker), '--',
                str(folder / 'request.json')], stdout=stream, stderr=subprocess.STDOUT, timeout=120,
                env={**os.environ, 'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2'})
        if process.returncode:
            raise ValueError('Dependency inspection failed: ' + str(folder / 'worker.log'))
    result = read(folder / 'result.json')
    if (read(folder / 'request.json') != request or result['scene'] != scene
            or result['worker_sha256'] != pin(worker)['sha256']
            or result['request_sha256'] != pin(folder / 'request.json')['sha256']):
        raise ValueError('Dependency audit binding changed')
    for row in result['unpacked_dependencies']:
        if row['sha256']:
            pin(row['resolved_path'], row['sha256'])
    return gate(combine(r['measurement_status'] for r in result['unpacked_dependencies'])
                if result['unpacked_dependencies'] else 'passed', evidence=pin(folder / 'result.json'))

def run(root, task_id):
    row = next(r for r in read(root / 'campaign.json')['records'] if r['task_id'] == task_id)
    verify_task(root, row)
    source = jobdir(root, tested_model(root), task_id)
    if affected(source):
        raise ValueError('Environment recovery required')
    manifest_path = source / 'legacy_execution/variants.json'
    manifest = read(manifest_path)
    if manifest['status'] != 'completed' or manifest['generation'] != pin(source / 'generation_state.json'):
        raise ValueError('Complete bound executions required')
    folder = source / 'legacy_delivery'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'case.lock').open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        results = {}
        files = file_contract(Path(row['task_root']), manifest, read(source / 'generation_state.json'))
        for seed in ('primary', 'seed-0', 'seed-1', 'seed-2'):
            artifacts = manifest['variants'][seed]
            for pointer in artifacts.values():
                pin(pointer['path'], pointer['sha256'])
            gates = {'dependencies': dependencies(artifacts['scene.blend'], folder / seed / 'dependencies')}
            for name in (('scene.blend', 'scene.glb') if row['level'] == 1 else ('scene.blend',)):
                dest = folder / seed / name
                native = collect_native(Path(artifacts[name]['path']), dest, 1,
                                        studio=False, main_required=False, geometry_only=True)
                gates[name + '_geometry'] = gate('passed' if native['has_real_geometry'] else 'failed',
                    evidence=pin(dest / 'native.json'), triangles=native['triangles'],
                    scope='Legacy nonplanar visible geometry gate; full task geometry remains a quality measurement')
            results[seed] = gates
            atomic(folder / 'status.json', {'status': 'running', 'finished_variants': list(results)})
        result = {'task_id': task_id, 'source_bindings': {'generation': manifest['generation'],
                    'variants': pin(manifest_path), 'collector': pin(ROOT / 'src/evaluator/l1_review_blender.py'),
                    'dependency_collector': pin(ROOT / 'src/evaluator/addition_dependencies_blender.py')},
                  'per_variant': results, 'file_contract': files, 'model_calls': 0,
                  'measurement_status': combine(g['measurement_status'] for groups in [*results.values(), *files.values()] for g in groups.values()),
                  'scope': 'Geometry/loadability and portable dependencies only; image consistency and other delivery checks separate'}
        atomic(folder / 'delivery.json', result)
        atomic(folder / 'status.json', {'status': result['measurement_status'], 'finished_variants': list(results)})
        return result
