"""Versioned L2 quality blend. VLM never establishes execution/system validity."""
from __future__ import annotations

import copy
import math
from pathlib import Path

PROFILES = {
    # v6.0 was a draft retaining the inherited 18/34/18 split; preserve its
    # identity for in-flight pilot evidence. New collections use round weights.
    'l2-edit-vlm-v6.1.0': ('SceneEdit', {'l2-edit-embodied-v5.0.0'}, {'numeric':.2,'target':.3,'preservation':.2,'physics':.1,'vlm':.2}),
    'l2-brief-vlm-v5.0.0': ('Brief2Scene', {'l2-brief-embodied-v4.0.0'}, {'vlm':.6,'data':.3,'physics':.1}),
    'l2-edit-vlm-v6.0.0': ('SceneEdit', {'l2-edit-embodied-v5.0.0'}, {'numeric':.18,'target':.34,'preservation':.18,'physics':.1,'vlm':.2}),
    'l2-reference-vlm-v6.0.0': ('Reference2Scene', {'l2-reference-embodied-v4.0.0'}, {'main_image':.6,'physics':.1,'render_validity':.1,'vlm':.2}),
    'l2-photo-vlm-v6.0.0': ('Reference2Scene-RealPhoto', {'l2-photo-embodied-v4.0.0'}, {'main_image':.6,'physics':.1,'render_validity':.1,'vlm':.2}),
    'l2-reference-localized-vlm-v6.0.0': ('Reference2Scene', {f'l2-reference-localized-v5.{i}.0' for i in range(4)}, {'main_image':.4,'localization':.2,'physics':.1,'render_validity':.1,'vlm':.2}),
    'l2-photo-localized-vlm-v6.0.0': ('Reference2Scene-RealPhoto', {'l2-photo-localized-v5.0.0'}, {'main_image':.4,'localization':.2,'physics':.1,'render_validity':.1,'vlm':.2}),
}


STRICT_PROFILES = {
    'l2-brief-vlm-v7.0.0': PROFILES['l2-brief-vlm-v5.0.0'],
    'l2-edit-vlm-v7.0.0': PROFILES['l2-edit-vlm-v6.1.0'],
    'l2-reference-localized-vlm-v7.0.0': PROFILES['l2-reference-localized-vlm-v6.0.0'],
    'l2-photo-localized-vlm-v7.0.0': PROFILES['l2-photo-localized-vlm-v6.0.0'],
    # v7.1 removes render_validity from the weighted quality blend. The
    # execution/anti-cheating checks remain gates and are still reported.
    'l2-reference-localized-vlm-v7.1.0': ('Reference2Scene', {f'l2-reference-localized-v5.{i}.0' for i in range(4)},
        {'main_image':.5,'localization':.2,'physics':.1,'vlm':.2}),
    'l2-photo-localized-vlm-v7.1.0': ('Reference2Scene-RealPhoto', {'l2-photo-localized-v5.0.0'},
        {'main_image':.5,'localization':.2,'physics':.1,'vlm':.2}),
}
PROFILES.update(STRICT_PROFILES)

# Optional scoring profile; retain the v7 defaults and L1 replay contract.
FIDELITY_PROFILES = {
    'l2-brief-vlm-v8.0.0': STRICT_PROFILES['l2-brief-vlm-v7.0.0'],
    'l2-edit-vlm-v8.0.0': STRICT_PROFILES['l2-edit-vlm-v7.0.0'],
    'l2-reference-localized-vlm-v8.0.0': STRICT_PROFILES['l2-reference-localized-vlm-v7.1.0'],
    'l2-photo-localized-vlm-v8.0.0': STRICT_PROFILES['l2-photo-localized-vlm-v7.1.0'],
}
REFRESH_VLM_PROFILES = {
    'l2-reference-refresh-vlm-v9.0.0': ('Reference2Scene', {'l2-reference-refresh-v1.0.0'},
        {'main_image':.5,'localization':.2,'physics':.1,'vlm':.2}),
    'l2-photo-refresh-vlm-v9.0.0': ('Reference2Scene-RealPhoto', {'l2-photo-refresh-v1.0.0'},
        {'main_image':.5,'localization':.2,'physics':.1,'vlm':.2}),
}
PROFILES.update(FIDELITY_PROFILES)
PROFILES.update(REFRESH_VLM_PROFILES)
ALL_FIDELITY_PROFILES = {**FIDELITY_PROFILES, **REFRESH_VLM_PROFILES}


def fidelity_profile_for(category):
    return next(p for p, (family, _, _) in FIDELITY_PROFILES.items() if family == category)


def strict_profile_for(category, base_profile):
    for profile,(family,bases,_) in reversed(STRICT_PROFILES.items()):
        if family==category and base_profile in bases:return profile
    raise ValueError('No strict VLM profile for this automatic base')


def profile_for(category, base_profile):
    for profile, (family, bases, _) in PROFILES.items():
        if category == family and base_profile in bases:
            return profile
    raise ValueError('VLM blending requires an explicit supported automatic profile')


def automatic_policy(policy):
    if policy.get('scoring_profile') not in PROFILES:
        return policy
    _, bases, _ = PROFILES[policy['scoring_profile']]
    if policy.get('automatic_profile') not in bases:
        raise ValueError('VLM automatic profile mismatch')
    return {**policy, 'scoring_profile':policy['automatic_profile']}


def load_config(root, policy, plan):
    from src.agent_judge import L2_PROTOCOL
    from src.agent_judge.protocol import read_json, validate_spec, digest, contract_hash
    from .spec import contained_path
    profile = policy['scoring_profile']
    category, _, weights = PROFILES[profile]
    automatic_policy(policy)
    config = plan.get('vlm_judge', {})
    from src.agent_judge import l2_rubric, l2_fidelity
    fidelity=profile in ALL_FIDELITY_PROFILES
    strict=profile in STRICT_PROFILES or fidelity
    version='l2-vlm-judge-v3' if fidelity else 'l2-vlm-judge-v2' if strict else 'l2-vlm-judge-v1'
    protocol=l2_fidelity.PROTOCOL if fidelity else l2_rubric.PROTOCOL if strict else L2_PROTOCOL
    if (plan['category'] != category or config.get('version') != version
            or config.get('component_weights') != weights or config.get('mode') not in {'visual','interactive'}
            or config.get('missing_policy') != (l2_rubric.MISSING_POLICY if strict else 'unmeasured_no_redistribution')):
        raise ValueError('VLM configuration/category/weights mismatch')
    path = contained_path(Path(root), config['spec_path'])
    if digest(path) != config['spec_sha256']:
        raise ValueError('Frozen VLM spec changed')
    spec = validate_spec(read_json(path))
    if (spec['protocol'] != protocol or spec['family'] != category or spec['case_id'] != policy['task_id']
            or spec['instruction_sha256'] != contract_hash((Path(root)/'instruction.md').read_text())):
        raise ValueError('VLM task/instruction binding mismatch')
    if strict and category=='SceneEdit':
        if set(config.get('edit_context',{}))!={'before','target'}:raise ValueError('Frozen before/target edit context required')
        for item in config['edit_context'].values():
            if digest(contained_path(Path(root),item['path']))!=item['sha256']:raise ValueError('Edit context changed')
    if strict and category.startswith('Reference') and not spec.get('localization'):raise ValueError('Strict reference rubric requires frozen localization')
    return {**config, 'spec':spec}


def finite_score(value):
    return type(value) in (int,float) and math.isfinite(value) and 0 <= value <= 1


def add_vlm(base, judgment, profile):
    """Pure replayable aggregation; a judge fault cannot yield a model zero."""
    _, allowed, weights = PROFILES[profile]
    if base.get('method_version') not in allowed:
        raise ValueError('Base report does not match VLM profile')
    result = copy.deepcopy(base)
    judge = copy.deepcopy(judgment or {'status':'not_measurable','reason':'VLM evidence unavailable','S_vlm':None})
    measured = judge.get('status') == 'scored' and finite_score(judge.get('S_vlm'))
    if judge.get('status') == 'scored' and not measured:
        raise ValueError('Scored judge result must contain a finite unit score')
    c = base.get('score_components', {})
    values = {key:judge['S_vlm'] if measured else None for key in ['vlm']}
    values.update({key:c.get(key) for key in weights if key != 'vlm'})
    strict=profile in STRICT_PROFILES or profile in ALL_FIDELITY_PROFILES
    if strict and 'localization' in weights:
        values['localization']=None
    if strict and 'localization' in weights and measured:
        loc=judge.get('localization')
        if loc and loc.get('method')=='vlm-grounded-reference-boxes-v2' and loc.get('status')=='measured' and finite_score(loc.get('score')):
            if loc.get('image_sha256')!=base.get('artifact_sha256',{}).get('main.png'):
                raise ValueError('Grounded boxes must bind the audited candidate image')
            values['localization']=loc['score']
            result['localization']=copy.deepcopy(loc)
            result['localization_complete']=True
            result['measurements']=[r for r in result.get('measurements',[]) if r.get('id')!='object_localization']
            result['measurements'].append({'id':'object_localization','status':'measured','score':loc['score'],
                'passed':loc['score']>=1-1e-8,'affects_quality':True,'affects_eligibility':False,'details':loc})
    system_invalid = base.get('score_valid') is False and base.get('S_core') == 0
    complete = (finite_score(base.get('S_core')) or strict and 'localization' in weights and result.get('localization_complete') is True and base.get('score_valid') is True) and measured and all(finite_score(value) for value in values.values())
    components = {}
    for key, weight in weights.items():
        components.update({key:values[key],key+'_weight':weight,
            key+'_contribution':0. if system_invalid else weight*values[key] if finite_score(values[key]) else None})
    # Keep the historical field's meaning for edit consumers.
    if 'target' in weights:
        components['similarity_weight'] = weights['target']
        components['target_weight'] = weights['target']+weights.get('numeric',0)
        components.update(main_image=None,main_image_weight=0.)
    total = 0. if system_invalid else sum(components[key+'_contribution'] for key in weights) if complete else None
    result.update(method_version=profile,automatic_profile=base['method_version'],
        automatic_score=base.get('S_core'),S_core=total,automatic_S_core=total,
        S_vlm=judge.get('S_vlm') if measured else None,vlm_judgment=judge,score_components=components,
        status='scored' if total is not None else 'not_measurable',
        score_scope='Frozen automatic measurements plus issue-based VLM quality; unchanged system gates',
        calibration_status='pilot_vlm_human_calibration_pending',formal_score_eligible=False,
        measurement_complete=complete or system_invalid,
        text_semantics_evaluated=measured,
        protocol={**base.get('protocol',{}),'evaluation_mode':'automatic_and_vlm_quality',
            'component_weights':weights,'vlm_weight':weights['vlm'],
            **{key:value for key,value in components.items() if key.endswith('_weight')}},
        automatic_diagnostic_score=base.get('S_diagnostic'),S_diagnostic=total,S_level=total)
    # Preserve all automatic validity flags, including genuine invalidity and
    # unknown infrastructure status. Missing quality does not mean system fail.
    result['task_quality_pass'] = base.get('task_quality_pass')
    if strict:
        result['limitations']=[r for r in result.get('limitations',[]) if 'Missing localization measurement' not in r]
        result['score_scope']='Frozen automatic measurements + anchored task-specific VLM v2; explicit visible-evidence credit; unchanged validity gates'
        if profile.endswith('v7.1.0') or profile in ALL_FIDELITY_PROFILES:
            result['score_scope']='Frozen image/localization/physics measurements + anchored task-specific VLM v2; validity remains a system gate and is not a weighted score component'
            result['protocol'].pop('render_validity_weight', None)
        if profile in ALL_FIDELITY_PROFILES:
            result['score_scope']='Frozen automatic measurements + case-specific fidelity VLM v3; original references and both authored views; no registration; unchanged weights and system gates'
        result.setdefault('limitations',[]).append('Machine reference annotations and VLM grades are explicit benchmark measurements, not human certification. Candidate non-demonstration loses criterion credit; technical failures block publication. Human calibration remains pending.')
    else:
        result.setdefault('limitations', []).append('VLM judgments require human calibration; semantic mistakes reduce quality only. Unobservable/low-confidence judgments suppress the total without redistributing weights.')
    return result
