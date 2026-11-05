import copy
from harness.L3.MinecraftVillage import algorithm_geometry as geom
from harness.L3.Suite.collect import replay_timeout

def test_large_mc_scene_uses_complete_suite_capacity(tmp_path,monkeypatch):
    physical={'instances':[{}]}
    monkeypatch.setattr(geom,'read_json',lambda _: {})
    monkeypatch.setattr(geom,'physical_scene',lambda *_:(physical,{}))
    monkeypatch.setattr(geom,'compact',lambda x:(x,{'output_instances':1}))
    monkeypatch.setattr(geom,'Scene',lambda x:x)
    monkeypatch.setattr(geom,'static_measure',lambda _: {'overlap_pair_count':0})
    monkeypatch.setattr(geom,'motion_measure',lambda *_:{})
    monkeypatch.setattr(geom,'digest',lambda _:'source-hash')
    def complete_support(scene,maximum_triangles=1_000_000,maximum_pieces=100_000,maximum_triangle_pairs=20_000_000):
        if maximum_triangles<1_000_001:raise ValueError('complete scene exceeds legacy capacity')
        assert scene is physical
        return {'complete_scene':True}
    monkeypatch.setattr(geom,'support_measure',complete_support)
    result=geom.measure(tmp_path/'run',tmp_path/'trial',tmp_path/'output')
    assert result['support']['complete_scene']

def test_suite_replay_budget_keeps_full_long_steps_and_plan():
    plan={'steps':[{'op':'wait','seconds':600},{'op':'wait','seconds':500}]}
    before=copy.deepcopy(plan)
    assert replay_timeout(plan)>=1100*12+900
    assert replay_timeout({'steps':[]})>=3600
    assert plan==before
