"""Validate evaluator-owned design contracts, not candidate geometry or scores."""
from __future__ import annotations

import hashlib
import json
import math
import re

VERSION = 'l1-text-edit-measurement-contract-v1'


def digest_contract(contract):
    return hashlib.sha256(json.dumps(contract, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError('L1 measurement design: ' + reason)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def numeric_tree(value):
    return finite(value) or isinstance(value, list) and bool(value) and all(numeric_tree(v) for v in value)


def interval_verdict(lower, upper, tolerance):
    """Contract semantics for an already-proven absolute-error interval.

    This helper establishes no measurement bound itself and is not a metric.
    """
    require(all(finite(x) for x in (lower, upper, tolerance))
            and 0 <= lower <= upper and tolerance > 0, 'invalid absolute-error interval/tolerance')
    if upper <= tolerance:
        return 'passed'
    if lower > tolerance:
        return 'failed'
    return 'not_measurable'


def validate_contract(plan, spec):
    contract = plan.get('measurement_contract')
    require(isinstance(contract, dict) and contract.get('version') == VERSION, 'missing/unsupported contract')
    require(contract.get('task_id') == plan.get('task_id') and contract.get('sources') == plan.get('sources'),
            'contract source identity mismatch')
    require(contract.get('status') == 'implementation_contract_design_only'
            and contract.get('new_metrics_registered') is False and contract.get('full_task_verified') is False
            and contract.get('score_policy_changed') is False, 'design cannot claim new implementation or scoring')
    require(plan.get('measurement_contract_sha256') == digest_contract(contract), 'contract digest mismatch')
    definitions = contract.get('definition_sha256', {})
    require(set(definitions) == {'l1_measurement_contracts.py', 'l1_case_targets.py'} and
            all(isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v) for v in definitions.values()),
            'missing design definition hashes')
    roles = contract.get('roles')
    require(isinstance(roles, dict) and roles and all(isinstance(k, str) and k and type(v) is int and v > 0
                                                   for k, v in roles.items()), 'invalid roles')
    require(sum(roles.values()) == contract.get('expected_parts') == plan.get('expected_parts'), 'role count mismatch')
    methods = contract.get('methods')
    require(isinstance(methods, dict) and methods, 'missing methods')
    for method in methods.values():
        require(isinstance(method, dict) and set(method) == {'inputs', 'algorithm', 'outputs', 'unknown'},
                'invalid method interface')
        require(all(isinstance(method[key], str) and method[key] for key in ('algorithm', 'unknown')),
                'missing algorithm or unknown boundary')
        require(all(isinstance(method[key], list) and method[key]
                    and all(isinstance(item, str) and item for item in method[key])
                    for key in ('inputs', 'outputs')), 'missing method evidence fields')
    requirements = contract.get('requirement_contracts', [])
    declared = spec['l1_protocol']['requirements']
    require([r.get('id') for r in requirements] == [r['id'] for r in declared], 'requirement coverage/order mismatch')
    for row, source in zip(requirements, declared, strict=True):
        require(row.get('text') == source['text'] and row.get('source') == source['source']
                and row.get('required') is source.get('required', True)
                and row.get('applicable') is source.get('applicable', True), 'requirement source changed')
        require(row.get('current_check_ids') == source['check_ids']
                and row.get('current_implementation') == source['implementation']
                and row.get('current_limitation') == source.get('reason', ''), 'current implementation drift')
        require(row.get('design_status') == 'specified_not_newly_implemented' and row.get('acceptance'),
                'missing requirement acceptance boundary')
    rows = contract.get('evaluation_contracts', [])
    require([(r.get('id'), r.get('line')) for r in rows] == [(r['id'], r['line']) for r in plan['evaluation_rows']],
            'EVALUATION row coverage/order mismatch')
    used = set()
    for row in [*rows, *requirements]:
        names = row.get('methods')
        require(isinstance(names, list) and names and len(names) == len(set(names)) and set(names) <= set(methods),
                'invalid method reference')
        used.update(names)
    require(used == set(methods), 'orphan method definition')
    landmarks = contract.get('landmarks')
    require(isinstance(landmarks, list) and landmarks, 'missing landmarks')
    ids = [p.get('id') for p in landmarks]
    require(all(isinstance(k, str) and k for k in ids) and len(ids) == len(set(ids)), 'duplicate/invalid landmark id')
    edit = plan.get('category') == 'CodeEdit'
    for point in landmarks:
        require(point.get('unit') == 'mm' and numeric_tree(point.get('public_nominal')), 'invalid landmark units/value')
        require(point.get('quantity') in {'dimension', 'position'}, 'invalid quantity')
        reference = point.get('judgement_reference')
        require(reference in {'public_nominal', 'public_initial_actual_geometry'}, 'invalid reference authority')
        preserved = reference == 'public_initial_actual_geometry'
        require(point.get('comparison') == ('diagnostic_only_not_an_independent_preservation_gate' if preserved else
                                           'per_instance_spatial_error' if point['quantity'] == 'position' else
                                           'per_dimension_error'), 'wrong comparison semantics')
        require(point.get('tolerance_quantity') == ('protected_surface_distance' if preserved else 'feature_error'),
                'surface preservation cannot become a stricter diameter/position gate')
        require(not preserved or edit, 'text case cannot use initial-asset preservation')
        expected_tolerance = spec['tolerances']['preserve_m' if preserved else 'dimension_m'] * 1000
        require(finite(point.get('tolerance_mm')) and point['tolerance_mm'] == expected_tolerance,
                'landmark tolerance differs from declared target/preservation scope')
        require(point.get('datum') == plan['case_blueprint']['alignment'], 'landmark datum drift')
        authority = ('current_pilot_serialization_precision_not_public_dimension_tolerance'
                     if preserved and plan['task_id'].endswith('_015') else 'instruction_and_EVALUATION')
        require(point.get('tolerance_authority') == authority, 'tolerance authority mismatch')
    execution = contract.get('execution_contract', {})
    require(execution.get('runs') == ['baseline', *[f'seed_{s}' for s in spec['seeds']]]
            and execution.get('formats') == ['native', 'glb']
            and execution.get('native_frames') == plan['frames']['native_frames']
            and execution.get('glb_frames') == [1], 'run/format/frame scope mismatch')
    result = contract.get('result_contract', {})
    require(result.get('statuses') == ['passed', 'failed', 'not_measurable', 'infrastructure_error', 'not_applicable'],
            'missing explicit unavailable/failure states')
    require({'observed_interval', 'absolute_error_interval', 'unit', 'source_hashes', 'compute_receipt',
             'frame_occurrence', 'role_assignment'} <= set(result.get('fields', [])), 'missing result evidence')
    matrix = contract.get('acceptance_matrix', {})
    for name in ('positive', 'case_negative', 'boundary', 'source_controls'):
        require(isinstance(matrix.get(name), list) and len(matrix[name]) >= 2
                and all(isinstance(v, str) and v for v in matrix[name]), 'incomplete acceptance matrix')
    require(isinstance(contract.get('relationships'), list) and contract['relationships'], 'missing case relationships')
    require(contract.get('calibration_pending'), 'calibration limits cannot be hidden')
    if edit:
        region = contract.get('change_domain_contract', {})
        require(region.get('baseline') == spec['baseline_scene'] and region.get('baseline_is_authority') is True
                and region.get('candidate_may_expand_allowed_region') is False, 'invalid preservation authority')
        require(region.get('allowed') and region.get('protected') and region.get('proof') and region.get('datum_rule'),
                'missing case-specific change/protection domain')
        require(region.get('preserve_tolerance_mm') == spec['tolerances']['preserve_m'] * 1000,
                'preservation tolerance mismatch')
    else:
        require('change_domain_contract' not in contract, 'unexpected edit domain in text task')
    return contract
