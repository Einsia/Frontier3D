import json
from pathlib import Path
import numpy as np
from harness.L3.MinecraftVillage.algorithm_geometry import unit_cube
from harness.L3.MinecraftVillage.scene_geometry import Scene,motion_measure
from harness.L3.Suite.physical_v2 import grounding,asset_geometry,penetration

def item(actor,component,center,size):
    return {'actor':actor,'component':component,'instance':0,'mesh':'cube','origin_cm':center,
        'axis_x':[size[0],0,0],'axis_y':[0,size[1],0],'axis_z':[0,0,size[2]],'visible':True}
def scene(items):return Scene({'instances':items,'meshes':{'cube':unit_cube()}})
def episodes(tmp_path,wall=False):
    folder=tmp_path/'door';folder.mkdir()
    def state(y):
        return {'time':y+1,'entities':[{'id':'door','components':[
            {'name':'leaf','position_cm':[0,y,100],'axis_x':[100,0,0],'axis_y':[0,10,0],'axis_z':[0,0,200],'visible':True},
            {'name':'handle','position_cm':[0,y,100],'axis_x':[10,0,0],'axis_y':[0,20,0],'axis_z':[0,0,10],'visible':True}]}]}
    (folder/'initial.json').write_text(json.dumps(state(0)))
    for i,y in enumerate([0,25,50]):(folder/f'trajectory_{i}.json').write_text(json.dumps(state(y)))
    rows=[item('door','leaf',[0,0,100],[100,10,200]),item('door','handle',[0,0,100],[10,20,10])]
    if wall:rows.append(item('wall','body',[0,50,100],[100,20,200]))
    return scene(rows)

def test_attached_moving_parts_are_not_self_collision(tmp_path):
    s=episodes(tmp_path)
    old=motion_measure(s,tmp_path,targets=['door'],stop_on_failure=True)['targets']['door']
    new=motion_measure(s,tmp_path,targets=['door'],stop_on_failure=True,rigid_assemblies=True)['targets']['door']
    assert old['sampled_clear'] is False
    assert new['sampled_clear'] is True
    assert new['rigid_internal_pairs_omitted']>0

def test_real_motion_into_external_wall_still_fails(tmp_path):
    s=episodes(tmp_path,wall=True)
    result=motion_measure(s,tmp_path,targets=['door'],stop_on_failure=True,rigid_assemblies=True)['targets']['door']
    assert result['sampled_clear'] is False
    assert result['overlaps'][0]['obstacle'][0]=='wall'

def test_ground_contact_containment_and_float_are_distinguished():
    s=scene([item('ground','g',[0,0,-10],[1000,1000,20]),item('body','b',[0,0,50],[100,100,100]),
             item('inset','i',[0,0,50],[10,10,10]),item('floating','f',[300,0,180],[100,100,100])])
    tri,areas=asset_geometry(s);result=grounding(s,tri,areas,{})
    assert {r['instance'][0] for r in result['unsupported_assets']}=={'floating'}
    assert result['entities']['inset']==1
    assert result['entities']['body']==1

def test_small_overlap_does_not_zero_whole_object(tmp_path):
    s=scene([item('a','a',[0,0,0],[100,100,100]),item('b','b',[90,0,0],[100,100,100])])
    tri,areas=asset_geometry(s)
    raw={'overlaps':[{'left':['a','a',0],'right':['b','b',0],'violates':True,'depth_cm':10}]}
    result=penetration(s,raw,areas,{},tmp_path)
    assert abs(result['score']-.9)<1e-8
    assert len(result['violations'])==1

def test_repeated_small_pavers_do_not_replace_ground_datum():
    s=scene([item('ground','g',[0,0,0],[9000,8500,36]),
        *[item('paver'+str(i),'p',[0,0,0],[172,172,5]) for i in range(20)],
        item('gate','g',[0,0,0],[570,42,650])])
    tri,areas=asset_geometry(s);result=grounding(s,tri,areas,{'gate':'door'})
    assert result['roots']==[['ground','g',0]]
    assert result['entities']['gate']==1
