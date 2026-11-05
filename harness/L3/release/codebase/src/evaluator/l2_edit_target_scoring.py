"""Versioned edit-target quality: native target similarity and protected scene state."""
from __future__ import annotations

import math
import numpy as np

from .l2_edit_light_properties import light_properties, fixed_light_properties
from .l2_edit_regions import reference_indices
from .l2_reference_scoring import VALIDITY_CHECKS, RENDER_CHECKS

PROFILE = 'l2-edit-target-v4.0.0'
MODE = 'native_edit_target_quality'
GEOMETRY_WEIGHTS = {'surface': .60, 'regions': .25, 'structure': .15}


def validate_plan(plan, policy):
    s = plan['scoring']
    if (plan['category'] != 'SceneEdit' or s.get('evaluation_mode') != MODE
            or s.get('main_image_weight') != 0. or s.get('target_weight') != .8
            or s.get('preservation_weight') != .2 or s.get('numeric_weight') != .2
            or s.get('similarity_weight') != .6 or s.get('minimum_quality', 'absent') is not None
            or s.get('geometry_weights') != GEOMETRY_WEIGHTS):
        raise ValueError('Edit target requires version-bound 80/20 weights and no content threshold')
    if plan.get('edit_measurement_mode') not in {'geometry', 'lighting'}:
        raise ValueError('Edit target needs geometry or lighting mode')
    ref = plan.get('reference_target', {})
    if not ref.get('scene') or ref['scene'] not in ref.get('files', []):
        raise ValueError('Native reference scene must be bound for all edit modes')
    checks = {c['id']: c.get('existing_check') for c in plan['active_checks']}
    if any(checks.get(name) != name for name in RENDER_CHECKS):
        raise ValueError('Native render delivery checks are required')
    if plan['edit_measurement_mode'] == 'geometry' and (not ref.get('objects') or not plan.get('edit_regions')):
        raise ValueError('Geometry target needs private object and region selectors')


def geometry_similarity(candidate, baseline, reference, plan, measured):
    a, b = (x['scene'].get('visible_surface', {}) for x in (candidate, reference))
    if any(v.get('status') != 'measured' for v in (a, b)) or a.get('size') != b.get('size'):
        return {'status': 'not_measurable', 'score': 0., 'reason': 'Comparable native visible surfaces required'}
    before = baseline['scene']['objects']
    targets = set(plan['reference_target']['objects'])
    expected = np.asarray([n in targets for n in b['object_names']], bool)
    actual = np.asarray([n is not None and n not in before for n in a['object_names']], bool)
    if expected.sum() < 8:
        raise ValueError('Reference target has insufficient visible samples')

    def coverage(indices):
        points = np.asarray([b['world_points_m'][i] for i in indices], float)
        diagonal = float(np.linalg.norm(np.ptp(points, axis=0)))
        tolerance = max(diagonal * .03, 1e-7)
        scores = []
        for i, point in zip(indices, points):
            hit = a['world_points_m'][i]
            scores.append(float(np.exp(-np.linalg.norm(np.asarray(hit) - point) / tolerance))
                          if actual[i] and hit is not None else 0.)
        return {'score': float(np.mean(scores)), 'samples': len(indices), 'distance_scale_m': tolerance}

    indices = np.flatnonzero(expected)
    union = expected | actual
    iou = float((expected & actual).sum() / union.sum())
    whole = coverage(indices)
    surface = .5 * iou + .5 * whole['score']
    regions = []
    for definition in plan['edit_regions']:
        selected = reference_indices(b, definition)
        if len(selected) < 8:
            raise ValueError('Reference region has insufficient samples: ' + definition['id'])
        regions.append({'id': definition['id'], **coverage(selected)})
    structural = dict(measured.get('edit_structure', {}))
    # A thick block is not rewarded for absent target surface or empty required regions.
    structure = float(np.mean([x.get('score', 0.) for x in structural.values()])) if structural else 0.
    groups = {'surface': surface, 'regions': float(np.mean([r['score'] for r in regions])), 'structure': structure}
    return {'status': 'measured', 'score': sum(GEOMETRY_WEIGHTS[k] * v for k, v in groups.items()),
            'groups': groups, 'weights': GEOMETRY_WEIGHTS, 'silhouette_iou': iou,
            'surface': whole, 'regions': regions, 'structure': structural,
            'reference_samples': int(expected.sum()), 'candidate_samples': int(actual.sum()),
            'threshold_status': 'pilot_not_calibrated',
            'scope': 'Native main-camera visible surfaces and explicit structure, no RGB or hidden exact-shape target'}


def preservation(candidate, baseline, audit, policy):
    before, after = baseline['scene'], candidate['scene']
    failures = audit.get('content_failures', [])
    rows = []
    for name, obj in before['objects'].items():
        if obj['type'] == 'LIGHT':
            continue
        damaged = any(f.get('object') == name for f in failures)
        rows.append({'object': name, 'domain': 'cameras' if obj['type'] == 'CAMERA' else 'scene_objects',
                     'score': float(name in after['objects'] and not damaged)})
    domains = {}
    for category in ('scene_objects', 'cameras'):
        values = [r['score'] for r in rows if r['domain'] == category]
        if values:
            domains[category] = float(np.mean(values))
    lights = fixed_light_properties(before, after,
        allow_color_energy=policy.get('edit_policy', {}).get('light_color_energy', False))
    if lights['score'] is not None:
        domains['lights'] = lights['score']
    world_failures = [f for f in failures if f.get('field') == 'world_sha256'
                      or f['check'] == 'world_except_background_strength']
    domains['world'] = float(not world_failures)
    domains['render_and_frame'] = float(not any(f.get('field') in {'render', 'render_settings_sha256'}
                                               or f['check'] == 'saved_frame' for f in failures))
    if policy.get('edit_policy', {}).get('mode') == 'lighting':
        old = {n for n,o in before['objects'].items() if o['type'] not in {'LIGHT','CAMERA'}}
        new = {n for n,o in after['objects'].items() if o['type'] not in {'LIGHT','CAMERA'}}
        domains['scene_objects'] = domains.get('scene_objects', 0.) * (len(old & new) / max(len(old | new), 1))
    return {'status': 'measured', 'score': float(np.mean(list(domains.values()))),
            'domains': domains, 'objects': rows, 'light_properties': lights,
            'content_failures': failures, 'scope': 'Equal domain weights; allowed target attributes excluded'}


def measure_edit_target(candidate, baseline, reference, plan, policy, audit, measured):
    target = (light_properties(candidate, baseline, reference,
                  world_strength=policy['edit_policy'].get('world_background_strength', False))
              if plan['edit_measurement_mode'] == 'lighting'
              else geometry_similarity(candidate, baseline, reference, plan, measured))
    return {'target': target, 'preservation': preservation(candidate, baseline, audit, policy),
            'mode': plan['edit_measurement_mode']}


def score_edit_target(legacy, measurements, evidence, policy, plan, *, execution_required):
    validate_plan(plan, policy)
    measured = evidence.get('native_edit_target', {})
    from .l2_edit_numeric import measure_numbers
    numbers = measure_numbers(evidence, plan['numeric_requirements'])
    for row in measurements:
        row.update(affects_eligibility=row['id'] in VALIDITY_CHECKS, affects_quality=False)
    texture = evidence.get('scene', {}).get('procedural_materials', {})
    measurements.append({'id': 'procedural_materials', 'passed': texture.get('passed') is True,
                         'score': float(texture.get('passed') is True), 'status': 'measured' if texture else 'missing',
                         'details': texture, 'affects_eligibility': True, 'affects_quality': False})
    values = {}
    for name in ('target', 'preservation'):
        result = measured.get(name, {})
        value = result.get('score', 0.)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('Invalid native edit measurement')
        values[name] = value
        measurements.append({'id': 'edit_' + name, 'passed': value >= 1 - 1e-8,
            'score': value, 'status': result.get('status', 'missing'), 'details': result,
            'affects_eligibility': False, 'affects_quality': True})
    for number in numbers['requirements']:
        measurements.append({'id': number['id'], 'source': number['source_quote'],
            'passed': number['passed'], 'score': number['score'], 'status': number['status'],
            'details': number, 'affects_eligibility': False,
            'affects_quality': number['status'] != 'pending_implementation'})
    required = [m for m in measurements if m['affects_eligibility']]
    failures = [m['id'] for m in required if m['passed'] is not True]
    gates = {name: legacy['gates'][name] for name in
             ('execution', 'artifacts', 'real_geometry', 'integrity', 'all_seeds', 'all_seed_quality')}
    gates['measured_requirements'] = {'passed': not failures, 'required': [m['id'] for m in required], 'failed': failures}
    local_valid = not failures and gates['artifacts']['passed'] and gates['real_geometry']['passed']
    eligible = all(g['passed'] for g in gates.values()) if execution_required else local_valid
    quality = .2 * numbers['score'] + .6 * values['target'] + .2 * values['preservation']
    legacy.update(gates=gates, status='passed' if eligible else 'failed', case_pass=bool(eligible),
        score_valid=bool(eligible), G=int(eligible), task_quality_pass=bool(local_valid),
        case_pass_meaning='System validity only; edit content is continuously scored',
        S_core=quality if eligible else 0., S_level=quality, S_diagnostic=quality,
        method_version=PROFILE, measurement_profile=policy['measurement_profile'], measurements=measurements,
        main_image_comparison={'status': 'not_in_scope', 'score': None},
        content_requirements={'passed': numbers['all_requirements_met'] and all(v >= 1-1e-8 for v in values.values()),
            'failed': ['edit_'+k for k,v in values.items() if v < 1-1e-8] + [r['id'] for r in numbers['requirements'] if r['passed'] is not True],
            'count': 2 + len(numbers['requirements']),
            'affects_eligibility': False, 'affects_quality': True},
        score_components={**values, 'target_weight': .8, 'preservation_weight': .2,
            'numeric': numbers['score'], 'numeric_weight': .2, 'similarity_weight': .6,
            'numeric_contribution': .2*numbers['score'] if eligible else 0.,
            'target_contribution': .6*values['target'] if eligible else 0.,
            'preservation_contribution': .2*values['preservation'] if eligible else 0.,
            'main_image': None, 'main_image_weight': 0.},
        native_edit_target=measured, numeric_requirements=numbers, quality_threshold=None, text_semantics_evaluated=False, vit_used=False,
        deferred_requirements=[r['id'] for r in policy['requirements'] if r['implementation'] != 'complete'],
        calibration_status=plan['scoring']['weights_status'], formal_score_eligible=False,
        evaluation_source_sha256=plan['sources']['solution/EVALUATION.md'],
        score_scope='20% published numerical requirements + 60% native target similarity + 20% protected scene',
        protocol={'evaluation_mode': MODE, 'target_weight': .8, 'preservation_weight': .2,
                  'numeric_weight': .2, 'similarity_weight': .6, 'main_image_weight': 0., 'minimum_quality': None},
        limitations=['Geometry scope is visible sampled surfaces and existing structural probes.',
                    'Material appearance and hidden exact geometry are not measured.',
                    'Light property agreement is not perceptual lighting equivalence.',
                    'Weights and distance/color scales need human calibration.'])
    return legacy
