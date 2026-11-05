"""Replay confirmed candidate-content errors as zero for the affected checks only."""

from __future__ import annotations
import os

import argparse

import copy

from datetime import datetime, timezone

from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from orchestrator.tasks import write_json

from src.evaluator.l1_candidate_content import POLICY

from src.evaluator.l1_l2_alignment import aggregate, measure_data

from src.evaluator.l1_requirements import check_outcome

from src.evaluator.metrics import evaluate_metric

from src.evaluator.spec import EvalSpec

from tools.run_l1_strict_review import bind, read

def refresh_sweep_sections(check, evidence, root, bindings):
    """Remeasure just the unresolved native section using retained mesh bytes."""
    if (check.metric != 'swept_bar' or check.params.get('feature') != 'section_dimensions'
            or check.params.get('scene') != '/scene'
            or evidence.get('inspector_execution', {}).get('status') != 'completed'
            or evidence.get('measurement_failures', {}).get(check.id)):
        return evidence
    from src.evaluator.l1_surface import load_surface
    from src.evaluator.l1_sweep_measurements import PROTOCOL, measure_sections
    key = check.params['path'].removeprefix('/numeric_checks/')
    audit = evidence.get('numeric_checks', {}).get(key, {})
    if audit.get('protocol') != PROTOCOL or audit.get('design') != check.params['design']:
        return evidence
    source = audit.get('source', {})
    row = evidence.get('scene', {}).get('objects', {}).get(source.get('object'), {})
    payload = row.get('mesh_payload')
    reference = source.get('reference', {})
    if (not payload or payload != source.get('mesh_payload')
            or reference.get('sha256') != check.params['design']['reference_sha256']):
        return evidence
    bind(payload['path'], bindings, payload['sha256'])
    reference_path = bind(reference['path'], bindings, reference['sha256'])
    measured = measure_sections(load_surface(payload, root), read(reference_path), check.params['design'])
    updated = copy.deepcopy(evidence)
    updated['numeric_checks'][key]['features']['section_dimensions'] = measured
    return updated

def replay(original_path):
    original_path = Path(original_path).resolve()
    original = read(original_path)
    if original.get('S_core') is not None or original.get('missing_components') != ['data']:
        raise ValueError('Only an unresolved data component may use this recovery')
    if original.get('score_valid') is not True:
        raise ValueError('Unrelated system failures require separate handling')
    bindings = copy.deepcopy(original['source_bindings'])
    bind(original_path, bindings)
    for path, expected in list(bindings.items()):
        bind(path, {}, expected)
    root = Path(original['source_run_dir'])
    run = read(bind(root/'run.json', bindings))
    campaign = original_path.parents[4]
    job = campaign/'jobs'/Path(original['task_id']).name
    from tools.generation_selection import result_path
    generated = read(bind(result_path(job), bindings))
    selected = read(bind(job/'native-result.json', bindings))
    if (Path(selected['run_dir']).resolve() != root.resolve()
            or run['task_id'] != original['task_id']
            or run['source_sha256'] != generated['source_sha256']):
        raise ValueError('Baseline is not bound to the currently selected candidate')
    for name, expected in generated['source_sha256'].items():
        bind(Path(generated['submission'])/name, bindings, expected)
    scene = bind(root/'submission/scene.blend', bindings, original['artifact_sha256']['scene.blend'])
    evidence_path = bind(run['evidence_path'], bindings)
    evidence = read(evidence_path)
    artifact = evidence.get('artifacts', {}).get('scene.blend', {})
    if (artifact.get('sha256') != original['artifact_sha256']['scene.blend']
            or Path(artifact.get('hash_io', {}).get('path', '/missing')).resolve() != scene):
        raise ValueError('Inspection belongs to different candidate scene bytes')
    spec_path = bind(root/'configuration/eval_spec.json', bindings)
    spec = EvalSpec.load(spec_path)
    if spec.digest != original['spec_sha256']:
        raise ValueError('Candidate task specification changed')
    plan_path = bind(original_path.parents[3]/'plans'/original['task_id']/'alignment.json', bindings)
    plan = read(plan_path)
    checks = {check.id: check for group in spec.checks.values() for check in group}
    data = original['measurements']['data']
    rows = copy.deepcopy(data['measurements'])
    replaced = []
    for identity in data['missing_checks']:
        check = checks[identity]
        if check.metric not in {'hole_pattern', 'swept_bar'}:
            continue
        if rows[identity].get('params') != check.params:
            raise ValueError('Retained partial check belongs to another task contract')
        refreshed = refresh_sweep_sections(check, evidence, root, bindings)
        result = evaluate_metric(check, refreshed, spec)
        if result.status != 'ok' or result.score != 0 or result.details.get('policy') != POLICY:
            continue
        row = {**rows[identity], **result.to_dict()}
        row['measurement_status'] = check_outcome(row, refreshed)
        if row['measurement_status'] != 'failed':
            raise ValueError('Content zero must have an explicit measured failure')
        rows[identity] = row
        replaced.append(identity)
    if not replaced:
        raise ValueError('No confirmed candidate-content partial failure was found')
    revised = measure_data(plan, rows)
    if revised['status'] != 'measured':
        raise ValueError('Independent measurement gaps remain: '+str(revised['missing_checks']))
    measurements = {**copy.deepcopy(original['measurements']), 'data': revised}
    report = {**original, **aggregate(plan, original['gates'], measurements, original['vlm_judgment'],
        artifact_sha256=original['artifact_sha256']), 'source_bindings': bindings,
        'candidate_content_recovery': dict(policy=POLICY, previous_report=str(original_path),
            replaced_checks=replaced, new_model_calls=0, new_candidate_executions=0,
            rule='Confirmed candidate errors receive zero only for their affected checks; retain every other score')}
    return report

def recover_if_confirmed(original_path):
    """Automatic partial-zero recovery; uncertain evidence keeps its old gap."""
    original = read(original_path)
    if (original.get('S_core') is not None or original.get('missing_components') != ['data']
            or original.get('score_valid') is not True):
        return None
    data = original.get('measurements', {}).get('data', {})
    rows = data.get('measurements', {})
    if not any(rows.get(key, {}).get('metric') in {'hole_pattern', 'swept_bar'}
               for key in data.get('missing_checks', [])):
        return None
    try:
        return recover(original_path)
    except ValueError as error:
        if (str(error) == 'No confirmed candidate-content partial failure was found'
                or str(error).startswith('Independent measurement gaps remain:')):
            return None
        raise

def verify_recovery(report):
    recovery = report['candidate_content_recovery']
    if recovery.get('policy') != POLICY:
        raise ValueError('Unknown candidate-content scoring policy')
    expected = replay(recovery['previous_report'])
    # The timestamp records when the evidence replay was written, not a new
    # candidate execution or a fresh judge sample.
    expected['candidate_content_recovery']['updated_utc'] = recovery['updated_utc']
    if report != expected:
        raise ValueError('Partial-zero recovery changed unrelated evidence or arithmetic')

def recover(original_path):
    original_path = Path(original_path).resolve()
    output = original_path.with_name('candidate_partial_report.json')
    if output.exists():
        report = read(output)
        verify_recovery(report)
        return report
    report = replay(original_path)
    report['candidate_content_recovery']['updated_utc'] = datetime.now(timezone.utc).isoformat()
    verify_recovery(report)
    write_json(output, report)
    return report
