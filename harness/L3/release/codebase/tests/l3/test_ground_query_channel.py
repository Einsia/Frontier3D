import pytest
from pathlib import Path
from tools.l3_ground_query import OLD,NEW,MARKER,patched_observer,can_upgrade

def test_only_reviewed_ray_block_changes_and_default_is_visibility():
    original='before interaction\n'+OLD+'\nafter interaction'
    result=patched_observer(original)
    assert result=='before interaction\n'+NEW+'\nafter interaction'
    assert 'PawnGround?ECC_Pawn:ECC_Visibility' in result
    assert 'BenchSurfaceRay),!PawnGround,Pawn' in result
    assert patched_observer(result)==result

@pytest.mark.parametrize('text',['other observer',OLD+'\n'+OLD])
def test_unknown_or_duplicate_implementation_rejected(text):
    with pytest.raises(ValueError):patched_observer(text)

def test_existing_completed_actions_prevent_observer_upgrade():
    assert can_upgrade({})
    assert can_upgrade({'episodes':{'pose_ground':{'completed':True}}})
    assert not can_upgrade({'episodes':{'workflow':{'completed':True}}})

def test_upgrade_rejects_changed_candidate_before_docker(tmp_path,monkeypatch):
    import json
    from tools import l3_ground_query as m
    run=tmp_path/'run';run.mkdir()
    (run/'run.json').write_text(json.dumps({'status':'collected','source':str(tmp_path/'candidate'),'source_sha256':'frozen'}))
    monkeypatch.setattr(m,'tree_digest',lambda p:'changed')
    monkeypatch.setattr(m.subprocess,'run',lambda *a,**k:pytest.fail('must not start Docker for changed source'))
    with pytest.raises(ValueError,match='Frozen candidate changed'):
        m.prepare_ground_observer(run,tmp_path/'output')

@pytest.mark.parametrize('build_ok',[True,False])
def test_observer_upgrade_retains_candidate_and_archives_only_runtime(tmp_path,monkeypatch,build_ok):
    import json,subprocess
    from tools import l3_ground_query as m
    candidate=tmp_path/'candidate';candidate.mkdir();(candidate/'scene.cpp').write_text('frozen scene')
    run=tmp_path/'run';project=run/'workspace/project'
    cpp=project/'Plugins/BenchRuntime/Source/BenchRuntime/Private/BenchObserver.cpp'
    cpp.parent.mkdir(parents=True);cpp.write_text(OLD)
    retained=run/'workspace/episodes/views';retained.mkdir(parents=True);(retained/'completed.json').write_text('original episode')
    output=tmp_path/'output';output.mkdir();(output/'run.json').write_text(json.dumps({'episodes':{'pose_ground':{'completed':True}}}))
    old_runtime=run/'workspace/runtime-geometry-v2';old_runtime.mkdir();(old_runtime/'probe').write_text('old failed probe')
    candidate_hash=m.tree_digest(candidate);verifier_hash=m.tree_digest(project)
    record={'status':'collected','source':str(candidate),'source_sha256':candidate_hash,'verification_source_sha256':verifier_hash,'observer_sha256':m.tree_digest(project/'Plugins/BenchRuntime'),'container':'owned-verifier'}
    (run/'run.json').write_text(json.dumps(record))
    def execute(cmd,**kwargs):
        if cmd[1]=='inspect':return subprocess.CompletedProcess(cmd,0,stdout=json.dumps([{'State':{'Running':False}}]))
        if 'build' in cmd and not build_ok:raise subprocess.CalledProcessError(1,cmd)
        return subprocess.CompletedProcess(cmd,0,stdout='')
    monkeypatch.setattr(m.subprocess,'run',execute)
    if build_ok:
        assert m.prepare_ground_observer(run,output)
        after=json.loads((run/'run.json').read_text())
        assert after['source_sha256']==candidate_hash
        assert after['verification_source_sha256']==m.tree_digest(project)!=verifier_hash
        archive=Path(after['ground_query_observer_recovery']['archive'])
        assert (archive/'runtime-output.before/run.json').is_file()
        assert (archive/'runtime-episodes.before/probe').read_text()=='old failed probe'
        assert not output.exists()
        assert after['ground_query_observer_recovery']['retained_episode_observer_sha256']==record['observer_sha256']
    else:
        with pytest.raises(subprocess.CalledProcessError):m.prepare_ground_observer(run,output)
        assert cpp.read_text()==OLD
        assert json.loads((run/'run.json').read_text())==record
        assert output.exists()
    assert (retained/'completed.json').read_text()=='original episode'
    assert m.tree_digest(candidate)==candidate_hash
