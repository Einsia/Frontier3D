"""Resume a parked, unauthored trial using its original workspace and container."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".venv/bin/python"
if __name__ == "__main__" and RUNTIME.exists() and Path(sys.executable).resolve() != RUNTIME.resolve():
    os.execv(str(RUNTIME), [str(RUNTIME), *sys.argv])
sys.path.insert(0, str(ROOT))
from tools.l3_api_control import stopped, BalanceExhausted
from tools.l3_trial_status import has_authoring_activity
from tools.validate_l3_suite import sha


def validate_parked(root):
    record = json.loads((root / 'trial.json').read_text())
    if record['status'] not in {'queued_model_connection', 'queued_preflight', 'retrying_model_connection'}:
        raise RuntimeError('Only unauthored connection-waiting trials may resume here')
    events = root / 'agent-events.jsonl'
    if record.get('started_unix') or (events.exists() and has_authoring_activity(events)):
        raise RuntimeError('Refusing to restart an authored trial')
    baseline = json.loads((root / 'preflight-complete.json').read_text())
    for relative, expected in baseline['input_and_material_hashes'].items():
        if sha(root / 'workspace' / relative) != expected:
            raise RuntimeError('Parked input changed: ' + relative)
    for relative, expected in baseline.get('public_tool_hashes', {}).items():
        if sha(root / 'public' / relative) != expected:
            raise RuntimeError('Parked public tool changed: ' + relative)
    return json.loads((root / 'environment.json').read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    environment = validate_parked(root)
    if stopped():
        raise BalanceExhausted('API balance exhausted')
    lock = ROOT / 'data/l3/locks' / ('engine-' + hashlib.sha256(str(Path(environment['engine_copy']).resolve()).encode()).hexdigest()[:16] + '.lock')
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        container = environment['container']
        running = subprocess.check_output(['docker', 'inspect', '-f', '{{.State.Running}}', container], text=True).strip()
        if running != 'false':
            raise RuntimeError('Parked container is already running')
        gateway = Path(environment['gateway_directory'])
        gateway.mkdir(parents=True, exist_ok=True)
        socket = gateway / 'api.sock'
        socket.unlink(missing_ok=True)
        command = [sys.executable, str(ROOT / 'tools/l3_model_bridge.py'), 'serve', '--socket', str(socket),
                   '--provider', str(ROOT.parent / '.config/3dbench/provider.json'), '--ledger', str(root / 'model-requests.jsonl'),
                   '--stage-file', str(root / 'model-stage.txt')]
        with (root / 'gateway.log').open('a') as log:
            server = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True,
                                      env={**os.environ, 'L3_EXPECTED_MODEL': environment['model']})
        environment['gateway_pid'] = server.pid
        (root / 'environment.json').write_text(json.dumps(environment, indent=2) + '\n')
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Gateway failed to start')
                if socket.exists():
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('Gateway socket not ready')
            subprocess.run(['docker', 'start', container], check=True)
            subprocess.run(['docker', 'exec', '-d', container, 'python3', '/opt/l3-public/l3_model_bridge.py',
                            'bridge', '--socket', '/model-gateway/api.sock'], check=True)
            subprocess.run([sys.executable, str(ROOT / 'tools/run_l3_trial.py'), '--output', str(root), '--generate'], check=True)
        finally:
            subprocess.run(['docker', 'stop', '--time', '10', container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            server.terminate()
            server.wait(timeout=15)


if __name__ == '__main__':
    main()
