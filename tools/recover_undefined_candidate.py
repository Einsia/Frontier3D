"""Replay archived L1 content gaps under the explicit robustness policy."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import copy

from pathlib import Path

from orchestrator.tasks import write_json

from src.evaluator.candidate_robustness import VERSION, resolve_checks, score, weighted_components

from src.evaluator.l1_l2_alignment import measure_data

from src.evaluator.spec import EvalSpec

from tools.run_l1_strict_review import ROOT, bind, read

POLICY = ROOT/'configs/evaluation/candidate-robustness-v1.json'

def enabled():
    return POLICY.is_file() and read(POLICY).get('enabled') is True

def replay(path):
    path = Path(path).resolve(); original = read(path)
    if not enabled() or original.get('S_core') is not None:
        raise ValueError('Robustness recovery needs an enabled policy and unresolved baseline')
    bindings = copy.deepcopy(original.get('source_bindings', {})); bind(path, bindings)
    for p, expected in list(bindings.items()): bind(p, {}, expected)
    root = Path(original['source_run_dir'])
    run = read(bind(root/'run.json', bindings))
    campaign = path.parents[4]; job = campaign/'jobs'/Path(original['task_id']).name
    from tools.generation_selection import result_path
    generated = read(bind(result_path(job), bindings))
    selected = read(bind(job/'native-result.json', bindings))
    if (Path(selected['run_dir']).resolve() != root.resolve()
            or run['task_id'] != original['task_id']
            or run['source_sha256'] != generated['source_sha256']):
        raise ValueError('Robustness report does not bind the selected candidate')
    for name, expected in generated['source_sha256'].items():
        bind(Path(generated['submission'])/name, bindings, expected)
    if original.get('artifact_sha256', {}).get('scene.blend'):
        bind(root/'submission/scene.blend', bindings, original['artifact_sha256']['scene.blend'])
    if original.get('errors') or original.get('budget_exhausted') or original.get('scoring_failed'):
        raise ValueError('Infrastructure or scoring exception requires recovery, not content zero')
    gates = original.get('gates', {})
    if any(g.get('measurement_status') == 'infrastructure_error' for g in gates.values()):
        raise ValueError('Infrastructure gate cannot become candidate zero')
    components = copy.deepcopy(original['score_components']); measurements = copy.deepcopy(original['measurements'])
    zeroed = []
    if isinstance(measurements, dict):
        data = measurements.get('data', {})
        if 'data' in (original.get('missing_components') or []):
            plan = read(bind(path.parents[3]/'plans'/original['task_id']/'alignment.json', bindings))
            rows, changed = resolve_checks(data['measurements'])
            revised = measure_data(plan, rows)
            if revised['status'] != 'measured': raise ValueError('Independent infrastructure gaps remain')
            measurements['data'] = revised; components['data'] = revised['score']; zeroed.extend(changed)
        if 'physics' in (original.get('missing_components') or []):
            physics = measurements['physics']
            # This is a bounded candidate-complexity failure, not an API or
            # missing-reference exception. Preserve all other quality scores.
            if 'exceeds one million complete triangles' not in str(physics.get('reason', '')):
                raise ValueError('Unknown physics failure needs infrastructure diagnosis')
            measurements['physics'] = {**physics, 'score': 0., 'status': 'measured',
                'robustness': {'policy': VERSION, 'previous_status': physics['status'],
                               'classification': 'candidate_geometry_exceeds_measurement_capacity'}}
            components['physics'] = 0.; zeroed.append('physics')
    else:
        from src.evaluator.l1_edit_quality import components as edit_components
        spec = EvalSpec.load(bind(root/'configuration/eval_spec.json', bindings))
        if spec.digest != original['spec_sha256']: raise ValueError('CodeEdit task specification changed')
        policy = spec.to_dict()['l1_edit_quality']
        rows, changed = resolve_checks({r['id']: r for r in measurements})
        base = edit_components(policy, rows)
        seeds = next(r for r in rows.values() if r.get('metric') == 'all_seed_checks').get('details', {}).get('per_seed', {})
        for key, current in list(components.items()):
            if key not in {'numeric', 'target', 'preservation'} or score(current): continue
            values = [base.get(key)] + [r.get('edit_components', {}).get(key) for r in seeds.values()]
            # Unknown seed subcomponents have the same explicit zero policy.
            components[key] = min(v if score(v) else 0. for v in values)
        measurements = list(rows.values()); zeroed.extend(changed)
    weights = {key[:-7]: value for key, value in components.items() if key.endswith('_weight') and value > 0}
    if 'similarity' in weights: weights['target'] = weights.pop('similarity')
    if any(not score(components.get(key)) for key in weights):
        raise ValueError('API/judge or unrelated weighted measurement remains unresolved')
    if not zeroed: raise ValueError('No undefined candidate measurement found')
    # Real failed system gates retain their original zero. Unknown geometry
    # gates are recorded as policy-waived, without claiming a passed inspection.
    failed = any(g.get('measurement_status') == 'failed' for g in gates.values())
    waived = {k: copy.deepcopy(v) for k,v in gates.items()
              if v.get('measurement_status') in {'not_measurable', 'not_implemented'}}
    total = 0. if failed else weighted_components(components, weights)
    for key, weight in weights.items(): components[key+'_contribution'] = 0. if failed else weight*components[key]
    result = {**original, 'S_core': total, 'S_level': total, 'score_components': components,
        'measurements': measurements, 'score_valid': not failed, 'measurement_complete': True,
        'status': 'system_invalid' if failed else 'scored', 'missing_components': [],
        'source_bindings': bindings, 'system_validity': 'failed' if failed else
            'content_uncertainty_resolved_by_policy' if waived else 'passed',
        'robustness_recovery': {'policy': VERSION, 'previous_report': str(path),
            'policy_sha256': __import__('orchestrator.tasks', fromlist=['sha256']).sha256(POLICY),
            'zeroed_checks': zeroed, 'waived_unknown_gates': waived,
            'new_model_calls': 0, 'new_candidate_executions': 0,
            'scope': 'Undefined candidate checks zero; finite measured partial scores retained'}}
    return result

def verify_recovery(report):
    if report != replay(report['robustness_recovery']['previous_report']):
        raise ValueError('Robustness recovery arithmetic or provenance changed')

def recover(path):
    path = Path(path); target = path.with_name('robustness_report.json')
    if target.exists():
        report = read(target); verify_recovery(report); return report
    report = replay(path); write_json(target, report); return report
