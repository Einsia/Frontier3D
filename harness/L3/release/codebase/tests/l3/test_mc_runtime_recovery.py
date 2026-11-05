import json
from tools.repair_l3_runtime import load_geometry
from tools.evaluate_l3_model_queue import resume_engine

def test_multimodel_runtime_uses_explicit_scene_without_legacy_directory(tmp_path):
    trial=tmp_path/"submission";trial.mkdir()
    scene=tmp_path/"evaluation"/"physical-scene.json";scene.parent.mkdir()
    scene.write_text(json.dumps({"instances":[{"actor":"measured-candidate"}]}))
    path,data=load_geometry(trial,scene)
    assert path==scene
    assert data["instances"][0]["actor"]=="measured-candidate"
    assert not (trial/"evaluation-algorithm-v1").exists()

def test_legacy_scene_remains_supported(tmp_path):
    scene=tmp_path/"evaluation-algorithm-v1/geometry/physical-scene.json"
    scene.parent.mkdir(parents=True);scene.write_text('{"instances":[]}')
    assert load_geometry(tmp_path)==(scene,{"instances":[]})

def test_restart_keeps_the_engine_mounted_by_the_verifier(tmp_path):
    assert resume_engine(tmp_path) is None
    p=tmp_path/"verification/run.json";p.parent.mkdir()
    p.write_text(json.dumps({"command":["docker","run","type=bind,src=/data/workspace,dst=/workspace",
      "type=bind,src=/data/engines/dedicated-sol,dst=/data/engines/main"]}))
    assert resume_engine(tmp_path)=="/data/engines/dedicated-sol"


def _bindings():
    from harness.L3.MinecraftVillage.protocol import REQUIRED, DOORS
    entities={k:{'approach_cm':[0.,-100.,85.],'look_cm':[0.,0.,50.]} for k in REQUIRED}
    for k in DOORS:
        entities[k].update(crossing_from_cm=[0.,-150.,85.],crossing_to_cm=[0.,150.,85.])
    return {'entities':entities}

def test_unresolved_route_keeps_real_local_interaction_probe(monkeypatch):
    import numpy as np
    from harness.L3.MinecraftVillage import geometry_routes as routes
    from harness.L3.MinecraftVillage.protocol import REQUIRED,CHESTS
    class Disconnected:
        def __init__(self,*a):
            self.blocked=np.zeros((10,10),bool)
        def cell(self,p):return (5,5)
        def route(self,*a):raise ValueError('Disconnected grid')
    monkeypatch.setattr(routes,'GridPlanner',Disconnected)
    monkeypatch.setattr(routes,'actor_vertices',lambda x:{k:np.array([[-45.,-30.,0.],[45.,30.,80.]]) for k in REQUIRED})
    result,audit=routes.derive_bindings({},_bindings(),{'pawn_position_cm':[1000.,1000.,85.]})
    for target in CHESTS:
        row=audit['targets'][target]
        assert row['route_status']=='planner_unresolved'
        assert row['reachable_candidates']==0
        assert row['pose_selection']=='nearest_free_perimeter'
        assert 'passed' not in row
        assert result['entities'][target]['look_cm']==[0.,0.,40.]

def test_unresolved_workflow_routes_are_walked_not_teleported_or_prescored(monkeypatch):
    from harness.L3.MinecraftVillage import algorithm_workflow as workflow
    class Disconnected:
        def __init__(self,*a):pass
        def route(self,*a):raise ValueError('Disconnected grid')
    monkeypatch.setattr(workflow,'GridPlanner',Disconnected)
    plan,meta=workflow.make_workflow({},_bindings(),{'pawn_position_cm':[1000.,1000.,85.]})
    assert meta['planner_fallbacks']
    assert meta['teleports']==0
    assert all(s['op']!='fixture' for s in plan['steps'])
    assert any(s['op']=='walk_to' for s in plan['steps'])
    assert any(s['op']=='interact' and s['target']=='house01.chest' for s in plan['steps'])
    assert 'workflow_success' not in meta
    assert all('passed' not in r for r in meta['routes'])
