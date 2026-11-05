import copy
from harness.L3.Suite.binding_hints import normalize_bindings

def test_exact_overview_and_entity_aliases_preserve_candidate():
    original={'entities':[{'entity_key':'pump','approach_cm':[1,2,3]}],
              'overview_views':[{'name':'overview','position_cm':[4,5,6],'target_cm':[0,0,0]}]}
    before=copy.deepcopy(original)
    normalized,audit=normalize_bindings(original)
    assert original==before
    assert normalized['entities']['pump']['approach_cm']==[1,2,3]
    assert normalized['views']['overview']['look_cm']==[0,0,0]

def test_camera_field_aliases_and_conflicts():
    row={'camera_cm':[1,2,3],'target_cm':[0,0,0],'fov_deg':80}
    normalized,_=normalize_bindings({'views':{'a':row}})
    assert normalized['views']['a']['position_cm']==[1,2,3]
    assert normalized['views']['a']['horizontal_fov_deg']==80
    for key,value in [('position_cm',[9,9,9]),('horizontal_fov_deg',70)]:
        normalized,audit=normalize_bindings({'views':{'a':{**row,key:value}}})
        assert normalized['views']=={}
        assert any('conflicting' in x['reason'] for x in audit['rejected'])

def test_explicit_views_not_replaced_by_overview():
    view={'position_cm':[1,2,3],'look_cm':[0,0,0]}
    normalized,_=normalize_bindings({'views':{'a':view},'overview_views':[{'name':'other',**view}]})
    assert list(normalized['views'])==['a']

def test_conflicting_entity_ids_rejected():
    normalized,audit=normalize_bindings({'entities':[{'id':'a','entity_key':'b','approach_cm':[1,2,3]}]})
    assert normalized['entities']=={}

def test_descriptive_golden_path_is_translated_without_overriding_workflow():
    from harness.L3.Suite.route_translation import needs_translation
    assert needs_translation({'golden_path_workflow':{'steps':['Walk to the pump']}})
    assert not needs_translation({'workflow':[],'golden_path_workflow':{'steps':['Ignored alternative']}})
