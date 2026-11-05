"""Reference visual score: render validity gates, continuous appearance quality."""
import math


RENDER_CHECKS=frozenset({'main_native_size','main_png','alternate_native_size','alternate_png'})
VALIDITY_CHECKS=RENDER_CHECKS | {'procedural_materials'}
MODE='render_and_reference_similarity'


def profile_weights(profile):
    from .l2_reference_boxes import PROFILES as LOCALIZED
    if profile in LOCALIZED:return .6,.1
    from .l2_method_scoring import REFERENCE_VISUAL_PROFILE,REFERENCE_WEIGHTED_PROFILE,REFERENCE_EMBODIED_PROFILE
    if profile==REFERENCE_VISUAL_PROFILE:return 1.,0.
    if profile==REFERENCE_WEIGHTED_PROFILE:return .8,.2
    if profile==REFERENCE_EMBODIED_PROFILE:return .8,.1
    raise ValueError('Unknown visual scoring profile')


def validate_visual_plan(plan,profile):
    image_weight,validity_weight=profile_weights(profile)
    scoring=plan['scoring']
    if (scoring.get('evaluation_mode')!=MODE or scoring.get('main_image_weight')!=image_weight
            or scoring.get('render_validity_weight',0.)!=validity_weight
            or scoring.get('diagnostic_weight',0.)!=0.
            or 'minimum_similarity' not in scoring or scoring['minimum_similarity'] is not None):
        raise ValueError('Visual reference profile requires version-bound weights without a pass threshold')
    existing={c['id']:c.get('existing_check') for c in plan['active_checks']}
    if any(existing.get(name)!=name for name in RENDER_CHECKS):
        raise ValueError('Visual reference profile requires native PNG delivery checks')
    from .l2_reference_regions import PROFILE
    from .l2_reference_boxes import PROFILES as LOCALIZED,SCENE_PROFILES,PHOTO_PROFILE,WEIGHTS
    if profile in LOCALIZED and (scoring.get('localization_weight')!=.2 or scoring.get('component_weights')!=WEIGHTS):
        raise ValueError('Localized profile requires fixed 60/20/10/10 weights')
    if profile==PHOTO_PROFILE:
        from .l2_physical_adaptation import validate_configuration
        if scoring.get('physics_weight')!=.1:
            raise ValueError('Photo localization requires 10% physics')
        validate_configuration(plan['physics'],plan['category'],plan['task_id'],None)
    if profile in {PROFILE,*SCENE_PROFILES}:
        from .l2_physical import validate_policy
        if scoring.get('physics_weight')!=.1:
            raise ValueError('Embodied profile requires 10% physics')
        validate_policy(plan['physics'])
        if plan['physics']['gravity']=='space' and plan.get('task_id')!='L2/Reference2Scene/task_L2_Reference2Scene-003':
            raise ValueError('Space exception is restricted to the reviewed outer-space task')
        if (plan['physics']['ground_mode']=='diorama_platform' and plan.get('task_id') not in {
                'L2/Reference2Scene/task_L2_Reference2Scene-005','L2/Reference2Scene/task_L2_Reference2Scene-009'}):
            raise ValueError('Diorama datum is restricted to reviewed city/island tasks')


def score_reference_visual(legacy,measurements,image,policy,plan,*,execution_required,physics=None):
    validate_visual_plan(plan,policy['scoring_profile'])
    image_weight,validity_weight=profile_weights(policy['scoring_profile'])
    for measurement in measurements:
        measurement['affects_eligibility']=measurement['id'] in VALIDITY_CHECKS
        measurement['affects_similarity']=False
    required=[m for m in measurements if m['affects_eligibility']]
    diagnostic=[m for m in measurements if not m['affects_eligibility']]
    measured=(image.get('status')=='measured' and isinstance(image.get('score'),(float,int))
              and math.isfinite(image['score']) and 0.<=image['score']<=1.)
    # In particular, missing bench_role or a failed scale probe cannot fail a seed.
    validity=all(m['passed'] for m in required) and measured
    image_score=float(image['score']) if measured else 0.
    gates={name:legacy['gates'][name] for name in
           ('execution','artifacts','real_geometry','integrity','all_seeds','all_seed_quality')}
    gates['measured_requirements']={'passed':bool(validity),
        'required':[m['id'] for m in required]+['main_image_comparable'],
        'failed':[m['id'] for m in required if not m['passed']]+([] if measured else ['main_image_comparable'])}
    local_valid=bool(validity and gates['artifacts']['passed'] and gates['real_geometry']['passed'])
    eligible=all(g['passed'] for g in gates.values()) if execution_required else local_valid
    quality=image_weight*image_score+validity_weight*float(eligible)
    legacy.update(
        gates=gates,status='passed' if eligible else 'failed',case_pass=eligible,G=int(eligible),
        score_valid=eligible,case_pass_meaning='Valid reproducible render; not a similarity threshold',
        S_core=quality if eligible else 0.,S_diagnostic=quality,S_level=quality,
        task_quality_pass=local_valid,method_version=policy['scoring_profile'],
        score_scope='Reference main-view appearance; dimensions, structure and camera conventions are diagnostics',
        measurements=measurements,main_image_comparison=image,
        score_components={'main_image':image.get('score'),'main_image_weight':image_weight,'data_weight':0.},
        diagnostic_requirements={'passed':all(m['passed'] for m in diagnostic),
            'failed':[m['id'] for m in diagnostic if not m['passed']],
            'count':len(diagnostic),'affects_main_score':False},
        similarity_pass=None,similarity_threshold=None,
        text_semantics_evaluated=False,vit_used=False,deferred_requirements=[],
        excluded_legacy_requirements=[r['id'] for r in policy['requirements'] if r['implementation']!='complete'],
        calibration_status=plan['scoring']['weights_status'],formal_score_eligible=False,
        evaluation_source_sha256=plan['sources']['solution/EVALUATION.md'],
        protocol={'quality':'native-appearance-v1','main_image_weight':image_weight,'data_weight':0.,
            'minimum_similarity':None,'seeds':legacy.get('protocol',{}).get('seeds',[]),
            'render_views':legacy.get('protocol',{}).get('render_views',[])},
        limitations=['Image similarity is an uncalibrated visual proxy, not semantic object recognition.',
            'Single-view appearance does not certify hidden geometry or physical plausibility.',
            'Legacy modules and numeric requirements are diagnostic only.'])
    if validity_weight:
        legacy['score_components'].update(render_validity=float(eligible),render_validity_weight=validity_weight,
            main_image_contribution=image_weight*image_score if eligible else 0.,
            render_validity_contribution=validity_weight*float(eligible))
        legacy['protocol']['render_validity_weight']=validity_weight
        legacy['score_scope']='80% reference main-view similarity + 20% render/delivery validity; structural checks are diagnostics'
    from .l2_reference_regions import PROFILE
    if policy['scoring_profile']==PROFILE:
        if (not physics or physics.get('status') not in {'measured','not_measurable','not_applicable'}
                or not isinstance(physics.get('score'),(int,float)) or not math.isfinite(physics['score'])
                or not 0.<=physics['score']<=1.):
            raise ValueError('Explicit finite physics result required')
        quality+=.1*physics['score']
        legacy.update(S_core=quality if eligible else 0.,S_diagnostic=quality,S_level=quality,
            physical_plausibility=physics,
            score_scope='80% subject-focused reference appearance + 10% static support plausibility + 10% render validity')
        legacy['score_components'].update(physics=physics['score'],physics_weight=.1,
            physics_contribution=.1*physics['score'] if eligible else 0.)
        legacy['protocol'].update(quality='reference-regions-v1',physics='static-support-v1',physics_weight=.1)
        legacy['limitations']=['Reference regions are appearance proxies, not semantic object recognition.',
            'Physical component measures static surface support, not complete dynamics or penetration.',
            'Unknown physics earns no physics credit; it does not invalidate a reproducible scene.',
            'Pilot weights require independent perceptual calibration.']
    return legacy
