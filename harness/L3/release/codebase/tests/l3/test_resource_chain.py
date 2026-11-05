import json
from harness.L3.MinecraftVillage.resource_chain import plan, diagnose, TARGETS, EXPECTED
from harness.L3.MinecraftVillage.inventory import ITEMS

def test_chain_uses_gameplay_actions_and_explicit_local_placements():
    bindings={'entities':{t:{'approach_cm':[0,0,85],'look_cm':[100,0,100]} for t in TARGETS}}
    p=plan(bindings)
    assert p['kind']=='local' and p['continuous_walk'] is False
    assert all(s['op'] not in {'invoke','grant','set_state'} for s in p['steps'])
    actions=[(s['target'],s['action']) for s in p['steps'] if s['op']=='interact']
    assert actions.index(('house01.chest','take'))<actions.index(('farm.crop01','plant'))<actions.index(('smithy01.furnace','process'))
    assert len([s for s in p['steps'] if s['op']=='fixture'])==6

def test_inventory_is_observed_and_emissive_effect_is_not_falsely_rejected(tmp_path):
    (tmp_path/'completed.json').write_text('{"completed":true}')
    for name in set(EXPECTED)|{'crop_before','before_processing','furnace_active'}:
        entities=[{'id':t,'components':[],'lights':[]} for t in TARGETS]
        crop=entities[1]
        if name!='crop_harvested':
            crop['components']=[{'name':'Plant','mesh':'mature' if name=='crop_before' else 'young','visible':True,'instances':1}]
        values=EXPECTED.get(name,[0,0,0,0])
        if name=='seed_taken':values=[2,0,0,0]
        frame={'protocol':'ue5-observer-v1','time':0,'entities':entities,
               'trusted_inventory':[{'counts':dict(zip(ITEMS,values))}]}
        (tmp_path/(name+'.json')).write_text(json.dumps(frame))
    result=diagnose(tmp_path)
    assert result['inventory']['checks']['seed_taken']['passed'] is False
    assert result['inventory']['failed']==1
    assert result['geometry_checks']['plant_restores_visible_crop'] is True
    assert result['geometry_checks']['processing_light_observed_for_one_second'] is None
    assert result['continuous_walk_verified'] is False
    assert result['formal_score'] is None
