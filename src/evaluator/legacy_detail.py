"""Versioned replacement of one legacy quality term with bound continuous detail.

All other legacy measurements, weights, candidate identities and validity gates
remain unchanged. A missing detail measurement blocks a valid candidate's score.
"""
from __future__ import annotations

from copy import deepcopy
import math

VERSION = 'legacy-detail-replacement-v1'
COMPONENT = 'detail'


def require_full_population(detail, population):
    """Reject screening and incomplete cached evidence before formal reuse."""
    for field in ('required_variants', 'measured_variants'):
        if field in detail and detail[field] != population:
            raise ValueError('Complete frozen detail population required: ' + field)
    judgments = set(detail.get('judge_runs', {}))
    failures = set(detail.get('preparation_failures', {}))
    if (detail.get('status') == 'screening' or judgments & failures
            or judgments | failures != set(population)):
        raise ValueError('Complete frozen detail population required')


def ratio(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Expected a finite score in [0, 1]')
    return value


def legacy_weights(report):
    components = report['score_components']
    if not components and report.get('score_valid') is False and report.get('S_core') == 0:
        if report.get('method_version') == 'l1-brief-l2aligned-v1.0.0':
            return {'vlm': .6, 'data': .3, 'physics': .1}
    weights = {}
    for field, value in components.items():
        if not field.endswith('_weight'):
            continue
        ratio(value)
        if value == 0:
            continue
        key = field[:-7]
        if key == 'similarity':
            key = 'target'
        elif key == 'target' and 'similarity_weight' in components:
            # Old SceneEdit stores numeric + target in target_weight.
            continue
        weights[key] = value
    if not weights or not math.isclose(math.fsum(weights.values()), 1, abs_tol=1e-10):
        raise ValueError('Legacy quality weights must sum to one')
    for key in weights:
        if components.get(key) is not None:
            ratio(components[key])
    return weights


def detail_from_component(record, plan):
    """Reuse exactly the audited F component, including its minimum variant."""
    if record['task_id'] != plan['task_id'] or 'F' not in plan['weights']:
        raise ValueError('An F detail component for this task is required')
    expected = {a['id']: a for a in plan['measurements'] if a['component'] == 'F'}
    atoms = [deepcopy(a) for a in record['measurements'] if a['component'] == 'F']
    if len(atoms) != len(expected) or {a['id'] for a in atoms} != set(expected):
        raise ValueError('Detail population differs from the frozen task plan')
    value = record['components']['F']
    if value is not None:
        ratio(value)
        if any(a['value'] is None for a in atoms):
            raise ValueError('A complete F component contains missing atoms')
        replay = math.fsum(expected[a['id']]['weight'] * ratio(a['value']) for a in atoms)
        if not math.isclose(replay, value, abs_tol=1e-10):
            raise ValueError('F detail arithmetic differs')
        variants = record['component_values_by_variant']['F']
        if set(variants) != set(record['expected_variants']) or any(v is None for v in variants.values()):
            raise ValueError('F detail requires every retained variant')
        selected = record['component_variants']['F']
        if not math.isclose(value, min(ratio(v) for v in variants.values()), abs_tol=1e-10) or variants[selected] != value:
            raise ValueError('F detail minimum differs')
    return {'method': 'continuous-f-component-reuse-v1', 'score': value,
            'status': 'measured' if value is not None else 'not_measurable',
            'selected_variant': record['component_variants']['F'],
            'values_by_variant': deepcopy(record['component_values_by_variant']['F']),
            'source_component': 'F', 'measurements': atoms}


def detail_from_criteria(plan, criteria, visual_by_variant, expected_variants):
    """Reaggregate an explicit, model-independent list of existing visual atoms.

    Each variant is scored before taking the minimum; the minimum Q or T variant
    is not assumed to be the minimum of a newly selected subset.
    """
    definitions = {m['id']: m for m in plan['measurements']}
    if not criteria or len(criteria) != len(set(criteria)):
        raise ValueError('An explicit nonempty distinct criterion list is required')
    if not expected_variants or len(expected_variants) != len(set(expected_variants)):
        raise ValueError('Distinct expected variants required')
    if set(visual_by_variant) - set(expected_variants):
        raise ValueError('Unexpected visual variant')
    for key in criteria:
        if key not in definitions or definitions[key]['method'] != 'visual_coverage_deviation':
            raise ValueError('Detail criteria must reuse existing visual measurements')
    denominator = math.fsum(definitions[k]['weight'] for k in criteria)
    if denominator <= 0:
        raise ValueError('Positive detail weight required')
    weights = {k: definitions[k]['weight'] / denominator for k in criteria}
    values, missing = {}, []
    for name in expected_variants:
        visual = visual_by_variant.get(name, {})
        absent = [k for k in criteria if visual.get(k) is None]
        if absent:
            values[name] = None
            missing.extend(name + ':' + k for k in absent)
        else:
            # Inputs are strictly validated above; only contain summation roundoff.
            values[name] = min(1., max(0., math.fsum(weights[k] * ratio(visual[k]) for k in criteria)))
    selected = None if missing else min(expected_variants, key=values.__getitem__)
    atoms = [{'id': k, 'method': definitions[k]['method'], 'weight': weights[k],
              'value': visual_by_variant[selected][k] if selected else None,
              'selected_variant': selected} for k in criteria]
    return {'method': 'continuous-visual-subset-minimum-v1', 'status': 'not_measurable' if missing else 'measured',
            'score': None if missing else values[selected], 'selected_variant': selected,
            'values_by_variant': values, 'measurements': atoms,
            'criterion_ids': list(criteria), 'missing_measurements': missing}


def detail_from_mixed_criteria(plan, criteria, scores_by_variant, expected_variants):
    """Combine native mechanism observations and visual detail at frozen weights."""
    copied = deepcopy(plan)
    native = []
    for atom in copied['measurements']:
        if atom['id'] not in criteria or atom['method'] == 'visual_coverage_deviation': continue
        if atom['id'] != 'hinge_kinematics' or atom['method'] != 'normalized_error_kernel':
            raise ValueError('No specialized collector registered for '+atom['id'])
        native.append(atom['id'])
        # The common aggregator consumes already measured numeric atom scores;
        # its weighting/minimum-variant arithmetic is identical for both kinds.
        atom['method'] = 'visual_coverage_deviation'
    result = detail_from_criteria(copied, criteria, scores_by_variant, expected_variants)
    if native:
        result.update(method='mixed-native-visual-detail-v1', native_criterion_ids=native)
        for atom in result['measurements']:
            if atom['id'] in native: atom['method'] = 'normalized_error_kernel'
    return result


def replace_connection(report, detail, *, source_report, detail_record, release_id):
    """Replace the declared physics term without changing any other old score."""
    weights = legacy_weights(report)
    if not math.isclose(weights.get('physics', 0), .1, abs_tol=1e-12):
        raise ValueError('Only the legacy 10% connection/physics term may be replaced')
    if detail_record['task_id'] != report['task_id']:
        raise ValueError('Detail task identity differs')
    if detail_record['source_bindings']['selected_report'] != source_report:
        raise ValueError('Detail belongs to a different accepted candidate report')
    if type(report.get('score_valid')) is not bool or detail_record['effective_validity'] is not report['score_valid']:
        raise ValueError('Legacy and detail delivery validity differ')
    valid = report['score_valid']
    old = report['score_components']
    if valid and report.get('S_core') is not None:
        replay = math.fsum(weights[k] * ratio(old[k]) for k in weights)
        if not math.isclose(replay, ratio(report['S_core']), abs_tol=1e-8):
            raise ValueError('Original score and component arithmetic differ')
    if not valid and report.get('S_core') != 0:
        raise ValueError('Confirmed delivery failure must retain zero')
    value = detail.get('score') if detail.get('status') == 'measured' else None
    if value is not None:
        ratio(value)
    output = deepcopy(report)
    components = output['score_components']
    if not components and not valid:
        for key, weight in weights.items():
            components.update({key: None, key+'_weight': weight, key+'_contribution': 0.})
    archived = {k: components.pop(k) for k in list(components) if k == 'physics' or k.startswith('physics_')}
    weight = weights.pop('physics')
    weights[COMPONENT] = weight
    components.update(detail=value, detail_weight=weight,
                      detail_contribution=0. if not valid else None if value is None else weight * value)
    missing = [k for k in weights if components.get(k) is None]
    total = 0. if not valid else None if missing else math.fsum(weights[k] * components[k] for k in weights)
    output.update(method_version=report['method_version'] + '+detail-v1',
                  release_id=release_id, legacy_method_version=report['method_version'],
                  S_core=total, S_level=total,
                  status='system_invalid' if not valid else 'not_measurable' if missing else 'scored',
                  measurement_complete=not valid or not missing, missing_components=missing,
                  component_weights=weights, formal_score_eligible=False,
                  detail_measurement=deepcopy(detail),
                  legacy_replacement={'version': VERSION, 'source_report': deepcopy(source_report),
                      'source_model': detail_record['model'], 'old_score': report['S_core'],
                      'removed_components': archived, 'replacement_weight': weight,
                      'preserved_component_ids': [k for k in weights if k != COMPONENT],
                      'quality_scope': 'Legacy accepted-candidate scores plus continuous detail; original system gates retained'})
    removed_evidence = {}
    if 'physical_plausibility' in output:
        removed_evidence['physical_plausibility'] = output.pop('physical_plausibility')
    if isinstance(output.get('measurements'), dict) and 'physics' in output['measurements']:
        removed_evidence['physics'] = output['measurements'].pop('physics')
        output['measurements']['detail'] = deepcopy(detail)
    output['legacy_replacement']['removed_evidence'] = removed_evidence
    if isinstance(output.get('protocol'), dict):
        output['protocol']['component_weights'] = deepcopy(weights)
        output['protocol']['evaluation_mode'] = VERSION
    if total is not None and report.get('S_core') is not None:
        output['legacy_replacement']['delta_points'] = 100 * (total - report['S_core'])
    return output
