"""Versioned measured scoring, with explicit numerical scope and deferred semantics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity

from .l2 import score_l2
from .metrics import evaluate_metric
from .spec import CheckSpec
from .l2_quality_scoring import QUALITY_PROFILES, EDIT_TARGET_PROFILE, measurement_policy, validate_quality_plan
from .l2_reference_regions import PROFILE as REFERENCE_EMBODIED_PROFILE
from .l2_reference_boxes import (PROFILE as REFERENCE_LOCALIZED_PROFILE, SCENE_PROFILES as LOCALIZED_PROFILES,
                                 PHOTO_PROFILE as PHOTO_LOCALIZED_PROFILE)
from .l2_embodied_scoring import BASE_PROFILES as EMBODIED_PROFILES

PROFILE='l2-measured-v2.0.0'
REFERENCE_PROFILE='l2-reference-v2.1.0'
REFERENCE_VISUAL_PROFILE='l2-reference-visual-v3.0.0'
REFERENCE_WEIGHTED_PROFILE='l2-reference-visual-v3.1.0'
REFERENCE_VISUAL_PROFILES={REFERENCE_VISUAL_PROFILE,REFERENCE_WEIGHTED_PROFILE}
REFERENCE_SCENE_PROFILES=REFERENCE_VISUAL_PROFILES | {REFERENCE_EMBODIED_PROFILE,*LOCALIZED_PROFILES}
EDIT_PROFILE='l2-edit-v2.1.0'
EDIT_STRUCTURE_PROFILE='l2-edit-v2.2.0'
EDIT_REGION_PROFILE='l2-edit-v2.3.0'
EDIT_REGION_EXPANSION_PROFILE='l2-edit-v2.5.0'
EDIT_REGION_REFINED_PROFILE='l2-edit-v2.5.1'
EDIT_COMPONENT_PROFILE='l2-edit-v2.4.0'
EDIT_COMPONENT_REFINED_PROFILE='l2-edit-v2.4.1'
BRIEF_PROFILE='l2-brief-v2.1.0'
BRIEF_RELIEF_PROFILE='l2-brief-v2.2.0'
BRIEF_RELATION_PROFILE='l2-brief-v2.3.0'
BRIEF_ASSEMBLY_PROFILE='l2-brief-v2.4.0'
BRIEF_ACCESS_PROFILE='l2-brief-v2.5.0'
BRIEF_PROPERTY_PROFILE='l2-brief-v2.6.0'
BRIEF_CONTACT_PROFILE='l2-brief-v2.7.0'
BRIEF_MATERIAL_PROFILE='l2-brief-v2.7.1'
BRIEF_PROJECTION_PROFILE='l2-brief-v2.8.0'
SUPPORTED_PROFILES={PROFILE,REFERENCE_PROFILE,EDIT_PROFILE,EDIT_STRUCTURE_PROFILE,EDIT_REGION_PROFILE,EDIT_REGION_EXPANSION_PROFILE,EDIT_REGION_REFINED_PROFILE,EDIT_COMPONENT_PROFILE,EDIT_COMPONENT_REFINED_PROFILE,BRIEF_PROFILE,BRIEF_RELIEF_PROFILE,BRIEF_RELATION_PROFILE,BRIEF_ASSEMBLY_PROFILE,BRIEF_ACCESS_PROFILE,BRIEF_PROPERTY_PROFILE,BRIEF_CONTACT_PROFILE,BRIEF_MATERIAL_PROFILE,BRIEF_PROJECTION_PROFILE}


SUPPORTED_PROFILES.update(REFERENCE_SCENE_PROFILES)
SUPPORTED_PROFILES.update(QUALITY_PROFILES)
SUPPORTED_PROFILES.update(EMBODIED_PROFILES)
SUPPORTED_PROFILES.add(PHOTO_LOCALIZED_PROFILE)


def load_methods(root, policy):
    from . import l2_numeric_methods,l2_reference_numeric,l2_brief_numeric,l2_brief_route,l2_brief_opening,l2_surface_relief,l2_brief_relations,l2_ball_course,l2_brief_assemblies,l2_course_access,l2_property_access,l2_support_chain,l2_material_connectivity,l2_projected_separation
    raw=(Path(root)/'harness/methods.json').read_bytes()
    plan=json.loads(raw)
    requested_plan=None
    if policy.get('scoring_profile') == PHOTO_LOCALIZED_PROFILE:
        from .l2_reference_boxes import validate_photo_plan,photo_base_plan,load_annotation
        validate_photo_plan(plan)
        annotation=load_annotation(root,plan['reference_boxes'])
        if annotation.get('scoring_profile')!=PHOTO_LOCALIZED_PROFILE or annotation['task_id']!=policy['task_id']:
            raise ValueError('Localized photo annotation identity mismatch')
        plan['_reference_boxes']=annotation
        requested_plan=plan
        policy={**policy,'scoring_profile':'l2-photo-embodied-v4.0.0'}
        plan=photo_base_plan(plan)
    if policy.get('scoring_profile') in EMBODIED_PROFILES:
        from .l2_embodied_scoring import validate_plan,base_policy,base_plan
        validate_plan(plan,policy)
        if requested_plan is None:requested_plan=plan
        policy=base_policy(policy);plan=base_plan(plan)
    if policy.get('scoring_profile') == EDIT_TARGET_PROFILE:
        from .l2_edit_numeric import validate_numbers
        validate_numbers(plan, (Path(root)/'instruction.md').read_text())
    if policy.get('scoring_profile') in QUALITY_PROFILES:
        validate_quality_plan(plan,policy)
        policy=measurement_policy(policy)
    if plan['task_id']!=policy['task_id'] or plan['version']!='l2-method-plan-v1':
        raise ValueError('Method plan identity mismatch')
    if set(plan['sources'])!={'instruction.md','solution/EVALUATION.md'}:
        raise ValueError('Both public instruction and private evaluation must be bound')
    if policy.get('scoring_profile') in SUPPORTED_PROFILES and hashlib.sha256(raw).hexdigest()!=policy.get('methods_sha256'):
        raise ValueError('Active method plan hash mismatch')
    for name,expected in plan['sources'].items():
        if name not in {'instruction.md','solution/EVALUATION.md'}:
            raise ValueError('Unexpected evaluator brief source')
        if hashlib.sha256((Path(root)/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('Method plan source changed: '+name)
    evaluation=(Path(root)/'solution/EVALUATION.md').read_text()
    if any(r['source_quote'] not in evaluation for r in plan['evaluation_rows']):
        raise ValueError('Method plan row does not match EVALUATION.md')
    if policy.get('scoring_profile') in SUPPORTED_PROFILES and not plan.get('active_checks'):
        raise ValueError('Active profile needs concrete per-case checks')
    if policy.get('scoring_profile') in {REFERENCE_PROFILE,*REFERENCE_SCENE_PROFILES}:
        method='reference-regions-v1' if policy.get('scoring_profile') in {REFERENCE_EMBODIED_PROFILE,*LOCALIZED_PROFILES} else 'native-appearance-v1'
        if plan['category'] not in {'Reference2Scene','Reference2Scene-RealPhoto'} or plan['scoring'].get('main_image_method')!=method:
            raise ValueError('Reference profile category/image-method mismatch')
    if policy.get('scoring_profile') in REFERENCE_SCENE_PROFILES:
        from .l2_reference_scoring import validate_visual_plan
        validate_visual_plan(plan,policy['scoring_profile'])
        if policy['scoring_profile'] in {REFERENCE_EMBODIED_PROFILE,*LOCALIZED_PROFILES}:
            from .l2_reference_regions import load_annotation
            plan['_reference_annotation']=load_annotation(root,plan['reference_annotation'])
            if plan['_reference_annotation']['task_id']!=policy['task_id']:
                raise ValueError('Reference annotation task identity mismatch')
        if policy['scoring_profile'] in LOCALIZED_PROFILES:
            from .l2_reference_boxes import load_annotation
            plan['_reference_boxes']=load_annotation(root,plan['reference_boxes'])
            if (plan['_reference_boxes'].get('scoring_profile',REFERENCE_LOCALIZED_PROFILE)!=policy['scoring_profile'] or plan['category']!='Reference2Scene' or plan['_reference_boxes']['task_id']!=policy['task_id']
                    or plan['_reference_boxes']['reference_sha256']!=plan['_reference_annotation']['reference_sha256']):
                raise ValueError('Localized reference task/image mismatch')
    if policy.get('scoring_profile') in {EDIT_STRUCTURE_PROFILE,EDIT_REGION_PROFILE,EDIT_REGION_EXPANSION_PROFILE,EDIT_REGION_REFINED_PROFILE,EDIT_COMPONENT_PROFILE,EDIT_COMPONENT_REFINED_PROFILE}:
        if plan['category']!='SceneEdit' or plan.get('edit_measurement_mode') not in {'geometry','lighting'}:
            raise ValueError('Edit structure profile requires a defined SceneEdit mode')
        if plan['edit_measurement_mode']=='geometry':
            definition=plan.get('edit_structure',{})
            if set(definition)!={'thickness','open_cavity'} or definition['thickness'] is not True or type(definition['open_cavity']) is not bool:
                raise ValueError('Edit structure methods must explicitly require thickness and define cavity scope')
            if policy['scoring_profile'] in {EDIT_REGION_PROFILE,EDIT_REGION_EXPANSION_PROFILE,EDIT_REGION_REFINED_PROFILE,EDIT_COMPONENT_PROFILE,EDIT_COMPONENT_REFINED_PROFILE}:
                groups=plan.get('edit_regions',[]);ids=[];public=(Path(root)/'instruction.md').read_text()
                if not groups:raise ValueError('Regional edit profile requires explicit reference groups')
                for group in groups:
                    names=group.get('objects',[]);ids.append(group['id'])
                    if 'image_box' in group:
                        if policy['scoring_profile'] not in {EDIT_REGION_EXPANSION_PROFILE,EDIT_REGION_REFINED_PROFILE}:
                            raise ValueError('Image boxes require the separately versioned regional expansion')
                        from .l2_edit_regions import validate_image_box
                        validate_image_box(group['image_box'])
                    if policy['scoring_profile'] in {EDIT_REGION_EXPANSION_PROFILE,EDIT_REGION_REFINED_PROFILE} and not set(group)<= {'id','objects','source_quote','image_box'}:
                        raise ValueError('Unknown regional expansion selector field')
                    if (not names or len(set(names))!=len(names) or not set(names)<=set(plan['reference_target']['objects'])
                            or not group.get('source_quote') or group['source_quote'] not in public):
                        raise ValueError('Every region must bind public requirements and private reference selectors')
                if len(ids)!=len(set(ids)):raise ValueError('Duplicate required region ID')
            if policy['scoring_profile'] in {EDIT_COMPONENT_PROFILE,EDIT_COMPONENT_REFINED_PROFILE}:
                components=plan.get('edit_components',{})
                keys={'method','expected_count','source_quote'}
                if policy['scoring_profile']==EDIT_COMPONENT_REFINED_PROFILE:keys.add('maximum_section_gap_degrees')
                if (set(components)!=keys or components['method']!='persistent_circular_sections'
                        or type(components['expected_count']) is not int or components['expected_count']<=0
                        or not components['source_quote'] or components['source_quote'] not in public):
                    raise ValueError('Component count must bind a public requirement and a concrete geometric method')
                if policy['scoring_profile']==EDIT_COMPONENT_REFINED_PROFILE and components['maximum_section_gap_degrees']!=60:
                    raise ValueError('Refined cylindrical count requires the published 60-degree section gap')
    if policy.get('scoring_profile') in {BRIEF_PROFILE,BRIEF_RELIEF_PROFILE,BRIEF_RELATION_PROFILE,BRIEF_ASSEMBLY_PROFILE,BRIEF_ACCESS_PROFILE,BRIEF_PROPERTY_PROFILE,BRIEF_CONTACT_PROFILE,BRIEF_MATERIAL_PROFILE,BRIEF_PROJECTION_PROFILE} and (plan['category']!='Brief2Scene' or plan['scoring']['main_image_weight']!=0):
        raise ValueError('Brief profile must exclude reference-image and text-semantic scoring')
    if policy.get('scoring_profile') in SUPPORTED_PROFILES:
        from .metrics import REGISTRY,_PARAMS
        identities=[]
        for definition in plan['active_checks']:
            identities.append(definition['id'])
            if bool(definition.get('existing_check'))==bool(definition.get('check')):
                raise ValueError('A method must select exactly one existing or custom check')
            if 'check' in definition:
                check=CheckSpec.parse(definition['check'])
                if check.id!=definition['id'] or check.metric not in REGISTRY:
                    raise ValueError('Unknown or mismatched active method check')
                required,optional=_PARAMS[check.metric]
                if required-check.params.keys() or check.params.keys()-required-optional:
                    raise ValueError('Invalid active method parameters')
                if check.metric.startswith('l2_brief_'):l2_brief_numeric.validate(check)
                if check.metric in {'l2_surface_depression','l2_terrain_relief'}:l2_surface_relief.validate(check)
                if check.metric in {'l2_side_layout','l2_course_correspondence'}:l2_brief_relations.validate(check)
                if check.metric=='l2_ball_course':l2_ball_course.validate(check)
                if check.metric in {'l2_attachment_correspondence','l2_entity_part_geometry'}:
                    if policy.get('scoring_profile') not in {BRIEF_ASSEMBLY_PROFILE,BRIEF_ACCESS_PROFILE,BRIEF_PROPERTY_PROFILE,BRIEF_CONTACT_PROFILE,BRIEF_MATERIAL_PROFILE,BRIEF_PROJECTION_PROFILE}:
                        raise ValueError('Assembly checks require the separately versioned Brief assembly profile')
                    l2_brief_assemblies.validate(check)
                if check.metric in {'l2_course_visitor_route','l2_course_obstacle_placement'}:
                    if policy.get('scoring_profile') not in {BRIEF_ACCESS_PROFILE,BRIEF_PROPERTY_PROFILE,BRIEF_CONTACT_PROFILE,BRIEF_MATERIAL_PROFILE,BRIEF_PROJECTION_PROFILE}:
                        raise ValueError('Course access requires the separately versioned Brief access profile')
                    l2_course_access.validate(check)
                if check.metric in {'l2_street_corridors','l2_street_clearance','l2_property_connections'}:
                    if policy.get('scoring_profile') not in {BRIEF_PROPERTY_PROFILE,BRIEF_CONTACT_PROFILE,BRIEF_MATERIAL_PROFILE,BRIEF_PROJECTION_PROFILE}:
                        raise ValueError('Property access requires the separately versioned Brief property profile')
                    l2_property_access.validate(check)
                if check.metric=='l2_support_chain':
                    if policy.get('scoring_profile')!=BRIEF_CONTACT_PROFILE:
                        raise ValueError('Support contact requires its separately versioned Brief profile')
                    l2_support_chain.validate(check)
                if check.metric=='l2_material_support_chain':
                    if policy.get('scoring_profile') not in {BRIEF_MATERIAL_PROFILE,BRIEF_PROJECTION_PROFILE}:
                        raise ValueError('Material support requires the refined Brief contact profile')
                    l2_material_connectivity.validate(check)
                if check.metric=='l2_projected_disjoint':
                    if policy.get('scoring_profile')!=BRIEF_PROJECTION_PROFILE:
                        raise ValueError('Projected separation requires its separately versioned Brief profile')
                    l2_projected_separation.validate(check)
                for key in ('tolerance','expected'):
                    value=check.params.get(key)
                    if value is not None:
                        values=np.asarray(value)
                        if values.dtype.kind not in 'if' or not np.isfinite(values).all() or np.any(values<=0):
                            raise ValueError('Active method '+key+' must be finite and positive')
        if len(set(identities))!=len(identities):raise ValueError('Duplicate active method ID')
    return requested_plan if requested_plan is not None else plan


def compare_main_image(evidence,method=None,annotation=None):
    """No per-object registration, hidden camera, or arbitrary resizing/warping."""
    reference=evidence.get('reference_images',{}).get('main')
    candidate=evidence.get('artifacts',{}).get('main.png')
    if not reference or not candidate:return {'status':'missing','score':0.}
    images=[]
    for item in (reference,candidate):
        path=Path(item['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('Main-view comparison image hash changed')
        with Image.open(path) as image:
            image.load();images.append(np.asarray(image.convert('RGB'),dtype=np.float64)/255.)
    a,b=images
    if a.shape!=b.shape or min(a.shape[:2])<7:
        return {'status':'invalid_size','score':0.,'reference_shape':list(a.shape),'candidate_shape':list(b.shape)}
    if method:
        from .l2_reference_image import appearance_components,METHOD
        if method=='reference-regions-v1':
            from .l2_reference_regions import regional_components
            if not annotation or annotation['reference_sha256']!=reference['sha256']:
                raise ValueError('Main image is not the annotated reference')
            components=regional_components(a,b,annotation)
        elif method==METHOD:components=appearance_components(a,b)
        else:raise ValueError('Unknown main image method')
        ssim=components['ssim_scales'][0]
    else:
        ssim=float(structural_similarity(a,b,data_range=1.,channel_axis=2));components={'score':float(np.clip(ssim,0,1))}
    return {'status':'measured',**components,'ssim_rgb':ssim,
        'mean_absolute_rgb_error':float(np.abs(a-b).mean()),'native_size':[a.shape[1],a.shape[0]],
        'alignment':'Same native pixel grid; no transform fitted using candidate',
        'scope':'Main-view appearance only; not a semantic or hidden 3D correctness claim'}


def score_measured(spec,evidence,policy,plan,*,execution_required=True):
    if policy.get('scoring_profile') == PHOTO_LOCALIZED_PROFILE:
        from .l2_reference_boxes import validate_photo_plan,photo_base_plan,compare_boxes,add_localization
        validate_photo_plan(plan)
        base=score_measured(spec,evidence,{**policy,'scoring_profile':'l2-photo-embodied-v4.0.0'},
            photo_base_plan(plan),execution_required=execution_required)
        localization=compare_boxes(plan['_reference_boxes'],evidence.get('object_detection',{}),
            evidence.get('artifacts',{}).get('main.png',{}).get('sha256'))
        return add_localization(base,localization)
    if policy.get('scoring_profile') in EMBODIED_PROFILES:
        from .l2_embodied_scoring import score
        return score(spec,evidence,policy,plan,execution_required=execution_required)
    scoring_policy=policy
    policy=measurement_policy(policy)
    legacy=(score_l2(spec,evidence,{'image_ssim'}) if scoring_policy.get('scoring_profile') == EDIT_TARGET_PROFILE
            else score_l2(spec,evidence))
    by_id={c['id']:c for m in legacy['modules'].values() for c in m['checks']}
    measurements=[]
    for definition in plan['active_checks']:
        if 'existing_check' in definition:
            result=by_id[definition['existing_check']]
        else:
            check=CheckSpec.parse(definition['check'])
            result={'id':check.id,**evaluate_metric(check,evidence,spec).to_dict()}
        measurements.append({'id':definition['id'],'source':definition['source'],
            'passed':result['passed'],'score':result['score'],'status':result['status'],'details':result['details']})
    if scoring_policy.get('scoring_profile') == EDIT_TARGET_PROFILE:
        from .l2_edit_target_scoring import score_edit_target
        return score_edit_target(legacy,measurements,evidence,scoring_policy,plan,execution_required=execution_required)
    if plan['category']=='SceneEdit':
        if plan.get('edit_measurement_mode')=='lighting':
            from .l2_edit_lighting import lighting_improvement
            target=lighting_improvement(evidence)
            target_id='lighting_restoration'
        else:
            target=evidence.get('edit_target',{});target_id='visible_edit_target'
        measurements.append({'id':target_id,'source':'solution/EVALUATION.md target restoration',
            'passed':target.get('passed') is True,'score':target.get('score',0.),
            'status':target.get('status','not_measurable'),'details':target})
        if policy.get('scoring_profile') in {EDIT_STRUCTURE_PROFILE,EDIT_REGION_PROFILE,EDIT_REGION_EXPANSION_PROFILE,EDIT_REGION_REFINED_PROFILE,EDIT_COMPONENT_PROFILE,EDIT_COMPONENT_REFINED_PROFILE} and plan['edit_measurement_mode']=='geometry':
            names=['visible_target_thickness']
            if plan['edit_structure']['open_cavity']:names.append('open_target_cavity')
            for name in names:
                result=evidence.get('edit_structure',{}).get(name,{})
                measurements.append({'id':name,'source':'solution/EVALUATION.md structural geometry',
                    'passed':result.get('passed') is True,'score':result.get('score',0.),
                    'status':result.get('status','not_measurable'),'details':result})
            if policy['scoring_profile'] in {EDIT_REGION_PROFILE,EDIT_REGION_EXPANSION_PROFILE,EDIT_REGION_REFINED_PROFILE,EDIT_COMPONENT_PROFILE,EDIT_COMPONENT_REFINED_PROFILE}:
                result=evidence.get('edit_regions',{})
                measurements.append({'id':'required_visible_regions','source':'Public task required visible regions',
                    'passed':result.get('passed') is True,'score':result.get('score',0.),
                    'status':result.get('status','not_measurable'),'details':result})
            if policy['scoring_profile'] in {EDIT_COMPONENT_PROFILE,EDIT_COMPONENT_REFINED_PROFILE}:
                result=evidence.get('edit_components',{})
                measurements.append({'id':'cylindrical_container_count','source':'Public count checked on complete added geometry',
                    'passed':result.get('passed') is True,'score':result.get('score',0.),
                    'status':result.get('status','not_measurable'),'details':result})
    texture=evidence.get('scene',{}).get('procedural_materials',{})
    measurements.append({'id':'procedural_materials','source':'user override 2026-10-03',
        'passed':texture.get('passed') is True,'score':float(texture.get('passed') is True),
        'status':'measured' if texture else 'not_measurable','details':texture})
    if policy.get('scoring_profile') in REFERENCE_SCENE_PROFILES:
        from .l2_reference_scoring import score_reference_visual
        image=compare_main_image(evidence,plan['scoring']['main_image_method'],plan.get('_reference_annotation'))
        physics=None
        if policy['scoring_profile'] in {REFERENCE_EMBODIED_PROFILE,*LOCALIZED_PROFILES}:
            from .l2_physical import physical_plausibility
            physics=physical_plausibility(evidence,plan['physics'])
        if policy['scoring_profile'] in LOCALIZED_PROFILES:
            from .l2_reference_boxes import add_localization,compare_boxes
            base=score_reference_visual(legacy,measurements,image,{**policy,'scoring_profile':REFERENCE_EMBODIED_PROFILE},
                {**plan,'scoring':{**plan['scoring'],'main_image_weight':.8}},execution_required=execution_required,physics=physics)
            localization=compare_boxes(plan['_reference_boxes'],evidence.get('object_detection',{}),
                evidence.get('artifacts',{}).get('main.png',{}).get('sha256'))
            return add_localization(base,localization)
        return score_reference_visual(legacy,measurements,image,policy,plan,execution_required=execution_required,physics=physics)
    data_pass=all(m['passed'] for m in measurements)
    data_score=sum(m['score'] for m in measurements)/len(measurements)
    brief=plan['category']=='Brief2Scene'
    method=plan['scoring'].get('main_image_method')
    image={'status':'not_in_scope','score':None} if brief else compare_main_image(evidence,method) if method else compare_main_image(evidence)
    if scoring_policy.get('scoring_profile') in QUALITY_PROFILES:
        if not brief:
            passed=evidence.get('case',{}).get('preservation') is True
            measurements.append({'id':'edit_preservation','source':'Public edit preservation requirements',
                'passed':passed,'score':float(passed),'status':'measured' if 'preservation' in evidence.get('case',{}) else 'not_measurable',
                'details':evidence.get('case',{}).get('preservation_details',{})})
        from .l2_quality_scoring import score_content_quality
        return score_content_quality(legacy,measurements,image,scoring_policy,plan,execution_required=execution_required)
    image_weight=plan['scoring']['main_image_weight']
    quality=(1-image_weight)*data_score+image_weight*(image['score'] or 0.)
    if not brief:data_pass &= image['status']=='measured'
    gates={name:legacy['gates'][name] for name in ('execution','artifacts','real_geometry','integrity','all_seeds','all_seed_quality')}
    gates['measured_requirements']={'passed':bool(data_pass),'failed':[m['id'] for m in measurements if not m['passed']]}
    if not execution_required:
        eligible=bool(data_pass and gates['artifacts']['passed'] and gates['real_geometry']['passed'])
    else:
        eligible=all(g['passed'] for g in gates.values())
    deferred=[r['id'] for r in policy['requirements'] if r['implementation']!='complete']
    legacy.update(gates=gates,case_pass=eligible,G=int(eligible),S_core=quality if eligible else 0.,
        S_diagnostic=quality,S_level=quality,task_quality_pass=bool(data_pass),
        method_version=policy.get('scoring_profile',PROFILE),score_scope='Measured numerical/appearance requirements; semantic completion is not evaluated',
        measurements=measurements,main_image_comparison=image,
        score_components={'data':data_score,'main_image':image['score'],'main_image_weight':image_weight},
        text_semantics_evaluated=False,vit_used=False,deferred_requirements=deferred,
        calibration_status=plan['scoring']['weights_status'],formal_score_eligible=False,
        evaluation_source_sha256=plan['sources']['solution/EVALUATION.md'])
    return legacy
