import json
import subprocess
from pathlib import Path
from unittest.mock import patch
import pytest
from tools.prepare_l3_trial import assert_engine_available, docker_running_snapshot


@pytest.fixture(autouse=True)
def legacy_inspection_fallback():
    with patch('tools.prepare_l3_trial.docker_running_snapshot',return_value=None):
        yield


def test_disappeared_container_does_not_abort_preparation():
    results=[subprocess.CompletedProcess([],1,'','Error: No such object: gone'),
             subprocess.CompletedProcess([],0,json.dumps([{'Mounts':[{'Source':'/other'}]}]),'')]
    with patch('tools.prepare_l3_trial.subprocess.check_output',return_value='gone live'), patch('tools.prepare_l3_trial.subprocess.run',side_effect=results):
        assert_engine_available(Path('/engine'))

def test_live_engine_collision_still_rejected():
    result=subprocess.CompletedProcess([],0,json.dumps([{'Mounts':[{'Source':'/engine'}]}]),'')
    with patch('tools.prepare_l3_trial.subprocess.check_output',return_value='live'), patch('tools.prepare_l3_trial.subprocess.run',return_value=result):
        with pytest.raises(ValueError,match='in use'):assert_engine_available(Path('/engine'))

def test_docker_connection_failure_not_ignored():
    result=subprocess.CompletedProcess([],1,'','Cannot connect to Docker daemon')
    with patch('tools.prepare_l3_trial.subprocess.check_output',return_value='live'), patch('tools.prepare_l3_trial.subprocess.run',return_value=result):
        with pytest.raises(RuntimeError,match='Cannot inspect'):assert_engine_available(Path('/engine'))

def test_stopped_since_listing_does_not_occupy_engine():
    result=subprocess.CompletedProcess([],0,json.dumps([{'State':{'Running':False},'Mounts':[{'Source':'/engine'}]}]),'')
    with patch('tools.prepare_l3_trial.subprocess.check_output',return_value='stopped'), patch('tools.prepare_l3_trial.subprocess.run',return_value=result):
        assert_engine_available(Path('/engine'))


def test_container_listing_timeout_fails_closed():
    with patch('tools.prepare_l3_trial.subprocess.check_output',side_effect=subprocess.TimeoutExpired('docker ps',20)) as listing:
        with pytest.raises(RuntimeError,match='timed out while listing'):
            assert_engine_available(Path('/engine'))
        assert listing.call_args.kwargs['timeout']==20


def test_container_inspection_timeout_fails_closed():
    with patch('tools.prepare_l3_trial.subprocess.check_output',return_value='live'), patch('tools.prepare_l3_trial.subprocess.run',side_effect=subprocess.TimeoutExpired('docker inspect',20)) as inspect:
        with pytest.raises(RuntimeError,match='timed out while inspecting live'):
            assert_engine_available(Path('/engine'))
        assert 0 < inspect.call_args.kwargs['timeout'] <= 20


def test_total_inspection_budget_is_bounded():
    with patch('tools.prepare_l3_trial.subprocess.check_output',return_value='live'), patch('tools.prepare_l3_trial.time.monotonic',side_effect=[100,161]), patch('tools.prepare_l3_trial.subprocess.run') as inspect:
        with pytest.raises(RuntimeError,match='60-second budget'):
            assert_engine_available(Path('/engine'))
        inspect.assert_not_called()


def test_mount_snapshot_rejects_actual_engine_collision():
    snapshot=[{'Names':['/occupied'],'Mounts':[{'Source':'/engine'}]}]
    with patch('tools.prepare_l3_trial.docker_running_snapshot',return_value=snapshot), patch('tools.prepare_l3_trial.subprocess.run') as inspect:
        with pytest.raises(ValueError,match='occupied'):
            assert_engine_available(Path('/engine'))
        inspect.assert_not_called()


def test_mount_snapshot_avoids_unrelated_container_inspections():
    snapshot=[{'Names':['/other'],'Mounts':[{'Source':'/other-engine'}]}]
    with patch('tools.prepare_l3_trial.docker_running_snapshot',return_value=snapshot), patch('tools.prepare_l3_trial.subprocess.run') as inspect:
        assert_engine_available(Path('/engine'))
        inspect.assert_not_called()


def test_unix_snapshot_rejects_missing_mount_evidence():
    from unittest.mock import MagicMock
    response=MagicMock(status=200)
    response.read.return_value=b'[{"Id":"missing-mounts"}]'
    with patch.dict('os.environ',{'DOCKER_HOST':'unix:///test.sock','DOCKER_CONTEXT':''}), patch('tools.prepare_l3_trial.http.client.HTTPConnection.request'), patch('tools.prepare_l3_trial.http.client.HTTPConnection.getresponse',return_value=response):
        with pytest.raises(RuntimeError,match='mount evidence'):
            docker_running_snapshot()


def test_unix_snapshot_accepts_mounts_and_closes_connection():
    from unittest.mock import MagicMock
    response=MagicMock(status=200)
    response.read.return_value=b'[{"Mounts":[{"Source":"/engine"}]}]'
    with patch.dict('os.environ',{'DOCKER_HOST':'unix:///test.sock','DOCKER_CONTEXT':''}), patch('tools.prepare_l3_trial.http.client.HTTPConnection.request') as request, patch('tools.prepare_l3_trial.http.client.HTTPConnection.getresponse',return_value=response), patch('tools.prepare_l3_trial.http.client.HTTPConnection.close') as close:
        assert docker_running_snapshot()[0]['Mounts'][0]['Source']=='/engine'
        request.assert_called_once_with('GET','/containers/json?all=0')
        close.assert_called_once()
