"""Reuse historical L2 distinct saved-camera image verification for new tasks."""
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

from orchestrator.l2_inspection import reproduce_flexible

from src.agent_judge.protocol import read_json as read

from tools.evaluate_linear_candidate import atomic, pin

from tools.measure_effort_l2_reproducibility import run as reproduce_seeds

from tools.run_new_tasks import jobdir, verify_task

def variant_artifacts(artifacts):
    names = ('scene.blend', 'main.png', 'alternate.png')
    pointers = {name: pin(artifacts[name]['path'], artifacts[name]['sha256']) for name in names}
    parents = {Path(pointer['path']).parent for pointer in pointers.values()}
    if len(parents) != 1 or any(Path(pointers[name]['path']).name != name for name in names):
        raise ValueError('Bound native scene and submitted PNGs must share their execution output')
    return parents.pop(), pointers

def run(root, task_id):
    campaign = read(root / 'campaign.json')
    row = next(row for row in campaign['records'] if row['task_id'] == task_id)
    if row['level'] != 2:
        raise ValueError('L2 authored-view contract required')
    verify_task(root, row)
    reproduce_seeds(root, task_id)
    source = jobdir(root, tested_model(root), task_id)
    manifest_path = source / 'legacy_execution/variants.json'
    manifest = read(manifest_path)
    folder = source / 'legacy_image_integrity'
    folder.mkdir(parents=True, exist_ok=True)
    implementation = {name: pin(ROOT / name) for name in (
        'tools/measure_effort_l2_image_integrity.py', 'orchestrator/l2_inspection.py',
        'harness/L2/audit.py', 'src/evaluator/l2_case_blender.py',
        'src/evaluator/l2_case_collector.py', 'src/evaluator/l2_case_compare.py')}
    with (folder / 'case.lock').open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        results = {}
        for seed in ('primary', 'seed-0', 'seed-1', 'seed-2'):
            output, artifacts = variant_artifacts(manifest['variants'][seed])
            facts_path = source / 'legacy_reproducibility' / seed / 'facts.json'
            bindings = {'artifacts': artifacts, 'facts': pin(facts_path), 'implementation': implementation}
            receipt = folder / seed / 'receipt.json'
            if receipt.exists():
                record = read(receipt)
                cached=record['source_bindings']
                actual_collectors={k:v for k,v in implementation.items()
                                   if k!='tools/measure_effort_l2_image_integrity.py'}
                if (cached.get('artifacts')!=artifacts or cached.get('facts')!=bindings['facts']
                        or any(cached.get('implementation',{}).get(k)!=v for k,v in actual_collectors.items())):
                    raise ValueError('Saved-camera evidence binding changed')
                for pointer in record['evidence_files']:
                    pin(pointer['path'], pointer['sha256'])
                result = record['result']
            else:
                target = folder / seed / 'renders'
                from tools.native_render_budget import budget
                seconds, _ = budget(artifacts['scene.blend']['sha256'], 1200, 8)
                result = reproduce_flexible(output, read(facts_path), target,
                    Path(campaign['blender']), runtime='local', image=None,
                    deadline=time.monotonic() + seconds + 30, timeout=seconds)
                for pointer in artifacts.values():
                    pin(pointer['path'], pointer['sha256'])
                atomic(receipt, {'source_bindings': bindings, 'result': result,
                    'evidence_files': [pin(p) for p in sorted(target.rglob('*')) if p.is_file()]})
            results[seed] = {'passed': result['passed'], 'status': result['status'], 'receipt': pin(receipt)}
            atomic(folder / 'status.json', {'status': 'running', 'finished_variants': list(results)})
        report = {'task_id': task_id, 'source_bindings': {'variants': pin(manifest_path),
            'reproducibility': pin(source / 'legacy_reproducibility/report.json'), 'implementation': implementation},
            'per_variant': results, 'measurement_status': 'passed' if all(r['passed'] for r in results.values()) else 'failed',
            'model_calls': 0, 'protocol': 'l2-camera-search-v2'}
        atomic(folder / 'report.json', report)
        return report
