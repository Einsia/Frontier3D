from harness.L3.MinecraftVillage.geometry_routes import retarget_removed_block


def test_removed_block_aims_at_surviving_geometry_without_mutating_evidence():
    plan={'steps':[{'op':'interact','name':'action_1'}, {'op':'interact','name':'action_2'}, {'op':'interact','name':'action_3'}]}
    snapshot={'entities':[{'id':'edit.block01','candidate_state':{'removed':'false'},'components':[
        {'name':'arbitrary_large_hidden','visible':False,'collision':False,'bounds_center_cm':[10,20,50],'bounds_extent_cm':[50,50,50]},
        {'name':'arbitrary_survivor','visible':True,'collision':True,'bounds_center_cm':[10,20,1],'bounds_extent_cm':[45,45,1]}]}]}
    revised,audit=retarget_removed_block(plan,snapshot,'edit.block01')
    assert audit['retargeted'] and audit['look_cm']==[10,20,1]
    assert [s['name'] for s in revised['steps']]==['action_1','action_2_retarget','action_2','action_3_retarget','action_3']
    assert len(plan['steps'])==3
    assert snapshot['entities'][0]['components'][0]['visible'] is False


def test_removed_block_with_no_target_surface_is_not_given_an_invented_anchor():
    plan={'steps':[{'op':'interact','name':'action_3'}]}
    snapshot={'entities':[{'id':'edit.block01','components':[{'visible':False,'collision':False}]}]}
    revised,audit=retarget_removed_block(plan,snapshot,'edit.block01')
    assert revised==plan and not audit['retargeted']
