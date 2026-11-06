"""Validate and publish complete L1 new-task extensions of legacy-detail v2."""
import os

import argparse

import fcntl

import math

from pathlib import Path

import re

import sys

import tomllib

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from tools.experiment_identity import tested_model

from PIL import Image

from src.agent_judge.protocol import read_json as read

from src.evaluator.legacy_detail import ratio, require_full_population

from src.evaluator.legacy_detail_v2 import VERSION

from src.evaluator.l1_edit_validity import combine, gate

from tools.evaluate_linear_candidate import atomic, pin, exported_scene, addition_exported_scene

from tools.run_l1_strict_review import collect_native

from tools.evaluate_new_task_legacy_v1 import measured_image

from tools.measure_effort_addition_detail import aggregate

from tools.measure_effort_addition_delivery import run as delivery

from tools.measure_effort_addition_integrity import run as integrity

from tools.run_new_tasks import jobdir, verify_task

from tools.watch_effort_historical import affected

from tools.effort_addition_files import file_contract

def validate_baseline_artifact(name, pointer, primary, judge):
    pin(pointer['path'], pointer['sha256'])
    if name in {'scene.blend', 'main.png'} and pointer != primary[name]:
        raise ValueError('Baseline image belongs to another candidate')
    # The visual judge receives PNGs; native scenes are bound by the execution manifest.
    if name.endswith('.png') and judge.get('source_bindings', {}).get(pointer['path']) != pointer['sha256']:
        raise ValueError('Baseline judge did not use the bound candidate evidence')

def validate_detail(plan, spec, detail):
    population = plan['detail_variants']
    require_full_population(detail, population)
    if set(detail['judge_runs']) != set(population):
        raise ValueError('Complete detail population required')
    scores = {}
    for variant, pointer in detail['judge_runs'].items():
        pin(pointer['path'], pointer['sha256'])
        judge = read(Path(pointer['path']))
        if (judge.get('status') != 'scored' or judge.get('model') != judge_model()
                or judge.get('case_id') != plan['task_id']
                or judge.get('reasoning_effort') != 'medium'
                or judge.get('spec_sha256') != detail['source_bindings']['spec']['sha256']):
            raise ValueError('Accepted bound Astra medium detail judgment required')
        for path, expected in judge.get('source_bindings', {}).items():
            pin(path, expected)
        scores[variant] = judge.get('criterion_scores', {})
    replay = aggregate(spec, scores, population)
    for key in ('status', 'score', 'selected_variant', 'values_by_variant', 'criterion_ids'):
        if detail.get(key) != replay.get(key):
            raise ValueError('Detail arithmetic or variant selection changed: ' + key)
    if replay['status'] != 'measured':
        raise ValueError('Detail measurement incomplete')
    return replay['score']

def validate_variant_sources(source, plan, manifest, detail):
    """Bind each scored scene to that seed's native or imported GLB artifact."""
    folder = source / ('scene_scoring_detail' if (source/'scene_scoring_evidence/images.json').exists() else 'legacy_detail')
    for variant in plan['detail_variants']:
        seed, fmt = variant.split('/')
        current = manifest['variants'][seed]
        native = collect_native(Path(current['scene.blend']['path']), folder / 'native' / seed,
                                1, studio=False, main_required=True)
        scene = addition_exported_scene(current, native, folder, seed) if fmt == 'glb' else current['scene.blend']
        judge = read(Path(detail['judge_runs'][variant]['path']))
        if judge.get('source_bindings', {}).get(scene['path']) != scene['sha256']:
            raise ValueError('Detail judgment belongs to another seed/export: ' + variant)

def finalize(root, task_id):
    campaign = read(root / 'campaign.json')
    row = next(r for r in campaign['records'] if r['task_id'] == task_id)
    if row['level'] == 2:
        from tools.finalize_effort_addition_l2 import finalize as finalize_l2
        return finalize_l2(root, task_id)
    verify_task(root, row)
    source = jobdir(root, tested_model(root), task_id)
    if affected(source):
        raise ValueError('Namespace recovery required before publication')
    generation_path = source / 'generation_state.json'
    generation = read(generation_path)
    if generation['status'] != 'completed':
        raise ValueError('Accepted generation required')
    manifest_path = source / 'legacy_execution/variants.json'
    manifest = read(manifest_path)
    binding = pin(generation_path)
    if manifest['status'] != 'completed' or manifest['generation'] != binding:
        raise ValueError('Complete bound executions required')
    config = resource('addition_config') / Path(task_id).name
    plan = read(config / 'plan.json')
    if plan['task_id'] != task_id or plan['scoring_version'] != VERSION:
        raise ValueError('Unified task contract required')
    for pointer in [plan['rules'], plan['acceptance'], plan['instruction'], *plan['references']]:
        pin(pointer['path'], pointer['sha256'])
    from tools.scene_scoring_evidence import scoring_manifest
    scoring=scoring_manifest(source)
    base_path, detail_path = ((source/'scene_scoring_baseline/components.json',source/'scene_scoring_detail/detail.json') if scoring
                             else (source/'legacy_baseline/components.json',source/'legacy_detail/detail.json'))
    baseline, detail = read(base_path), read(detail_path)
    if baseline['generation'] != binding or baseline['plan'] != pin(config / 'plan.json'):
        raise ValueError('Baseline candidate or plan changed')
    expected = {'generation': binding, 'variants': pin(manifest_path),
                'plan': pin(config / 'plan.json'), 'spec': pin(config / 'detail_spec.json')}
    if scoring:expected['scoring_evidence']=pin(source/'scene_scoring_evidence/images.json')
    if detail['source_bindings'] != expected:
        raise ValueError('Detail candidate or contract changed')
    detail_score = validate_detail(plan, read(config / 'detail_spec.json'), detail)
    validate_variant_sources(source, plan, manifest, detail)
    pin(baseline['judge']['path'], baseline['judge']['sha256'])
    judge = read(Path(baseline['judge']['path']))
    if (judge.get('status') != 'scored' or judge.get('model') != judge_model()
            or judge.get('case_id') != task_id
            or judge.get('reasoning_effort') != 'medium'
            or judge.get('spec_sha256') != pin(config / 'vlm_spec.json')['sha256']):
        raise ValueError('Accepted bound Astra medium baseline judgment required')
    for path, expected_hash in judge.get('source_bindings', {}).items():
        pin(path, expected_hash)
    for name, pointer in baseline['images'].items():
        validate_baseline_artifact(name, pointer, (scoring or manifest)['variants']['primary'], judge)
    image = measured_image(row, read(Path(plan['rules']['path'])), plan['references'], baseline['images'])
    components = {'main_image': image['score'], 'localization': judge.get('localization', {}).get('score'),
                  'vlm': judge.get('S_vlm')}
    if components != baseline['components']:
        raise ValueError('Baseline component arithmetic changed')
    components['detail'] = detail_score
    weights = {'main_image': .5, 'localization': .2, 'vlm': .2, 'detail': .1}
    if plan['weights'] != weights:
        raise ValueError('Legacy image weights changed')
    for value in components.values():
        ratio(value)
    files = file_contract(Path(row['task_root']), manifest, generation)
    native, render = delivery(root, task_id), integrity(root, task_id)
    render_status='passed' if scoring else render['measurement_status']
    validity = combine([native['measurement_status'], render_status,
                        *(g['measurement_status'] for checks in files.values() for g in checks.values())])
    if validity not in {'passed', 'failed'}:
        raise ValueError('Delivery validity unresolved')
    valid = validity == 'passed'
    total = math.fsum(weights[k] * components[k] for k in weights) if valid else 0.
    report = {'task_id': task_id, 'model': tested_model(root), 'source_run_dir': str(source),
        'scoring_version': VERSION, 'framework': 'legacy-composite-detail', 'task_adaptation': 'new-task-extension',
        'method_version': VERSION, 'judge_model': judge_model(), 'judge_effort': 'medium',
        'status': 'scored' if valid else 'system_invalid', 'score_valid': valid, 'S_core': total,
        'components': {**components, **{k + '_weight': w for k, w in weights.items()},
                       **{k + '_contribution': w * components[k] if valid else 0. for k, w in weights.items()}},
        'file_contract': files, 'delivery_status': validity, 'images': baseline['images'],
        'source_bindings': {**expected, 'baseline': pin(base_path), 'detail': pin(detail_path),
            'delivery': pin(source / 'legacy_delivery/delivery.json'),
            'integrity': pin(source / 'legacy_integrity/render_consistency.json')},
        'new_candidate_generations': 0}
    if scoring:report.update(scoring_policy_revision='content-partial-rerender-20261103-v1',
        quality_diagnostics={'saved_image_consistency':render['measurement_status']})
    folder = root / 'main_results' / tested_model(root) / Path(task_id).name
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'case.lock').open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = folder / 'report.json'
        if target.exists() and read(target) != report:
            raise ValueError('Refusing to replace a published case')
        if not target.exists():
            atomic(target, report)
    return report
