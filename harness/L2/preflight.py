"""Public deliverable checks; no hidden task score or quality thresholds."""
import time
import json

from .audit import artifact_state, scene_audit


def check_annotations(objects, policy):
    """Validate public entity/part grouping without hidden shape thresholds."""
    groups = {}
    for name, obj in objects.items():
        if obj.get('type') == 'MESH' and obj.get('visible_render') and obj.get('faces', 0) > 0:
            groups.setdefault((obj.get('role'), obj.get('entity', name)), set()).add(obj.get('part'))
    errors = []
    missing = set(policy.roles)-{role for role, _ in groups}
    if missing:
        errors.append({'missing_geometric_roles': sorted(missing)})
    for (role, entity), parts in groups.items():
        required = set(policy.entity_parts.get(role, ()))
        if required-parts:
            errors.append({'entity': entity, 'role': role, 'missing_parts': sorted(required-parts),
                'repair': 'Tag one parent Empty for each complete entity; parent its mesh parts to it and tag each mesh with bench_part.'})
    return errors


def check_outputs(workspace, blender, policy, directory, timeout, *, cancel_event=None):
    from .rerun import inspect
    started = time.monotonic()
    def remaining():
        if cancel_event is not None and cancel_event.is_set():
            return 0
        return max(0, timeout-(time.monotonic()-started))
    artifacts, errors = artifact_state(workspace, policy.output_files, policy.views)
    result = {'passed': False, 'errors': errors, 'artifacts': artifacts}
    if errors:
        return result
    try:
        facts = inspect(blender, workspace, directory/'scene', '/work/scene.blend', policy, remaining(), cancel_event=cancel_event)
        for view in policy.views:
            if view['camera'] not in facts['scene']['cameras']:
                errors.append('Missing output camera: '+view['camera'])
        baseline = None
        if policy.baseline_scene:
            baseline = inspect(blender, workspace, directory/'baseline', '/work/'+policy.baseline_scene,
                               policy, remaining(), cancel_event=cancel_event)
        audit = scene_audit(facts, baseline, edit=bool(policy.baseline_scene))
        if not audit['passed']:
            errors.append({'scene_integrity': audit['failures']})
        errors.extend(check_annotations(facts['scene']['objects'], policy))
        evidence = {**facts, 'artifacts': artifacts, 'baseline': baseline['scene'] if baseline else {}}
        checks = public_checks(evidence, policy)
        result['public_checks'] = checks
        errors.extend({'public_constraint': c} for c in checks if not c['passed'])
        from src.evaluator.l2_diagnostics import write_diagnostics
        route = next((c for checks in policy.spec.checks.values() for c in checks
            if c.metric == 'l2_route'), None) if policy.spec else None
        diagnostics = write_diagnostics(evidence, directory, entity_parts=policy.entity_parts,
                                       route_check=route, spec=policy.spec)
        result['diagnostics'] = {'route': diagnostics.get('route'), 'files': [p.name for p in directory.glob('*') if p.name in
            {'scene_diagnostics.json', 'scene_diagnostics.png', 'road_diagnostics.png', 'road_grid.npz'}],
            'semantic_status': 'pending_human',
            'cameras': diagnostics['cameras'],
            'support_warnings': [{k: e[k] for k in ('entity', 'role', 'min_gap_m', 'max_gap_m', 'contact_fraction')}
                for e in diagnostics['support']['entities'] if e['floating_suspect'] or e['penetration_suspect']]}

    except (OSError, ValueError, RuntimeError) as error:
        errors.append(str(error))
    result['passed'] = not errors
    result['timed_out'] = remaining() <= 0 or any(json.loads(p.read_text()).get('status') in {'timeout', 'budget_exhausted'}
                             for p in directory.glob('*-logs/process.json'))
    if result['timed_out']:
        result['passed'] = False
        errors.append('Public preflight deadline exhausted')
    return result


def public_checks(evidence, policy):
    from src.evaluator.metrics import evaluate_metric
    if not policy.requirements or policy.spec is None:
        return []
    results = []
    for checks in policy.spec.checks.values():
        for check in checks:
            if policy.requirements['checks'][check.id]['public']:
                result = evaluate_metric(check, evidence, policy.spec)
                results.append({'id': check.id, 'passed': result.passed, 'status': result.status,
                    'expected': check.params, 'measured': result.details})
    return results
