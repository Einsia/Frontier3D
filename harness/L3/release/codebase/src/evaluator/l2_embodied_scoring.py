"""Explicit 10% physical quality extensions of existing L2 scoring profiles."""
import copy
import math

BRIEF_PROFILE='l2-brief-embodied-v4.0.0'
EDIT_PROFILE='l2-edit-embodied-v5.0.0'
PHOTO_PROFILE='l2-photo-embodied-v4.0.0'
BASE_PROFILES={BRIEF_PROFILE:'l2-brief-quality-v3.0.0',EDIT_PROFILE:'l2-edit-target-v4.0.0',
               PHOTO_PROFILE:'l2-reference-visual-v3.1.0'}
CATEGORIES={BRIEF_PROFILE:'Brief2Scene',EDIT_PROFILE:'SceneEdit',PHOTO_PROFILE:'Reference2Scene-RealPhoto'}
WEIGHTS={BRIEF_PROFILE:{'data':.9,'physics':.1},
         EDIT_PROFILE:{'numeric':.18,'target':.54,'preservation':.18,'physics':.1},
         PHOTO_PROFILE:{'main_image':.8,'render_validity':.1,'physics':.1}}
MODE='system_validity_with_physical_quality'


def base_policy(policy):
    profile=policy.get('scoring_profile')
    return {**policy,'scoring_profile':BASE_PROFILES[profile]} if profile in BASE_PROFILES else policy


def base_plan(plan):
    return {**plan,'scoring':plan['base_scoring']}


def validate_plan(plan,policy):
    from .l2_physical_adaptation import validate_configuration
    profile=policy['scoring_profile'];weights=WEIGHTS[profile]
    if (plan['category']!=CATEGORIES[profile] or plan.get('base_scoring_profile')!=BASE_PROFILES[profile]
            or plan['scoring']!={'evaluation_mode':MODE,'component_weights':weights,'physics_weight':.1,
                                'minimum_quality':None,'weights_status':'pilot_not_calibrated'}):
        raise ValueError('Embodied profile requires version-bound category, base and weights')
    validate_configuration(plan['physics'],plan['category'],plan['task_id'],plan.get('edit_measurement_mode'))


def add_physics(base,physics,policy,plan):
    """No physical/content result can change the original system validity gates."""
    validate_plan(plan,policy)
    if (physics.get('status') not in {'measured','not_measurable','not_applicable'}
            or type(physics.get('score')) not in (int,float) or not math.isfinite(physics['score'])
            or not 0<=physics['score']<=1):
        raise ValueError('Explicit finite physical result required')
    profile=policy['scoring_profile'];weights=WEIGHTS[profile];result=copy.deepcopy(base)
    eligible=base['score_valid'];components=copy.deepcopy(base['score_components'])
    components['physics']=physics['score']
    if profile==PHOTO_PROFILE:components['render_validity']=float(eligible)
    values={name:float(components[name] or 0.) for name in weights}
    quality=sum(weights[name]*values[name] for name in weights)
    for name,weight in weights.items():
        components[name+'_weight']=weight
        components[name+'_contribution']=weight*values[name] if eligible else 0.
    if profile==EDIT_PROFILE:
        # target_weight historically means numeric + similarity, while the
        # measured target scalar is native target similarity alone.
        components['target_weight']=.72;components['similarity_weight']=.54
    protocol={**base.get('protocol',{}),'evaluation_mode':MODE,'component_weights':weights,'physics_weight':.1}
    for name in ('numeric','similarity','target','preservation','main_image','data','render_validity'):
        if name+'_weight' in components:protocol[name+'_weight']=components[name+'_weight']
    result.update(method_version=profile,physical_plausibility=physics,
        S_core=quality if eligible else 0.,S_level=quality,S_diagnostic=quality,score_components=components,
        base_scoring_profile=BASE_PROFILES[profile],formal_score_eligible=False,
        score_scope=' + '.join(f'{weight:.0%} {name}' for name,weight in weights.items()),
        protocol=protocol,
        calibration_status='pilot_not_calibrated')
    result['measurements'].append({'id':'physical_plausibility','score':physics['score'],
        'passed':physics['score']>=1-1e-8,'status':physics['status'],'details':physics,
        'affects_eligibility':False,'affects_quality':True})
    result['limitations']=[*base.get('limitations',[]),
        'Physical quality is a static geometric proxy; it does not certify dynamics, strength or complete collision freedom.',
        'Unknown physical evidence earns no physical credit; it does not invalidate the other quality components.']
    return result


def score(spec,evidence,policy,plan,*,execution_required=True):
    from .l2_method_scoring import score_measured
    from .l2_physical_adaptation import measure_physics
    validate_plan(plan,policy)
    base=score_measured(spec,evidence,base_policy(policy),base_plan(plan),execution_required=execution_required)
    physics=measure_physics(evidence,plan['physics'])
    return add_physics(base,physics,policy,plan)
