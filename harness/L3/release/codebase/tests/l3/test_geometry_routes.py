import copy
import numpy as np
import pytest
from harness.L3.MinecraftVillage import geometry_routes as g
from harness.L3.MinecraftVillage import algorithm_workflow as w


def test_geometry_poses_ignore_stale_and_hinge_side_hints(monkeypatch):
    for module in [g,w]:monkeypatch.setattr(module,'DOORS',['room.door'])
    monkeypatch.setattr(g,'CHESTS',['room.chest'])
    for name in ['CROPS','FURNACES','BLOCKS']:monkeypatch.setattr(g,name,[])
    mesh={'vertices_cm':[[x,y,z] for x in [-.5,.5] for y in [-.5,.5] for z in [-.5,.5]]}
    def item(actor,center,size):
        return {'actor':actor,'mesh':'cube','origin_cm':center,'axis_x':[size[0],0,0],'axis_y':[0,size[1],0],'axis_z':[0,0,size[2]],'blocks_pawn':True,'role':'prop'}
    ex={'meshes':{'cube':mesh},'instances':[
        item('room.door',[0,0,100],[120,10,200]),
        item('room.chest',[100,180,45],[60,60,90]),
        item('west_wall',[-160,0,100],[180,30,200]),
        item('east_wall',[160,0,100],[180,30,200])
    ]}
    hints={'entities':{'room.door':{'approach_cm':[60,-200,85],'look_cm':[60,0,100],'crossing_from_cm':[60,-150,85],'crossing_to_cm':[60,150,85]},
        'room.chest':{'approach_cm':[700,700,85],'look_cm':[700,700,85]}}}
    frozen=copy.deepcopy(hints)
    actual,audit=g.derive_bindings(ex,hints,{'pawn_position_cm':[0,-300,85]})
    assert hints==frozen
    door=actual['entities']['room.door']
    assert door['crossing_from_cm'][0]==pytest.approx(0)
    assert door['crossing_to_cm'][0]==pytest.approx(0)
    assert door['crossing_from_cm'][1]<0<door['crossing_to_cm'][1]
    chest=actual['entities']['room.chest']
    assert np.allclose(chest['look_cm'],[100,180,45])
    assert np.linalg.norm(np.array(chest['approach_cm'][:2])-[100,180])<250
    assert audit['targets']['room.chest']['reachable_candidates']>0


def test_door_lane_success_requires_matched_closed_open_closed_path(tmp_path):
    from harness.L3.MinecraftVillage.protocol import DOORS,write_json
    bindings={'entities':{t:{'approach_cm':[0,-100,85],'crossing_from_cm':[0,-100,85],
        'crossing_to_cm':[0,100,85],'test_lane_offset_cm':[45,0]} for t in DOORS}}
    plan,checks=w.door_walk_plan(bindings)
    assert sum(s['op']=='walk_to' for s in plan['steps'])==45
    for check in checks:
        for i,lane in enumerate(check['lanes']):
            for state in ['closed','open','reclosed']:
                # Center is obstructed in every state. A side path works only
                # when open. The other side is a permanently open bypass.
                reached=(i==1 and state=='open') or i==2
                pos=lane['destination'] if reached else lane['start']
                write_json(tmp_path/(lane['prefix']+'_'+state+'_end.json'),{'pawn_position_cm':pos})
    result=w.diagnose_doors(tmp_path,checks)
    for row in result['targets'].values():
        assert row['opened_passage'] and row['closed_barrier'] and row['closed_again']
        assert row['prefix'].endswith('_l1')

def test_fully_blocked_conservative_grid_keeps_runtime_probe(monkeypatch):
    monkeypatch.setattr(g,'DOORS',[])
    monkeypatch.setattr(g,'CHESTS',[])
    monkeypatch.setattr(g,'CROPS',['crop'])
    monkeypatch.setattr(g,'FURNACES',[])
    monkeypatch.setattr(g,'BLOCKS',[])
    class FullyBlocked:
        def __init__(self,*args):
            self.blocked=np.ones((10,10),dtype=bool)
        def cell(self,point):return (5,5)
        def route(self,*args):raise AssertionError('Blocked proposals must not be routed')
    monkeypatch.setattr(g,'GridPlanner',FullyBlocked)
    ex={'meshes':{'cube':{'vertices_cm':[[x,y,z] for x in [-20,20] for y in [-20,20] for z in [0,40]]}},
        'instances':[{'actor':'crop','mesh':'cube','origin_cm':[0,0,0],
                      'axis_x':[1,0,0],'axis_y':[0,1,0],'axis_z':[0,0,1]}]}
    hints={'entities':{'crop':{'approach_cm':[400,400,85],'look_cm':[400,400,40]}}}
    original=copy.deepcopy(hints)
    actual,audit=g.derive_bindings(ex,hints,{'pawn_position_cm':[0,-300,85]})
    assert hints==original
    assert actual['entities']['crop']['approach_cm']==[-75.,0.,85.]
    assert actual['entities']['crop']['look_cm']==[0.,0.,20.]
    row=audit['targets']['crop']
    assert row['route_status']=='planner_unresolved'
    assert row['pose_selection']=='unverified_geometry_perimeter'
    assert row['reachable_candidates']==0
