"""Replay continuous, case-specific measurement plans without executing assets.

Native collectors supply evidence-bound raw quantities. Candidate/model supplied
scores and legacy pass/fail quality scores are never accepted as measurements.
"""
import math

VERSION = 'continuous-task-plan-v1'
PROFILES = {
    'image-no-comparable-gt-40-50-10-v1': {'H': .4, 'F': .5, 'M': .1},
    'text-continuous-80-20-v1': {'Q': .8, 'E': .2},
    'edit-continuous-40-40-20-v1': {'N': .4, 'T': .4, 'K': .2},
    'edit-continuous-80-20-v1': {'T': .8, 'K': .2},
}
METHODS = {'visual_coverage_deviation', 'normalized_error_kernel', 'soft_surface_fscore',
           'silhouette_iou', 'defect_fraction', 'preserved_fraction'}


def finite(value, *, ratio=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (ratio and value > 1):
        raise ValueError('Invalid finite nonnegative measurement')
    return value


def validate_plan(plan):
    if plan['version'] != VERSION or plan['weights'] != PROFILES[plan['profile']]:
        raise ValueError('Unknown version or changed component weights')
    weights = dict.fromkeys(plan['weights'], 0.)
    ids = set()
    for atom in plan['measurements']:
        if atom['id'] in ids or atom['component'] not in weights or atom['method'] not in METHODS:
            raise ValueError('Duplicate or unknown measurement')
        ids.add(atom['id'])
        if finite(atom['weight'], ratio=True) == 0:
            raise ValueError('Measurement weights must be positive')
        weights[atom['component']] += atom['weight']
        if not atom['question'].strip() or not atom['measurement_rule'].strip() or not atom['source']:
            raise ValueError('Every measurement needs a task requirement and measurement rule')
    if any(abs(v - 1) > 1e-9 for v in weights.values()):
        raise ValueError('Weights within each component must sum to one')
    if plan['physics_scoring'] is not False or plan['registration'] != 'fixed_format_conversion_only':
        raise ValueError('Unsupported physics or registration policy')
    return plan


def measure(atom, raw):
    """Raw quantities are produced by trusted collectors under the frozen plan."""
    if raw is None or raw.get('status') == 'technical_failure':
        return None
    if raw.get('status') == 'absent':
        if not raw.get('evidence'):
            raise ValueError('Observable absence needs evidence')
        return 0.
    if raw.get('status') != 'measured' or not raw.get('evidence'):
        raise ValueError('Raw measurement requires measured status and evidence')
    method = atom['method']
    if method == 'visual_coverage_deviation':
        raise ValueError('Visual results must come through the validated Agentic protocol')
    if method == 'normalized_error_kernel':
        errors = raw['normalized_errors']
        if not errors: raise ValueError('Empty measurement population')
        return sum(2 ** -finite(e) for e in errors) / len(errors)
    if method == 'soft_surface_fscore':
        candidate, reference = raw['candidate_normalized_distances'], raw['reference_normalized_distances']
        if not candidate or not reference: raise ValueError('Empty surface samples are not a perfect match')
        p = sum(2 ** -finite(e) for e in candidate) / len(candidate)
        r = sum(2 ** -finite(e) for e in reference) / len(reference)
        return 2 * p * r / (p + r) if p + r else 0.
    if method == 'silhouette_iou':
        pairs = raw['views']
        expected = atom['parameters']['view_ids']
        if len(pairs) != len(expected) or {v['id'] for v in pairs} != set(expected):
            raise ValueError('Frozen silhouette views differ')
        values = []
        for view in pairs:
            intersection, union = finite(view['intersection']), finite(view['union'])
            if union <= 0 or intersection > union: raise ValueError('Invalid foreground masks')
            values.append(intersection / union)
        return sum(values) / len(values)
    key = 'defect_fraction' if method == 'defect_fraction' else 'preserved_fraction'
    value = finite(raw[key], ratio=True)
    return 1 - value if method == 'defect_fraction' else value


def aggregate(plan, native_measurements, visual_scores, *, validity=None):
    """Pure replay API; the runner must verify artifact/spec hashes before calling."""
    validate_plan(plan)
    if validity is not None and type(validity) is not bool:
        raise ValueError('Validity must be bool or None')
    if set(native_measurements) - {r['id'] for r in plan['measurements'] if r['method'] != 'visual_coverage_deviation'}:
        raise ValueError('Unknown native measurement')
    if set(visual_scores) - {r['id'] for r in plan['measurements'] if r['method'] == 'visual_coverage_deviation'}:
        raise ValueError('Unknown visual measurement')
    rows, missing = [], []
    for atom in plan['measurements']:
        value = visual_scores.get(atom['id']) if atom['method'] == 'visual_coverage_deviation' else measure(atom, native_measurements.get(atom['id']))
        if value is None: missing.append(atom['id'])
        else: finite(value, ratio=True)
        rows.append({'id': atom['id'], 'component': atom['component'], 'value': value,
                     'weight': atom['weight'], 'contribution_points': None if value is None else
                     100 * plan['weights'][atom['component']] * atom['weight'] * value})
    components = {}
    for name in plan['weights']:
        selected = [r for r in rows if r['component'] == name]
        components[name] = None if any(r['value'] is None for r in selected) else sum(r['weight'] * r['value'] for r in selected)
    if validity is None: missing.append('system_validity')
    total = 0. if validity is False else None if missing else sum(r['contribution_points'] for r in rows)
    return {'task_id': plan['task_id'], 'release_id': plan['release_id'], 'profile': plan['profile'],
            'status': 'invalid_submission' if validity is False else 'not_measurable' if missing else 'scored',
            'score_100': total, 'S_core': None if total is None else total / 100,
            'components': components, 'measurements': rows, 'missing_measurements': missing,
            'formal_score_eligible': False}
