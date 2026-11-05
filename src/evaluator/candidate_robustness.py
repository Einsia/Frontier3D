"""User-authorized zero for undefined candidate measurements, preserving credit."""
from copy import deepcopy
import math

VERSION = 'candidate-robustness-v1'
UNKNOWN = {'missing', 'invalid', 'not_measurable', 'not_implemented', None}


def score(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def zero_check(row, reason):
    result = deepcopy(row)
    previous = deepcopy(row)
    result.update(score=0., passed=False, status='ok', measurement_status='failed')
    result['details'] = {**result.get('details', {}), 'robustness': {
        'policy': VERSION, 'classification': 'undefined_candidate_content',
        'reason': reason, 'previous_measurement': previous}}
    return result


def resolve_checks(rows):
    """Only explicit inspection/compute infrastructure errors stay unresolved."""
    updated, zeroed = deepcopy(rows), []
    for key, row in updated.items():
        failure = row.get('details', {}).get('measurement_failure', {})
        state = row.get('measurement_status', row.get('status'))
        if state == 'infrastructure_error' or failure.get('status') == 'infrastructure_error':
            continue
        if state in UNKNOWN or not score(row.get('score')):
            updated[key] = zero_check(row, 'Undefined, unsupported or nonconforming candidate measurement')
            zeroed.append(key)
    return updated, zeroed


def weighted_components(values, weights):
    if not math.isclose(math.fsum(weights.values()), 1., abs_tol=1e-10):
        raise ValueError('Component weights must sum to one')
    if any(not score(values.get(key)) for key in weights):
        raise ValueError('Every weighted component needs a finite score')
    return math.fsum(weights[key]*values[key] for key in weights)
