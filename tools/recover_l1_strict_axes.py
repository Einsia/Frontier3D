"""Apply user-approved fixed GLB format conversion to archived L1 measurements.

No candidate execution, model call, arbitrary alignment or native-score copying.
Every baseline/seed gets its own full-geometry proof and GLB numeric measurement.
"""

from __future__ import annotations
import os

import argparse

import copy

from pathlib import Path

import sys

import tempfile

import time

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from orchestrator.tasks import sha256, write_json

from src.evaluator.l1_compute import run_compute

from src.evaluator.l1_format_axes import PROTOCOL, ROW_MATRIX, converted_numeric_scene, delivery_mesh, prove_conversion

from src.evaluator.l1_l2_alignment import aggregate, measure_data

from src.evaluator.l1_requirements import check_outcome

from src.evaluator.l1_surface import load_surface

from src.evaluator.metrics import evaluate_metric

from src.evaluator.spec import EvalSpec

from tools.run_l1_strict_review import read, bind, now, flatten

USER_DECISION = '允许有证据的固定格式坐标转换，不允许任意配准'

ALLOWED_TASKS = {'L1/Text2Code/task_L1_Text2Code_013', 'L1/Text2Code/task_L1_Text2Code_014'}

def verified_baseline_path(original_path):
    """Select a separately verified recovery without replacing archived facts.

    A successful original baseline always wins. This accessor never starts a
    recovery or new measurement: an absent recovery leaves the original gap
    visible, and an invalid one fails rather than silently substituting scores.
    """
    original_path = Path(original_path)
    original = read(original_path)
    robust_path = original_path.with_name('robustness_report.json')
    if original.get('S_core') is None and robust_path.is_file():
        if robust_path.is_symlink(): raise ValueError('Robustness recovery must be a regular report')
        from tools.recover_undefined_candidate import verify_recovery as verify_robustness
        robust = read(robust_path)
        if robust.get('robustness_recovery', {}).get('previous_report') != str(original_path.resolve()):
            raise ValueError('Robustness recovery belongs to another candidate')
        verify_robustness(robust)
        return robust_path
    partial_path = original_path.with_name('candidate_partial_report.json')
    if original.get('S_core') is None and partial_path.is_file():
        if partial_path.is_symlink():
            raise ValueError('Candidate partial recovery must be a regular local report')
        from tools.recover_candidate_content_partial import verify_recovery as verify_partial
        partial = read(partial_path)
        if partial.get('candidate_content_recovery', {}).get('previous_report') != str(original_path.resolve()):
            raise ValueError('Candidate partial recovery belongs to another baseline')
        verify_partial(partial)
        return partial_path
    recovered_path = original_path.with_name('recovery_report.json')
    if (original.get('S_core') is not None or original.get('task_id') not in ALLOWED_TASKS
            or not recovered_path.is_file()):
        return original_path
    if recovered_path.is_symlink():
        raise ValueError('Recovered baseline must be a regular local report')
    recovered = read(recovered_path)
    if (original.get('missing_components') != ['data']
            or recovered.get('task_id') != original['task_id']
            or recovered.get('model') != original.get('model')
            or recovered.get('S_core') is None
            or recovered.get('format_axis_recovery', {}).get('previous_report') != str(original_path.resolve())):
        raise ValueError('Recovered baseline does not belong to the isolated original data gap')
    verify_recovery(recovered)
    return recovered_path

def phase_sources(run, evidence):
    if run.get('seeds') != [0, 1, 2]:
        raise ValueError('Baseline and every frozen seed 0/1/2 required')
    seeds = evidence['harness']['seed_quality']['per_seed']
    if set(seeds) != {'0', '1', '2'}:
        raise ValueError('Incomplete seed evidence')
    return [('baseline', run['evidence_path'], run['report_path'], None)] + [
        ('seed-'+str(s), seeds[str(s)]['evidence']['path'], seeds[str(s)]['report']['path'], seeds[str(s)])
        for s in run['seeds']]

def selected_checks(spec):
    checks = [c for group in spec.checks.values() for c in group if c.applicable
              and c.params.get('scene') == '/artifacts/scene.glb/scene'
              and c.metric in {'machined_sleeve', 'swept_bar'}]
    if not checks or len({(c.metric, c.params['path']) for c in checks}) != 1:
        raise ValueError('One declared GLB numeric job required')
    return checks

def replacement_checks(spec, old_report, checks, scene, measurement):
    results = flatten(old_report)
    evidence = {'artifacts': {'scene.glb': {'scene': scene}},
                'numeric_checks': {checks[0].params['path'].rsplit('/', 1)[-1]: measurement}}
    for check in checks:
        row = {**copy.deepcopy(results[check.id]), **evaluate_metric(check, evidence, spec).to_dict()}
        row['measurement_status'] = check_outcome(row, evidence)
        if row['measurement_status'] not in {'passed', 'failed'}:
            raise ValueError('Fixed conversion leaves an unresolved numeric check: '+check.id)
        results[check.id] = row
    return results

def recover(file):
    file = file.resolve(); original = read(file); dest = file.parent
    if (dest/'recovery_report.json').exists():
        result = read(dest/'recovery_report.json')
        verify_recovery(result)
        return result
    if (original['task_id'] not in ALLOWED_TASKS or original.get('S_core') is not None
            or original.get('missing_components') != ['data']):
        raise ValueError('Only the isolated, explicitly reviewed Text013/014 data gaps are eligible')
    if any(g.get('measurement_status') != 'passed' for g in original['gates'].values()):
        raise ValueError('Unrelated system gaps must not be waived')
    bindings = copy.deepcopy(original['source_bindings']); bind(file, bindings)
    for p, digest in list(bindings.items()):
        bind(p, {}, digest)
    root = Path(original['source_run_dir']); run = read(bind(root/'run.json', bindings))
    spec = EvalSpec.load(bind(root/'configuration/eval_spec.json', bindings))
    if spec.digest != original['spec_sha256']:
        raise ValueError('Original task specification changed')
    plan = read(bind(file.parents[3]/'plans'/original['task_id']/'alignment.json', bindings))
    checks = selected_checks(spec)
    base = read(bind(run['evidence_path'], bindings))
    sources = phase_sources(run, base)
    output = Path(tempfile.mkdtemp(prefix='format-axes-', dir=dest))
    decision = {'protocol': PROTOCOL, 'decision_utc': now(), 'user_instruction': USER_DECISION,
                'fixed_row_vector_matrix': [list(r) for r in ROW_MATRIX],
                'scope': 'Numeric mesh measurements only; original exports and all unrelated verdicts retained',
                'forbidden': ['arbitrary_rotation', 'translation', 'scaling', 'ICP', 'reference_fitting', 'native_score_substitution'],
                'required_phases': [s[0] for s in sources]}
    write_json(output/'decision.json', decision)
    observations = []
    for phase, ep, rp, seed in sources:
        print(original['model'], original['task_id'], phase, flush=True)
        evidence = read(bind(ep, bindings, seed['evidence']['sha256'] if seed else None))
        old_report = read(bind(rp, bindings, seed['report']['sha256'] if seed else None))
        for name in ('scene.blend', 'scene.glb'):
            artifact = evidence['artifacts'][name]
            bind(artifact['hash_io']['path'], bindings, artifact['sha256'])
            if old_report['artifact_sha256'][name] != artifact['sha256']:
                raise ValueError('Mesh evidence belongs to another artifact')
        for scene in (evidence['scene'], evidence['artifacts']['scene.glb']['scene']):
            _, row = delivery_mesh(scene)
            bind(row['mesh_payload']['path'], bindings, row['mesh_payload']['sha256'])
        folder = output/phase
        converted, proof = converted_numeric_scene(evidence['scene'], evidence['artifacts']['scene.glb']['scene'],
            trusted_root=root, output=folder/'converted_glb.npz')
        write_json(folder/'numeric_scene.json', converted)
        params = checks[0].params
        payload = {'scene': converted, 'design': params['design'], 'trusted_root': str(folder)}
        if checks[0].metric == 'swept_bar':
            source = evidence['numeric_checks'][params['path'].rsplit('/', 1)[-1]]['source']['reference']
            reference = bind(source['path'], bindings, params['design']['reference_sha256'])
            assets = reference
            for _ in Path(params['design']['reference_path']).parts:
                assets = assets.parent
            payload['assets_root'] = str(assets)
        measured = run_compute(checks[0].metric, payload, output=folder/'compute', deadline=time.monotonic()+240)
        values = replacement_checks(spec, old_report, checks, converted, measured)
        data = measure_data(plan, values)
        if data['status'] != 'measured':
            raise ValueError('Other data gaps remain after format conversion')
        write_json(folder/'measurement.json', measured)
        write_json(folder/'data.json', data)
        observation = {'phase': phase, 'source_evidence': str(ep), 'source_report': str(rp),
                       'numeric_scene': str(folder/'numeric_scene.json'), 'measurement': str(folder/'measurement.json'),
                       'data': str(folder/'data.json'), 'proof': proof,
                       'remeasured_check_ids': [c.id for c in checks]}
        observations.append(observation)
    write_json(output/'observations.json', observations)
    measurements = copy.deepcopy(original['measurements'])
    measurements['data'] = read(observations[0]['data'])
    result = {**original, **aggregate(plan, original['gates'], measurements, original['vlm_judgment'],
              artifact_sha256=original['artifact_sha256']), 'finished_utc': now(), 'source_bindings': bindings,
              'format_axis_recovery': {'protocol': PROTOCOL, 'previous_report': str(file),
                  'decision': str(output/'decision.json'), 'observations': str(output/'observations.json'),
                  'new_model_calls': 0, 'new_candidate_executions': 0}}
    for p in output.rglob('*'):
        if p.is_file(): bind(p, bindings)
    for p, digest in list(bindings.items()): bind(p, {}, digest)
    # Independent mathematical replay precedes publication; no success by flags alone.
    verify_recovery(result)
    write_json(dest/'recovery_report.json', result)
    return result

def verify_recovery(report):
    recovery = report['format_axis_recovery']
    for p, digest in report['source_bindings'].items(): bind(p, {}, digest)

    def bound(path, expected=None, decode=True):
        path = Path(path).resolve(strict=True)
        digest = report['source_bindings'].get(str(path))
        if not digest or (expected and digest != expected):
            raise ValueError('Recovery uses an unbound or substituted source: '+str(path))
        bind(path, {}, digest)
        return read(path) if decode else path

    if recovery['protocol'] != PROTOCOL or recovery['new_model_calls'] or recovery['new_candidate_executions']:
        raise ValueError('Invalid format recovery provenance')
    old = bound(recovery['previous_report']); decision = bound(recovery['decision'])
    if report['task_id'] not in ALLOWED_TASKS or old.get('missing_components') != ['data'] or old.get('S_core') is not None:
        raise ValueError('Not an eligible isolated coordinate measurement gap')
    if decision['user_instruction'] != USER_DECISION or decision['fixed_row_vector_matrix'] != [list(r) for r in ROW_MATRIX]:
        raise ValueError('Format conversion is not the approved fixed rule')
    for key in ('model', 'task_id', 'source_run_dir', 'gates', 'vlm_judgment',
                'artifact_sha256', 'spec_sha256', 'plan_sha256'):
        if report[key] != old[key]: raise ValueError('Unrelated review facts changed: '+key)
    for key in set(old['measurements'])-{'data'}:
        if report['measurements'][key] != old['measurements'][key]:
            raise ValueError('Unrelated quality measurement changed: '+key)
    root = Path(report['source_run_dir']); run = bound(root/'run.json')
    spec = EvalSpec.from_dict(bound(root/'configuration/eval_spec.json')); checks = selected_checks(spec)
    if spec.digest != report['spec_sha256']: raise ValueError('Recovery specification changed')
    sources = phase_sources(run, bound(run['evidence_path']))
    observations = bound(recovery['observations'])
    if [o['phase'] for o in observations] != [s[0] for s in sources]:
        raise ValueError('Baseline/seed proof coverage differs')
    if decision['required_phases'] != [s[0] for s in sources]: raise ValueError('Approved phase coverage changed')
    plan = bound(Path(recovery['previous_report']).parents[3]/'plans'/report['task_id']/'alignment.json')
    from src.evaluator.l1_compute_worker import dispatch
    for observation, (phase, ep, rp, seed) in zip(observations, sources, strict=True):
        if (observation['source_evidence'], observation['source_report']) != (str(ep), str(rp)):
            raise ValueError('Recovery sources do not belong to the frozen phase')
        evidence = bound(ep, seed['evidence']['sha256'] if seed else None)
        old_report = bound(rp, seed['report']['sha256'] if seed else None)
        for name in ('scene.blend', 'scene.glb'):
            artifact = evidence['artifacts'][name]
            bound(artifact['hash_io']['path'], artifact['sha256'], decode=False)
            if old_report['artifact_sha256'][name] != artifact['sha256']:
                raise ValueError('Recovery phase artifact mismatch')
        proof = observation['proof']; imported_scene = evidence['artifacts']['scene.glb']['scene']
        _, nr = delivery_mesh(evidence['scene']); name, gr = delivery_mesh(imported_scene)
        if proof['native_mesh'] != nr['mesh_payload'] or proof['imported_mesh'] != gr['mesh_payload']:
            raise ValueError('Mesh proof source substitution')
        for key in ('native_mesh', 'imported_mesh', 'converted_mesh'):
            bound(proof[key]['path'], proof[key]['sha256'], decode=False)
        native = load_surface(nr['mesh_payload'], root); imported = load_surface(gr['mesh_payload'], root)
        transformed, expected = prove_conversion(native, imported)
        if any(proof.get(k) != v for k, v in expected.items()): raise ValueError('Geometry proof differs')
        import numpy as np
        converted = load_surface(proof['converted_mesh'], Path(observation['numeric_scene']).parent)
        if not np.array_equal(converted.vertices, transformed) or not np.array_equal(converted.triangles, imported.triangles):
            raise ValueError('Converted geometry is not the fixed transform of the original GLB')
        scene = bound(observation['numeric_scene']); _, record = delivery_mesh(scene)
        if record['mesh_payload'] != proof['converted_mesh']:
            raise ValueError('Numeric scene geometry binding mismatch')
        for key in ('type', 'entity_scope', 'valid_solid', 'closed', 'components', 'editable'):
            if record[key] != gr[key]: raise ValueError('Unrelated GLB validity fact changed')
        measured = bound(observation['measurement']); receipt = measured['compute_execution']
        work = Path(receipt['record_path']).parent
        bound(receipt['record_path'])
        request = bound(work/'request.json', receipt['request_sha256'])
        response = bound(work/'result.json', receipt['result_sha256'])
        if request['operation'] != checks[0].metric or response['operation'] != checks[0].metric:
            raise ValueError('Incorrect numeric operation')
        payload = {'scene': scene, 'design': checks[0].params['design'],
                   'trusted_root': str(Path(observation['numeric_scene']).parent)}
        if checks[0].metric == 'swept_bar':
            params = checks[0].params
            source = evidence['numeric_checks'][params['path'].rsplit('/', 1)[-1]]['source']['reference']
            reference = bound(source['path'], params['design']['reference_sha256'], decode=False)
            assets = reference
            for _ in Path(params['design']['reference_path']).parts: assets = assets.parent
            payload['assets_root'] = str(assets)
        if request['payload'] != payload:
            raise ValueError('Numeric job scene/design mismatch')
        replay = dispatch(checks[0].metric, request['payload'])
        if replay != response['result'] or replay != {k: v for k, v in measured.items() if k != 'compute_execution'}:
            raise ValueError('Full GLB numerical replay differs')
        values = replacement_checks(spec, old_report, checks, scene, measured)
        data = measure_data(plan, values)
        if bound(observation['data']) != data or observation['remeasured_check_ids'] != [c.id for c in checks]:
            raise ValueError('Data measurements differ from complete remeasurement')
        if phase == 'baseline' and data != report['measurements']['data']:
            raise ValueError('Published data component differs')
    return {'protocol': PROTOCOL, 'verified_phases': len(observations), 'numerical_replay': True}
