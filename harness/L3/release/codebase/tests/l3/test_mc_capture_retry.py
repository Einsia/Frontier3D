from pathlib import Path

def test_explicit_archived_mc_episode_controls_retry_budget(tmp_path):
    import copy,json
    from harness.L3.Suite.replay_budget import retry_budget
    from tools.capture_l3_algorithms import replay_timeout
    plan={'steps':[{'op':'walk_to','seconds':272.25}]};before=copy.deepcopy(plan)
    episode=tmp_path/'archived-capture/workflow';episode.mkdir(parents=True)
    (episode/'plan.json').write_text(json.dumps(plan))
    (episode/'trajectory_00000.json').write_text(json.dumps({'time':1.0}))
    (episode/'trajectory_07031.json').write_text(json.dumps({'time':238.6}))
    log=tmp_path/'workflow.log';log.write_text('RuntimeError: Command timed out after 4167s')
    seconds,evidence=retry_budget(plan,episode.parent,'workflow',log,replay_folders=[episode])
    assert seconds>replay_timeout(plan) and seconds>4167
    assert evidence[0]['observed_sim_seconds']==237.6
    assert plan==before
    altered={'steps':[{'op':'wait','seconds':1}]}
    seconds,evidence=retry_budget(altered,episode.parent,'workflow',log,replay_folders=[episode])
    assert seconds==replay_timeout(altered) and not evidence

def test_capture_retry_rejects_mismatched_frozen_identity(tmp_path,monkeypatch):
    import json,pytest
    from tools import capture_l3_algorithms as m
    from harness.L3.MinecraftVillage.protocol import tree_digest,digest
    trial=tmp_path/'trial';source=trial/'workspace/project';source.mkdir(parents=True)
    (source/'scene.cpp').write_text('candidate')
    run=tmp_path/'run';project=run/'workspace/project';project.mkdir(parents=True)
    (project/'scene.cpp').write_text('verifier')
    record={'status':'collected','source_sha256':tree_digest(source),'verification_source_sha256':tree_digest(project)}
    (run/'run.json').write_text(json.dumps(record))
    retry=tmp_path/'retry';retry.mkdir();episodes=tmp_path/'episodes';episodes.mkdir()
    (retry/'capture.json').write_text(json.dumps({'source_sha256':'other','run_sha256':digest(run/'run.json')}))
    monkeypatch.setattr(m.subprocess,'run',lambda *a,**k:pytest.fail('Must reject before Docker'))
    with pytest.raises(ValueError,match='identity mismatch'):
        m.capture(run,trial,tmp_path/'out',retry,episodes)
    assert not (tmp_path/'out').exists()

def test_matrix_preserves_partial_capture_and_forwards_retry_evidence(tmp_path,monkeypatch):
    import json,pytest
    from tools import l3_matrix_mc as m
    folder=tmp_path/'eval';run=folder/'verification';run.mkdir(parents=True)
    (run/'run.json').write_text(json.dumps({'status':'collected'}))
    geometry=folder/'algorithms/geometry';geometry.mkdir(parents=True);(geometry/'geometry.json').write_text('{}')
    capture=folder/'algorithms/capture';capture.mkdir();(capture/'capture.json').write_text(json.dumps({'status':'measured','episodes':{'workflow':{'status':'infrastructure_failure'}}}))
    episode=run/'workspace/algorithm-v1/workflow';episode.mkdir(parents=True);(episode/'plan.json').write_text('original plan')
    called=[]
    def execute(label,args,out):
        called.append(args);raise RuntimeError('test ends before starting measurement')
    monkeypatch.setattr(m,'execute',execute)
    with pytest.raises(RuntimeError,match='test ends'):m.collect_runtime(tmp_path/'trial',folder)
    args=called[0]
    archive=Path(args[args.index('--retry-capture')+1])
    replay=Path(args[args.index('--retry-episodes')+1])
    assert (archive/'capture.json').is_file()
    assert (replay/'workflow/plan.json').read_text()=='original plan'
    assert not capture.exists()
