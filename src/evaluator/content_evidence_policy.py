"""User-approved partial credit and scene-authoritative rendering policy."""
import copy
import math

VERSION = 'content-partial-rerender-20261103-v1'


def seed_system_status(seed):
    from .l1_edit_validity import combine
    gates = [*seed.get('prerequisites', {}).values(), *[
        v for k, v in seed.get('system_checks', {}).items() if k != 'reproducible']]
    if not gates:
        return 'not_measurable'
    return combine(g.get('measurement_status', 'passed' if g.get('passed') is True else 'failed'
                       if g.get('passed') is False else 'not_measurable') for g in gates)


def codeedit_partial(report):
    """Keep existing min-over-formats/seeds quality; remove equality as a veto."""
    from .l1_edit_validity import combine, gate
    result = copy.deepcopy(report)
    gates = result['gates']
    repro = gates['reproducible']
    rows = repro.get('details', {}).get('per_seed', {})
    if not rows or not all(r.get('execution_passed') is True for r in rows.values()):
        raise ValueError('All seed executions must be independently established')
    seeds = gates['all_seeds']['details']['per_seed']
    if set(rows) != set(seeds):
        raise ValueError('Seed evidence populations differ')
    result['quality_diagnostics'] = {**result.get('quality_diagnostics', {}),
        'reproduction_equality': repro, 'old_all_seeds': gates['all_seeds'],
        'policy': VERSION, 'meaning':'Geometry differences reduce measured native/GLB content scores; equality does not veto all credit'}
    gates['reproducible'] = gate('passed', policy=VERSION, scope='Seed execution only; geometry equality is diagnostic')
    gates['all_seeds'] = gate(combine(seed_system_status(s) for s in seeds.values()),
                              policy=VERSION, scope='Execution, loadability, dependencies and material legality retained')
    valid = all(g.get('passed') is True for g in gates.values())
    components = result.get('score_components', result['components'])
    weights = {'numeric':.4, 'target':.4, 'preservation':.2}
    for k, w in weights.items():
        v = components[k]
        if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1:
            raise ValueError('Missing measured component: '+k)
        components[k+'_contribution'] = w*v if valid else 0.
    result.update(S_core=math.fsum(w*components[k] for k,w in weights.items()) if valid else 0.,
        score_valid=valid, case_pass=valid, G=int(valid), status='scored' if valid else 'system_invalid',
        score_components=components, components=components,
        system_failures=[k for k,g in gates.items() if g.get('passed') is False],
        scoring_policy_revision=VERSION)
    result['S_level'] = result['S_core']
    result['S_diagnostic'] = result['S_core']
    return result


def rerender_available(replay):
    """Image equality is diagnostic; successful bound rendering is evidence."""
    views = replay.get('views', {})
    return (replay.get('status') == 'measured' and bool(views)
            and all(v.get('render_path') for v in views.values()))


def l2_audit_valid(row):
    """Do not suppress scores for seed signatures or saved-PNG inequality."""
    return (row.get('execution_passed') is True
            and row.get('audit', {}).get('passed') is True
            and (row.get('rerender', {}).get('passed') is True or rerender_available(row.get('rerender', {})))
            and not row.get('error'))
