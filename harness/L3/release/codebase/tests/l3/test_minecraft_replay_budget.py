import json
from tools.verify_l3_submission import prepare_episode_replay
import pytest

def test_timeout_preserves_evidence_and_plan(tmp_path):
    workspace=tmp_path/'workspace'
    folder=workspace/'episodes/views';folder.mkdir(parents=True)
    plan={'steps':[{'seconds':200}]}
    (folder/'plan.json').write_text(json.dumps(plan))
    (folder/'trajectory_00000.json').write_text(json.dumps({'time':0}))
    (folder/'trajectory_00001.json').write_text(json.dumps({'time':50}))
    (folder/'overview.png').write_bytes(b'original image')
    log=tmp_path/'episode_views.log';log.write_text('Command timed out after 900s')
    budget,evidence=prepare_episode_replay(workspace,tmp_path,'views',plan)
    assert budget==6300
    assert evidence and not folder.exists()
    archive=next((workspace/'episodes').glob('views-failed-*'))
    assert (archive/'overview.png').read_bytes()==b'original image'
    assert json.loads((archive/'plan.json').read_text())==plan
    assert list((tmp_path/'failed-attempts').glob('*-episode_views.log'))
    assert plan=={'steps':[{'seconds':200}]}

def test_changed_plan_is_rejected_before_archiving(tmp_path):
    workspace=tmp_path/'workspace'
    folder=workspace/'episodes/views';folder.mkdir(parents=True)
    (folder/'plan.json').write_text(json.dumps({'steps':[]}))
    with pytest.raises(ValueError,match='plan changed'):
        prepare_episode_replay(workspace,tmp_path,'views',{'steps':[{'seconds':1}]})
    assert folder.exists()

def test_fresh_episode_has_slow_renderer_budget(tmp_path):
    budget,evidence=prepare_episode_replay(tmp_path/'workspace',tmp_path,'views',{'steps':[{'seconds':10}]})
    assert budget==3600 and evidence==[]
