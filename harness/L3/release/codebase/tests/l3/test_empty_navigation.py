import json
import pytest
from harness.L3.Suite import measure

def write(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))

def fixture(tmp_path, walking=False):
    f=tmp_path/'l3-e05'; work=f/'workspace/episodes/workflow'
    frame={'protocol':'ue5-observer-v1','entities':[],'pawn_position_cm':[0,0,0]}
    write(f/'contract.json',{'entities':[{'id':'door','role':'door'}]})
    write(f/'local-metadata.json',{'entities':[{'id':'door','binding_missing':True}]})
    write(f/'workspace/project/bindings.json',{})
    for n in ['initial','final']:write(work/(n+'.json'),frame)
    write(work/'completed.json',{'completed':True})
    steps=[]
    if walking:
        steps=[{'before':'a','after':'b','step':{'op':'walk_to','name':'walk','target_cm':[100,0,0]}}]
        write(work/'a.json',frame);write(work/'b.json',{**frame,'pawn_position_cm':[100,0,0]})
    write(f/'workflow-metadata.json',{'steps':steps,'rejected':[] if walking else [{'reason':'invalid target_cm','step':{'op':'walk_to','target_cm':[1,2]}}]})
    return f

def test_rejected_walk_is_submission_failure_after_real_completed_episode(tmp_path,monkeypatch):
    monkeypatch.setattr(measure,'goals',lambda *args:[{'name':'required goal','passed':False}])
    f=fixture(tmp_path)
    out=measure.observations(f)
    assert out['navigation']==0 and out['route_success_fraction']==0
    assert out['navigation_evidence_status']=='completed_episode_without_executable_walk'
    assert out['rejected_route_steps']

def test_valid_observed_navigation_unchanged(tmp_path,monkeypatch):
    monkeypatch.setattr(measure,'goals',lambda *args:[{'name':'required goal','passed':True}])
    out=measure.observations(fixture(tmp_path,True))
    assert out['navigation']==1 and out['route_success_fraction']==1

@pytest.mark.parametrize('missing',['completed.json','final.json'])
def test_missing_independent_evidence_is_not_zero_scored(tmp_path,missing):
    f=fixture(tmp_path);(f/'workspace/episodes/workflow'/missing).unlink()
    with pytest.raises((RuntimeError,FileNotFoundError)):measure.observations(f)

def test_incomplete_episode_is_not_submission_failure(tmp_path):
    f=fixture(tmp_path);write(f/'workspace/episodes/workflow/completed.json',{'completed':False})
    with pytest.raises(RuntimeError,match='Incomplete independent workflow'):measure.observations(f)

def test_wrong_observer_protocol_not_zero_scored(tmp_path):
    f=fixture(tmp_path);write(f/'workspace/episodes/workflow/final.json',{'protocol':'candidate-claimed'})
    with pytest.raises(RuntimeError,match='Wrong observer protocol'):measure.observations(f)
