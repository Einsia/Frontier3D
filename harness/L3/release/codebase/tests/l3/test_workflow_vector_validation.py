import copy
import pytest
from harness.L3.Suite.plans import workflow_plan

@pytest.mark.parametrize('op,key', [('walk_to','target_cm'),('look','target_cm'),('move','direction')])
@pytest.mark.parametrize('value', [None,[],[1,2],[1,2,3,4],[1,True,3],[1,float('nan'),3],[1,float('inf'),3],['1',2,3]])
def test_invalid_vector_rejected_without_losing_other_steps(op,key,value):
    bindings={'workflow':[{'op':op,key:value},{'op':'wait','seconds':1}]}
    plan,meta=workflow_plan(bindings,{'entities':[]})
    assert len(meta['rejected'])==1 and meta['rejected'][0]['index']==0
    assert [s['op'] for s in plan['steps']]==['snapshot','wait','snapshot']

def test_exact_position_hint_is_copied_without_mutating_submission():
    bindings={'workflow':[{'op':'walk_to','position_cm':[1,2,3]}]}
    before=copy.deepcopy(bindings)
    plan,meta=workflow_plan(bindings,{'entities':[]})
    assert not meta['rejected'] and meta['steps'][0]['step']['target_cm']==[1,2,3]
    assert meta['steps'][0]['submitted_step']==before['workflow'][0]
    assert bindings==before

@pytest.mark.parametrize('value',[True,-1,31,float('nan'),'3'])
def test_invalid_duration_rejected(value):
    _,meta=workflow_plan({'workflow':[{'op':'wait','seconds':value}]},{'entities':[]})
    assert len(meta['rejected'])==1

def test_valid_vectors_and_defaults_preserved():
    steps=[{'op':'walk_to','target_cm':[1,2,3]},{'op':'look','target_cm':[4,5,6]},{'op':'move','direction':[1,0,0],'seconds':2}]
    before=copy.deepcopy(steps)
    plan,meta=workflow_plan({'workflow':steps},{'entities':[]})
    assert not meta['rejected']
    for original,row in zip(steps,meta['steps']):
        assert all(row['step'][k]==v for k,v in original.items())
    assert steps==before

@pytest.mark.parametrize('step',[
    {'op':'walk_to','position_cm':[1,2]},
    {'op':'walk_to','position_cm':[1,2,3],'target':[4,5,6]},
    {'op':'walk_to','waypoint':'not-a-coordinate'},
    {'op':'walk_to','target_cm':[],'position_cm':[1,2,3]}])
def test_ambiguous_or_incomplete_hint_is_not_invented(step):
    _,meta=workflow_plan({'workflow':[step]},{'entities':[]})
    assert len(meta['rejected'])==1

def test_target_array_is_an_exact_destination_alias():
    _,meta=workflow_plan({'workflow':[{'op':'walk_to','target':[1,2,3]}]},{'entities':[]})
    assert meta['steps'][0]['step']['target_cm']==[1,2,3]

def test_exact_entity_id_alias_still_requires_registered_id():
    contract={'entities':[{'id':'bag.01'}]}
    _,meta=workflow_plan({'workflow':[{'op':'interact','entity_id':'bag.01','action':'pick_up'},{'op':'interact','entity_id':'unknown','action':'pick_up'}]},contract)
    assert meta['steps'][0]['step']['target']=='bag.01'
    assert len(meta['rejected'])==1

@pytest.mark.parametrize('label',['name','id'])
def test_named_waypoint_resolves_only_exact_submitted_coordinates(label):
    b={'workflow':{'waypoints':[{label:'gate','position_cm':[12,34,56]}],
                   'steps':[{'op':'walk_to','waypoint':'gate','seconds':8}]}}
    before=copy.deepcopy(b)
    _,meta=workflow_plan(b,{'entities':[]})
    assert not meta['rejected']
    assert meta['steps'][0]['step']['target_cm']==[12,34,56]
    assert meta['steps'][0]['step']['seconds']==8
    assert b==before

@pytest.mark.parametrize('points',[
    [{'name':'x','position_cm':[1,2,3]},{'name':'x','position_cm':[3,2,1]}],
    [{'name':'x','position_cm':[1,2]}],
    [{'name':'x','position_cm':[1,2,float('inf')]}],
    []])
def test_bad_or_unknown_waypoint_is_not_repaired(points):
    _,meta=workflow_plan({'workflow':{'waypoints':points,'steps':[{'op':'walk_to','waypoint':'x'}]}},{'entities':[]})
    assert len(meta['rejected'])==1

def test_conflicting_explicit_and_named_destination_is_rejected():
    _,meta=workflow_plan({'workflow':{'waypoints':[{'id':'x','position_cm':[1,2,3]}],
        'steps':[{'op':'walk_to','waypoint':'x','position_cm':[4,5,6]}]}},{'entities':[]})
    assert len(meta['rejected'])==1

@pytest.mark.parametrize('field',['entity','entity_id'])
def test_exact_entity_alias_preserves_action_argument_and_registration(field):
    b={'workflow':[{'op':'interact',field:'bag.01','action':'put_into','argument':'box.02'},
                   {'op':'interact',field:'unknown','action':'pick_up'}]}
    before=copy.deepcopy(b)
    _,meta=workflow_plan(b,{'entities':[{'id':'bag.01'}]})
    assert b==before
    assert meta['steps'][0]['step']['target']=='bag.01'
    assert meta['steps'][0]['step']['argument']=='box.02'
    assert len(meta['rejected'])==1

def test_conflicting_entity_aliases_are_rejected():
    _,meta=workflow_plan({'workflow':[{'op':'interact','entity_id':'bag.01','entity':'bag.02','action':'pick_up'}]},
                        {'entities':[{'id':'bag.01'},{'id':'bag.02'}]})
    assert not meta['steps']
    assert len(meta['rejected'])==1
