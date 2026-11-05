"""Campaign engine aliases preserve dedicated-engine identity checks."""
import os
from unittest.mock import patch
from pathlib import Path
from tools import l3_leaderboard_batch as batch
import tools.prepare_l3_trial as preparation

def test_worker_resolves_engine_alias_before_preparation(tmp_path,monkeypatch):
    campaign=tmp_path/'campaign';engine=tmp_path/'dedicated-engine';engine.mkdir()
    (campaign/'engines').mkdir(parents=True)
    (campaign/'engines/slot-00').symlink_to(engine,target_is_directory=True)
    row={'id':'l3-e01--gpt-6.1-sol--max','task_key':'l3-e01',
         'output':str(campaign/'runs/trial'),'task_path':str(tmp_path/'task'),
         'model':'gpt-6.1-sol','effort':'max','group':'openai'}
    observed=[]
    def prepare(*args,**kwargs):
        observed.append(args[2])
        raise RuntimeError('stop before any runtime or API request')
    monkeypatch.setattr(batch,'B',campaign)
    monkeypatch.setattr(preparation,'prepare',prepare)
    with patch.dict(os.environ,dict(os.environ),clear=True):
        batch.worker(row,0)
    assert observed==[engine.resolve()]
    assert batch.read(Path(row['output'])/'state.json')['status']=='failed'
