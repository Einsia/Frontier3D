import subprocess
from unittest.mock import patch
import pytest
from tools.l3_leaderboard_batch import ensure_trial_container_running

ENV={'container':'l3-owned-trial','docker_command':['docker','run','owned-image']}

def test_running_owned_container_is_adopted_without_start():
    with patch('tools.prepare_l3_trial.docker_running_snapshot',return_value=[{'Names':['/l3-owned-trial'],'Mounts':[]}]), patch('tools.l3_leaderboard_batch.subprocess.run') as run:
        assert ensure_trial_container_running(ENV)=='already_running'
        run.assert_not_called()

def test_other_container_does_not_count_as_running():
    with patch('tools.prepare_l3_trial.docker_running_snapshot',return_value=[{'Names':['/l3-owned-trial-extra'],'Mounts':[]}]), patch('tools.l3_leaderboard_batch.subprocess.run',return_value=subprocess.CompletedProcess([],0)) as run:
        assert ensure_trial_container_running(ENV)=='started'
        assert run.call_args.args[0]==['docker','start','l3-owned-trial']

def test_absent_container_uses_preserved_creation_command():
    with patch('tools.prepare_l3_trial.docker_running_snapshot',return_value=[]), patch('tools.l3_leaderboard_batch.subprocess.run',return_value=subprocess.CompletedProcess([],1)) as run:
        assert ensure_trial_container_running(ENV)=='created'
        assert run.call_args.args[0]==ENV['docker_command']

def test_snapshot_failure_does_not_start_any_container():
    with patch('tools.prepare_l3_trial.docker_running_snapshot',side_effect=RuntimeError('Docker unavailable')), patch('tools.l3_leaderboard_batch.subprocess.run') as run:
        with pytest.raises(RuntimeError):ensure_trial_container_running(ENV)
        run.assert_not_called()


def test_resume_rejects_other_live_container_using_same_engine():
    snapshot=[{'Names':['/other-trial'],'Mounts':[{'Source':'/engines/slot-03'}]}]
    with patch('tools.prepare_l3_trial.docker_running_snapshot',return_value=snapshot), patch('tools.l3_leaderboard_batch.subprocess.run') as run:
        with pytest.raises(RuntimeError,match='resume engine is occupied'):
            ensure_trial_container_running({**ENV,'engine_copy':'/engines/slot-03'})
        run.assert_not_called()
