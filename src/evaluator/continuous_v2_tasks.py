"""Complete native aggregation, including observed absence within numeric groups.

The v1 weights and continuous kernels are unchanged. Each absent required raw
quantity contributes zero to its fixed population; technical missingness stays
null. This module does not turn judge estimates into native observations.
"""
from .continuous_tasks import validate_plan, finite, measure as primitive_measure


def measure(atom, raw):
    if raw is None: return None
    if atom['method'] == 'normalized_error_kernel' and raw.get('status') == 'measured' and 'quantities' in raw:
        if not raw.get('evidence') or not raw['quantities']: raise ValueError('Bound nonempty quantity population required')
        values = []
        for quantity in raw['quantities']:
            status = quantity.get('status')
            if status == 'technical_failure': return None
            if status == 'absent':
                if not quantity.get('reason'): raise ValueError('Observed absence requires explanation')
                values.append(0.)
            elif status == 'measured':
                errors = quantity['normalized_errors']
                if not errors: raise ValueError('Observed quantity needs raw errors')
                values.append(sum(2**-finite(e) for e in errors)/len(errors))
            else: raise ValueError('Unknown quantity status')
        return sum(values)/len(values)
    return primitive_measure(atom, raw)


def aggregate(plan, native, visual, *, validity=None):
    validate_plan(plan)
    if validity is not None and type(validity) is not bool: raise ValueError('Boolean validity required')
    native_ids = {a['id'] for a in plan['measurements'] if a['method'] != 'visual_coverage_deviation'}
    visual_ids = {a['id'] for a in plan['measurements'] if a['method'] == 'visual_coverage_deviation'}
    if set(native)-native_ids or set(visual)-visual_ids: raise ValueError('Unknown scoring measurement')
    rows, missing = [], []
    for atom in plan['measurements']:
        value = visual.get(atom['id']) if atom['method'] == 'visual_coverage_deviation' else measure(atom, native.get(atom['id']))
        if value is None: missing.append(atom['id'])
        else: finite(value, ratio=True)
        weight = atom['weight']*plan['weights'][atom['component']]
        rows.append({'id':atom['id'], 'component':atom['component'], 'method':atom['method'], 'value':value,
            'weight':atom['weight'], 'global_weight':weight, 'contribution_points':None if value is None else 100*weight*value})
    components = {}
    for key in plan['weights']:
        selected = [r for r in rows if r['component'] == key]
        components[key] = None if any(r['value'] is None for r in selected) else sum(r['weight']*r['value'] for r in selected)
    if validity is None: missing.append('system_validity')
    total = 0. if validity is False else None if missing else sum(r['contribution_points'] for r in rows)
    return {'task_id':plan['task_id'], 'release_id':plan['release_id'], 'profile':plan['profile'],
        'status':'invalid_submission' if validity is False else 'not_measurable' if missing else 'scored',
        'score_100':total, 'S_core':None if total is None else total/100,
        'components':components, 'measurements':rows, 'missing_measurements':missing,
        'formal_score_eligible':False, 'aggregation_version':'continuous-native-v2'}
