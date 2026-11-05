import copy
import json
from pathlib import Path

import numpy as np
import pytest

from orchestrator.tasks import TASKS,inventory,load_task
from src.evaluator.l2_case import load_case
from src.evaluator.l2_case_audit import audit_case
from src.evaluator.l2_case_metrics import camera_pair
from src.evaluator.spec import CheckSpec

CASES=[r['task_id'] for r in inventory(level=2) if r['harness_status'] in {'mvp','implemented'}]


def test_only_upstream_changed_slots_use_refresh_profiles():
    refreshed={identity for identity in CASES if '-refresh-' in load_case(TASKS/identity)[2]['scoring_profile']}
    expected={f'L2/Reference2Scene/task_L2_Reference2Scene-{n:03d}' for n in (2,3,4,5,6,7,9,10)}
    expected|={f'L2/Reference2Scene-RealPhoto/task_L2_Reference2Scene-RealPhoto_{n:03d}' for n in range(1,10)}
    assert refreshed==expected


@pytest.mark.parametrize('task_id',CASES)
def test_every_case_binds_its_own_public_contract(task_id):
    task=load_task(task_id)
    manifest,spec,policy=load_case(task.root)
    assert manifest['harness_status'] in {'mvp','implemented'}
    assert policy['task_id']==task_id and policy['spec_sha256']==spec.digest
    assert set(spec.required_artifacts)==set(task.artifacts)
    assert len(spec.seeds)==3
    assert 'alternate' not in spec.reference_images
    assert not spec.reference_scene  # Unpublished source scene is not a reconstruction target.
    assert all('solution/' not in path for path in spec.reference_images.values())
    text=(task.root/'instruction.md').read_text()
    assert all(r['source_quote'] in text for r in policy['requirements'])
    if '-refresh-' in policy['scoring_profile']:
        rubric=json.loads((task.root/'harness/vlm_spec.json').read_text())
        assert len([c for c in rubric['checks'] if c['id'].startswith('reference_feature_')])==5
        assert rubric['localization']['reference_sha256'] in policy['public_reference_sha256']
    else:
        assert any(r['implementation']=='manual' for r in policy['requirements'])
    assert not (task.root/'harness/harness.toml').exists()
    entry=(task.root/'harness/evaluate.py').read_text()
    assert not any(word in entry for word in ('subprocess','docker','retry','generate('))


def test_special_camera_scale_and_edit_policies_are_case_specific():
    cases={task_id:load_case(TASKS/task_id) for task_id in CASES}
    def case(category,number):
        return next(v for k,v in cases.items() if f'L2/{category}/' in k and k.endswith(f'{number:03d}'))
    assert case('Brief2Scene',1)[2]['camera_policy']['degrees']==25
    assert case('Brief2Scene',8)[2]['camera_policy']['mode']=='free'
    assert case('Brief2Scene',9)[2]['camera_policy']['delta_m']==2
    assert case('Brief2Scene',10)[2]['camera_policy']['mode']=='different_azimuth'
    assert case('Reference2Scene',5)[2]['native_resolution']==[1600,900]
    assert case('Reference2Scene',10)[2]['render_settings']['view_transform']=='AgX'
    assert case('Reference2Scene-RealPhoto',1)[2]['native_resolution']==[1439,1079]
    assert case('Reference2Scene-RealPhoto',2)[2]['native_resolution']==[960,720]
    assert case('Reference2Scene-RealPhoto',9)[2]['native_resolution']==[1280,960]
    for n in (1,2):
        assert 'novel.png' not in case('Reference2Scene-RealPhoto',n)[1].required_artifacts
        assert case('Reference2Scene-RealPhoto',n)[1].reference_images=={'main':'environment/input/reference.png'}
    assert case('SceneEdit',3)[2]['edit_policy']=={'mode':'lighting','light_color_energy':True,'world_background_strength':False}
    assert case('SceneEdit',5)[2]['edit_policy']['world_background_strength']
    assert case('SceneEdit',6)[2]['edit_policy']['mode']=='geometry'
    for n in range(1,11):
        assert case('SceneEdit',n)[1].baseline_scene=='environment/input/initial.blend'
        assert case('SceneEdit',n)[2]['native_resolution'] is None


def fixture():
    mesh={'type':'MESH','parent':None,'location':[0,0,0],'rotation':[0,0,0],'scale':[1,1,1],
          'visible_render':True,'geometry_sha256':'g','evaluated_geometry_sha256':'e','data_sha256':'d',
          'material_sha256':['m'],'constraints_sha256':'c'}
    light={**mesh,'type':'LIGHT','data_sha256':'light-before'}
    scene={'has_real_geometry':True,'billboard_suspects':[],'audit':{k:[] for k in ('drivers','autoexec_texts','script_nodes','compositor_images','linked_libraries','external_resources')},
           'objects':{'Mesh':mesh,'Light':light},'world_sha256':'world','render':{},'render_settings_sha256':'settings',
           'saved_frame':1,'light_data':{'Light':{'settings':{'energy':10,'color':[1,1,1],'type':'AREA','shape':'RECTANGLE','size':1},'nodes':None}},
           'world_data':{'properties':{},'nodes':{'nodes':{'Background':{'type':'ShaderNodeBackground',
               'inputs':[['Color',[1,1,1,1]],['Strength',.1]]}},'links':[]}}}
    return {'scene':scene}


def test_lighting_permissions_do_not_allow_geometry_positions_or_new_lights():
    baseline=fixture();facts=copy.deepcopy(baseline)
    facts['scene']['light_data']['Light']['settings']['energy']=100
    facts['scene']['objects']['Light']['data_sha256']='light-after'
    policy={'edit_policy':{'mode':'lighting','light_color_energy':True,'world_background_strength':False}}
    assert audit_case(facts,baseline,policy)['passed']
    facts['scene']['objects']['Light']['location']=[1,0,0]
    assert not audit_case(facts,baseline,policy)['passed']
    facts=copy.deepcopy(baseline);facts['scene']['light_data']['Light']['settings']['size']=2
    assert not audit_case(facts,baseline,policy)['passed']
    facts=copy.deepcopy(baseline);facts['scene']['objects']['extra']=facts['scene']['objects']['Light']
    assert not audit_case(facts,baseline,policy)['passed']


def test_only_snow_edit_allows_world_strength_and_not_texture_or_links():
    before=fixture();after=copy.deepcopy(before)
    after['scene']['world_sha256']='changed'
    after['scene']['world_data']['nodes']['nodes']['Background']['inputs'][1][1]=1
    policy={'edit_policy':{'mode':'lighting','light_color_energy':True,'world_background_strength':True}}
    assert audit_case(after,before,policy)['passed']
    policy['edit_policy']['world_background_strength']=False
    assert not audit_case(after,before,policy)['passed']
    policy['edit_policy']['world_background_strength']=True
    after['scene']['world_data']['nodes']['links'].append(['changed'])
    assert not audit_case(after,before,policy)['passed']


def test_camera_translation_does_not_accept_wrong_orthographic_scale():
    a={'type':'ORTHO','location':[0,0,0],'lens':50,'ortho_scale':10,
       'basis_x':[1,0,0],'basis_y':[0,1,0],'basis_z':[0,0,1]}
    b={**a,'location':[.3,0,0]}
    check=CheckSpec.parse({'id':'camera','metric':'l2_case_camera_pair','group':'g',
                          'params':{'mode':'local_translation','delta_m':.3,'tolerance':.003}})
    evidence={'scene':{'cameras':{'__main':a,'__alternate':b}}}
    assert camera_pair(check,evidence,None)[0]==1
    b['ortho_scale']=12
    assert camera_pair(check,evidence,None)[0]==0


def test_inherited_driver_needs_full_unchanged_signature():
    before=fixture();before['scene']['audit']['drivers']=['rig:pose.bones']
    before['scene']['driver_signatures']={'Rig:path:0':'full-expression-variables-and-targets'}
    after=copy.deepcopy(before)
    assert audit_case(after,before,{'edit_policy':{'mode':'geometry'}})['passed']
    after['scene']['driver_signatures']['Rig:path:0']='changed-expression'
    assert not audit_case(after,before,{'edit_policy':{'mode':'geometry'}})['passed']
    after=copy.deepcopy(before);after['scene']['audit']['drivers'].append('new:driver')
    assert not audit_case(after,before,{'edit_policy':{'mode':'geometry'}})['passed']
    assert not audit_case(before,None,{})['passed']
