import copy
import pytest
from harness.L3.Suite.aggregate_v2 import observable_reference

def sample():
    return {'checklist_sha256':'fixed','objects':[{'id':'cabinet','weight':100,'features':[{'id':'shape'},{'id':'capacity'}],
        'values':{'shape':.75,'capacity':0},'score':.375}], 'environment_values':{'layout':.5}}

def test_reference_only_mask_excludes_function_for_every_candidate_without_changing_grades():
    ref=sample();original=copy.deepcopy(ref)
    mask={'checklist_sha256':'fixed','criteria':{'object/cabinet/shape':{'eligible':True},
        'object/cabinet/capacity':{'eligible':False},'environment/layout':{'eligible':True}}}
    first=observable_reference(ref,mask)
    assert first['objects_score']==.75 and first['environment_score']==.5
    assert ref==original
    ref['objects'][0]['values']['shape']=.25
    assert observable_reference(ref,mask)['objects_score']==.25

def test_eligibility_for_different_reference_is_not_reusable():
    with pytest.raises(ValueError,match='mismatch'):observable_reference(sample(),{'checklist_sha256':'other'})
