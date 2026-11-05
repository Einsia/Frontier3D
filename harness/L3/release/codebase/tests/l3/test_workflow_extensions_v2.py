from harness.L3.Suite.plans import workflow_plan
from harness.L3.Suite.aggregate_v2 import applicable_motion

def test_real_registered_extensions_are_executed_without_accepting_claims():
    contract={'entities':[{'id':'washer','actions':['start']}]}
    bindings={'entities':{'washer':{}},'workflow':[
        {'op':'invoke','target':'washer','action':'take_out','argument':'shirt'},
        {'op':'invoke','target':'card.dock','action':'return'},
        {'op':'fixture','position_cm':[0,0,0]},
        {'op':'invoke','target':'unregistered','action':'anything'}]}
    plan,meta=workflow_plan(bindings,contract,observed_ids=['card.dock'])
    actions=[s for s in plan['steps'] if s['op']=='invoke']
    assert [s['target'] for s in actions]==['washer','card.dock']
    assert len(meta['rejected'])==2
    assert not any(s['op']=='fixture' for s in plan['steps'])

def test_no_motion_is_valid_for_electrical_switch_but_not_door():
    row={'moving_components':[],'overlaps':[],'unresolved':[],'sampled_clear':None}
    result=applicable_motion({'motion':{'targets':{'switch':row,'door':row}}},
        {'switch':'switch','door':'door'},{'switch':['on','off'],'door':['open','close']})
    assert 'switch' in result['not_applicable']
    assert result['targets']['door']==0
    assert result['score']==0
