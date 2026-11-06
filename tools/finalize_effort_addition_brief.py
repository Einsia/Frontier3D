'''Publish new Brief2Scene tasks with the legacy-detail v2 weights: VLM 60%, native numeric 30%, detail 10%.'''
import os

import fcntl

import math

from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from tools.experiment_identity import tested_model

from src.agent_judge.protocol import read_json as read

from src.evaluator.legacy_detail import ratio

from src.evaluator.legacy_detail_v2 import VERSION

from src.evaluator.l1_edit_validity import combine

from src.evaluator.addition_brief_numeric import numeric_data_score

from tools.evaluate_linear_candidate import atomic, pin

from tools.finalize_effort_addition import validate_detail, validate_baseline_artifact

from tools.finalize_effort_addition_l2 import validate_l2_detail_sources, validate_l2_gate, procedural_validity

from tools.effort_addition_files import file_contract

from tools.run_new_tasks import jobdir, verify_task

from tools.watch_effort_historical import affected

def finalize(root, task_id, row):
    verify_task(root, row)
    source = jobdir(root, tested_model(root), task_id)
    if affected(source):
        raise ValueError('Namespace recovery required')
    generation_path = source / 'generation_state.json'
    generation = read(generation_path)
    if generation['status'] != 'completed':
        raise ValueError('Accepted generation required')
    binding = pin(generation_path)
    manifest_path = source / 'legacy_execution/variants.json'
    manifest = read(manifest_path)
    manifest_pointer = pin(manifest_path)
    if manifest['status'] != 'completed' or manifest['generation'] != binding:
        raise ValueError('Complete bound executions required')
    config = resource('addition_config') / Path(task_id).name
    plan = read(config / 'plan.json')
    weights = {'vlm': .6, 'data': .3, 'detail': .1}
    if plan['task_id'] != task_id or plan['scoring_version'] != VERSION or plan['weights'] != weights:
        raise ValueError('Unified Brief2Scene contract required')
    for pointer in [plan['rules'], plan['acceptance'], plan['instruction'], *plan['references']]:
        pin(pointer['path'], pointer['sha256'])
    expected = {'generation': binding, 'variants': manifest_pointer,
                'plan': pin(config / 'plan.json'), 'spec': pin(config / 'detail_spec.json')}
    from tools.scene_scoring_evidence import scoring_manifest,addition_gates
    scoring=scoring_manifest(source)
    if scoring:expected['scoring_evidence']=pin(source/'scene_scoring_evidence/images.json')
    base_path, detail_path = ((source/'scene_scoring_baseline/components.json',source/'scene_scoring_detail/detail.json') if scoring
                             else (source/'legacy_baseline/components.json',source/'legacy_detail/detail.json'))
    baseline, detail = read(base_path), read(detail_path)
    if baseline['generation'] != binding or baseline['plan'] != expected['plan'] or detail['source_bindings'] != expected:
        raise ValueError('Candidate or scoring contract changed')
    detail_score = validate_detail(plan, read(config / 'detail_spec.json'), detail)
    validate_l2_detail_sources(plan, manifest, detail,scoring)
    pin(baseline['judge']['path'], baseline['judge']['sha256'])
    judge = read(Path(baseline['judge']['path']))
    if (judge.get('status') != 'scored' or judge.get('model') != judge_model()
            or judge.get('reasoning_effort') != 'medium' or judge.get('case_id') != task_id
            or judge.get('spec_sha256') != pin(config / 'vlm_spec.json')['sha256']):
        raise ValueError('Bound Astra medium baseline judgment required')
    for path, digest in judge.get('source_bindings', {}).items():
        pin(path, digest)
    for name in ('scene.blend', 'main.png', 'alternate.png'):
        pointer = baseline['images'][name]
        if pointer != (scoring or manifest)['variants']['primary'][name]:
            raise ValueError('Baseline belongs to another primary execution')
        validate_baseline_artifact(name, pointer, (scoring or manifest)['variants']['primary'], judge)
    numeric = read(source / 'legacy_numeric/report.json')
    if numeric['source_bindings'] != {'generation': binding, 'plan': expected['plan']}:
        raise ValueError('Numeric audit belongs to another candidate or contract')
    for name in ('response', 'measurement_manifest', 'catalogue'):
        pin(numeric[name]['path'], numeric[name]['sha256'])
    data = numeric_data_score(numeric, plan)
    if data['score'] is None:
        raise ValueError('Numeric measurement incomplete: ' + ', '.join(data['missing_checks']))
    components = {'vlm': judge.get('S_vlm'), 'data': data['score']}
    if baseline['components'] != {'vlm': components['vlm'], 'data': None}:
        raise ValueError('Baseline arithmetic changed')
    components['detail'] = detail_score
    for value in components.values():
        ratio(value)
    from tools.measure_effort_addition_delivery import run as delivery
    native = delivery(root, task_id)
    files = file_contract(Path(row['task_root']), manifest, generation)
    gates = {name: validate_l2_gate(source / directory / 'report.json', task_id, manifest_pointer)
             for name, directory in (('reproducible', 'legacy_reproducibility'), ('image_integrity', 'legacy_image_integrity'))}
    gates['procedural_materials'] = procedural_validity(source, plan)
    diagnostic_gates=dict(gates);gates=addition_gates(source,gates)
    validity = combine([native['measurement_status'], *gates.values(),
                        *(g['measurement_status'] for checks in files.values() for g in checks.values())])
    if validity not in {'passed', 'failed'}:
        raise ValueError('Unresolved L2 validity')
    valid = validity == 'passed'
    report = {'task_id': task_id, 'model': tested_model(root), 'source_run_dir': str(source),
        'scoring_version': VERSION, 'framework': 'legacy-composite-detail', 'task_adaptation': 'new-task-extension',
        'method_version': VERSION, 'judge_model': judge_model(), 'judge_effort': 'medium',
        'status': 'scored' if valid else 'system_invalid', 'score_valid': valid,
        'S_core': math.fsum(weights[k] * components[k] for k in weights) if valid else 0.,
        'components': {**components, **{k + '_weight': w for k, w in weights.items()},
                       **{k + '_contribution': w * components[k] if valid else 0. for k, w in weights.items()}},
        'numeric_audit': {k: data[k] for k in ('counts', 'checks', 'unresolved')},
        'file_contract': files, 'delivery_status': validity, 'validity_gates': gates, 'images': baseline['images'],
        'source_bindings': {**expected, 'baseline': pin(base_path), 'detail': pin(detail_path),
            'numeric': pin(source / 'legacy_numeric/report.json'),
            'delivery': pin(source / 'legacy_delivery/delivery.json'),
            **{name: pin(source / directory / 'report.json') for name, directory in (
                ('reproducibility', 'legacy_reproducibility'), ('image_integrity', 'legacy_image_integrity'))}},
        'new_candidate_generations': 0}
    report.update(scoring_policy_revision='content-partial-rerender-20261103-v1',quality_diagnostics={'original_validity_gates':diagnostic_gates})
    folder = root / 'main_results' / tested_model(root) / Path(task_id).name
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'case.lock').open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = folder / 'report.json'
        if target.exists() and read(target) != report:
            raise ValueError('Refusing to replace published Brief2Scene case')
        if not target.exists():
            atomic(target, report)
    return report
