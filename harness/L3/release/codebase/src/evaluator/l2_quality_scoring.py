"""Separate submission validity from measured content quality, without a cutoff."""
from __future__ import annotations

import math

from .l2_reference_scoring import RENDER_CHECKS, VALIDITY_CHECKS

BRIEF_QUALITY_PROFILE = 'l2-brief-quality-v3.0.0'
EDIT_QUALITY_PROFILE = 'l2-edit-quality-v3.0.0'
EDIT_TARGET_PROFILE = 'l2-edit-target-v4.0.0'
QUALITY_PROFILES = {BRIEF_QUALITY_PROFILE, EDIT_QUALITY_PROFILE, EDIT_TARGET_PROFILE}
MODE = 'system_validity_content_quality'
BASES = {
    BRIEF_QUALITY_PROFILE: {'l2-brief-v2.8.0'},
    EDIT_QUALITY_PROFILE: {'l2-edit-v2.2.0', 'l2-edit-v2.3.0',
                           'l2-edit-v2.4.1', 'l2-edit-v2.5.1'},
}
BASES[EDIT_TARGET_PROFILE] = BASES[EDIT_QUALITY_PROFILE]


def measurement_policy(policy):
    """Reuse frozen measurement scopes; version the eligibility rule separately."""
    profile = policy.get('scoring_profile')
    if profile not in QUALITY_PROFILES:
        return policy
    base = policy.get('measurement_profile')
    if base not in BASES[profile]:
        raise ValueError('Quality profile requires a supported measurement profile')
    return {**policy, 'scoring_profile': base}


def validate_quality_plan(plan, policy):
    measurement_policy(policy)
    if policy['scoring_profile'] == EDIT_TARGET_PROFILE:
        from .l2_edit_target_scoring import validate_plan
        return validate_plan(plan, policy)
    brief = policy['scoring_profile'] == BRIEF_QUALITY_PROFILE
    scoring = plan['scoring']
    if (plan['category'] != ('Brief2Scene' if brief else 'SceneEdit')
            or scoring.get('evaluation_mode') != MODE
            or scoring.get('main_image_weight') != (0. if brief else .5)
            or 'minimum_quality' not in scoring or scoring['minimum_quality'] is not None):
        raise ValueError('Quality profile requires fixed weights and no content pass threshold')
    checks = {c['id']: c.get('existing_check') for c in plan['active_checks']}
    if any(checks.get(name) != name for name in RENDER_CHECKS):
        raise ValueError('Quality profile requires native PNG delivery checks')


def score_content_quality(legacy, measurements, image, policy, plan, *, execution_required):
    validate_quality_plan(plan, policy)
    brief = plan['category'] == 'Brief2Scene'
    for m in measurements:
        m['affects_eligibility'] = m['id'] in VALIDITY_CHECKS
        m['affects_quality'] = True
    validity = [m for m in measurements if m['affects_eligibility']]
    content = [m for m in measurements if not m['affects_eligibility']]
    required = [m['id'] for m in validity]
    failures = [m['id'] for m in validity if m['passed'] is not True]
    if not brief:
        required.append('main_image_comparable')
        value = image.get('score')
        if (image.get('status') != 'measured' or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= 1):
            failures.append('main_image_comparable')
    gates = {name: legacy['gates'][name] for name in
             ('execution', 'artifacts', 'real_geometry', 'integrity', 'all_seeds', 'all_seed_quality')}
    gates['all_seed_quality'] = {**gates['all_seed_quality'],
        'meaning': 'Every seed has valid render/delivery evidence; content mismatches do not block scoring'}
    gates['measured_requirements'] = {'passed': not failures, 'required': required, 'failed': failures}
    local_valid = not failures and gates['artifacts']['passed'] and gates['real_geometry']['passed']
    eligible = all(g['passed'] for g in gates.values()) if execution_required else local_valid
    # Retain the existing equal-weight measurement average and image split.
    # SceneEdit now includes a quality-only preservation item formerly in the audit gate.
    data_score = sum(m['score'] for m in measurements) / len(measurements)
    weight = plan['scoring']['main_image_weight']
    image_score = image.get('score') or 0.
    quality = (1 - weight) * data_score + weight * image_score
    legacy.update(
        gates=gates, status='passed' if eligible else 'failed', case_pass=bool(eligible),
        score_valid=bool(eligible), G=int(eligible), task_quality_pass=bool(local_valid),
        case_pass_meaning='System validity only; content mismatches reduce quality without a pass threshold',
        S_core=quality if eligible else 0., S_level=quality, S_diagnostic=quality,
        method_version=policy['scoring_profile'], measurement_profile=policy['measurement_profile'],
        measurements=measurements, main_image_comparison=image,
        content_requirements={'passed': all(m['passed'] for m in content),
            'failed': [m['id'] for m in content if not m['passed']], 'count': len(content),
            'affects_eligibility': False, 'affects_quality': True},
        score_components={'data': data_score, 'data_weight': 1 - weight,
            'main_image': image.get('score'), 'main_image_weight': weight,
            'data_contribution': (1 - weight) * data_score if eligible else 0.,
            'main_image_contribution': weight * image_score if eligible else 0.},
        quality_threshold=None, text_semantics_evaluated=False, vit_used=False,
        deferred_requirements=[r['id'] for r in policy['requirements'] if r['implementation'] != 'complete'],
        calibration_status=plan['scoring']['weights_status'], formal_score_eligible=False,
        evaluation_source_sha256=plan['sources']['solution/EVALUATION.md'],
        score_scope='Measured content quality; only system validity failures suppress the score',
        protocol={'evaluation_mode': MODE, 'measurement_profile': policy['measurement_profile'],
            'data_weight': 1 - weight, 'main_image_weight': weight, 'minimum_quality': None,
            'seeds': legacy.get('protocol', {}).get('seeds', []),
            'render_views': legacy.get('protocol', {}).get('render_views', [])},
        limitations=['Only implemented measurements contribute; text semantics remain incomplete.',
            'Measurement averaging and image weights are provisional and need perceptual calibration.',
            'A valid score, including zero, does not certify content correctness.'])
    return legacy
