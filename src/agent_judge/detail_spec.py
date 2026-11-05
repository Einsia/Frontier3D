"""Project the published rubric onto exactly the criteria consumed by detail.

The original definitions, weights and evidence requirements remain unchanged.
This does not select variants, alter aggregation, or infer missing judgments.
"""
from copy import deepcopy

from .task_continuous import PROTOCOL, validate_spec


def project_detail_spec(spec, criterion_ids):
    if spec.get('protocol') != PROTOCOL:
        raise ValueError('Detail projection requires the continuous task protocol')
    validate_spec(spec)
    ids = list(criterion_ids)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Distinct, nonempty detail criterion IDs required')
    available = {check['id'] for check in spec['checks']}
    if set(ids) - available:
        raise ValueError('Unknown detail criterion')
    projected = deepcopy(spec)
    projected['checks'] = [c for c in projected['checks'] if c['id'] in ids]
    # This also checks that every public reference is still required. Never
    # silently drop public evidence to make a smaller projection validate.
    validate_spec(projected)
    return projected
