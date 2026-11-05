"""Per-case edit permissions over independently measured baseline/output facts."""
import copy

from harness.L2.audit import scene_audit
from .l2_case_compare import align_evaluated_roundoff
from .l2_quality_scoring import QUALITY_PROFILES


def separate_content_failures(result, policy):
    """Only explicitly identified edit-quality failures can leave the integrity gate."""
    from .l2_embodied_scoring import base_policy
    if base_policy(policy).get('scoring_profile') not in QUALITY_PROFILES:
        return result
    content_checks={'preservation','light_inventory','light_preservation',
        'world_except_background_strength','saved_frame','lighting_edit_object_inventory'}
    missing_evidence={'missing_geometry_evidence','missing_render_settings'}
    content=[failure for failure in result['failures']
        if failure['check'] in content_checks and failure.get('field') not in missing_evidence]
    result['content_failures']=content
    result['content_passed']=not content
    result['failures']=[failure for failure in result['failures'] if failure not in content]
    result['passed']=not result['failures']
    result['eligibility_policy']='system_validity_content_quality'
    return result


def without_light_edits(value):
    value=copy.deepcopy(value)
    for field in ('color','energy'):
        value.get('settings',{}).pop(field,None)
    # Only the light properties are allowed here; node edits stay visible.
    return value


def without_world_strength(value):
    value=copy.deepcopy(value)
    tree=value.get('nodes') if value else None
    if tree:
        for node in tree['nodes'].values():
            if node['type']=='ShaderNodeBackground':
                for item in node['inputs']:
                    if item[0]=='Strength':item[1]='<allowed strength>'
    return value


def audit_case(facts,baseline,policy):
    edit=policy.get('edit_policy')
    if baseline is None:
        result=scene_audit(facts,None,edit=bool(edit))
        from .l2_refresh_scoring import PROFILES
        if policy.get('automatic_profile',policy.get('scoring_profile')) in PROFILES:
            # Local texture planes (posters, tiles, wall patches) are explicitly
            # permitted in the refreshed package. The old two-polygon heuristic
            # is review evidence, not proof of a photographic scene substitute.
            result['texture_plane_review']=[r for r in result['failures'] if r['check']=='billboard_review']
            result['failures']=[r for r in result['failures'] if r['check']!='billboard_review']
            observed=facts['scene'].get('used_packed_image_sha256')
            if observed is None:
                result['failures'].append({'check':'image_dependency_inspection_missing'})
            elif set(observed)&set(policy['public_reference_sha256']):
                result['failures'].append({'check':'complete_reference_used_as_texture',
                    'sha256':sorted(set(observed)&set(policy['public_reference_sha256']))})
            result['passed']=not result['failures']
            result['limitations'].append('Packed local material textures are allowed. Exact whole-reference image reuse is rejected; transformed photographic substitutes still require visual geometry review.')
        return result
    before,after=baseline['scene'],facts['scene']
    allowed=edit or {}
    candidate=copy.deepcopy(facts)
    adjusted,roundoff=align_evaluated_roundoff(candidate['scene'],before,directory=facts.get('geometry_root'),reference_directory=baseline.get('geometry_root'))
    candidate['scene']=adjusted
    failures=[]
    inherited_drivers = before.get('audit',{}).get('drivers',[])
    if inherited_drivers:
        if (inherited_drivers == after.get('audit',{}).get('drivers')
                and before.get('driver_signatures')
                and before['driver_signatures'] == after.get('driver_signatures')):
            adjusted['audit']['drivers']=[]
        else:
            failures.append({'check':'inherited_driver_preservation'})
    old_lights={n for n,o in before['objects'].items() if o['type']=='LIGHT'}
    new_lights={n for n,o in after['objects'].items() if o['type']=='LIGHT'}
    if allowed.get('mode') in {'lighting','geometry'} and new_lights!=old_lights:
        failures.append({'check':'light_inventory','before':sorted(old_lights),'after':sorted(new_lights)})
    if allowed.get('light_color_energy'):
        for name in old_lights & new_lights:
            a,b=before.get('light_data',{}).get(name),after.get('light_data',{}).get(name)
            if a is None or b is None or without_light_edits(a)!=without_light_edits(b):
                failures.append({'check':'light_preservation','object':name})
            else:
                adjusted['objects'][name]['data_sha256']=before['objects'][name].get('data_sha256')
    if allowed.get('world_background_strength'):
        if without_world_strength(before.get('world_data')) != without_world_strength(after.get('world_data')):
            failures.append({'check':'world_except_background_strength'})
        else:
            adjusted['world_sha256']=before['world_sha256']
    result=scene_audit(candidate,baseline,edit=True)
    if before.get('saved_frame')!=after.get('saved_frame'):
        failures.append({'check':'saved_frame'})
    if allowed.get('mode')=='lighting':
        before_geometry={n for n,o in before['objects'].items() if o['type'] not in {'CAMERA'}}
        after_geometry={n for n,o in after['objects'].items() if o['type'] not in {'CAMERA'}}
        if before_geometry!=after_geometry:
            failures.append({'check':'lighting_edit_object_inventory'})
    if allowed.get('mode')=='geometry':
        additions=[n for n,o in after['objects'].items() if n not in before['objects'] and o['type']=='MESH' and o.get('visible_render') and o.get('faces',0)>0]
        result['target_geometry_additions']=additions
        # Target presence is a quality requirement; preservation/integrity alone may pass an unchanged scene.
    result['failures'].extend(failures)
    result['passed']=not result['failures']
    result['evaluated_roundoff']=roundoff
    result['edit_policy']=allowed
    result['inherited_drivers']=inherited_drivers
    return separate_content_failures(result,policy)
