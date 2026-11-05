"""Persistent finite model queue, including parked connection probes."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".venv/bin/python"
if __name__ == "__main__" and RUNTIME.exists() and Path(sys.executable).resolve() != RUNTIME.resolve():
    os.execv(str(RUNTIME), [str(RUNTIME), *sys.argv])
sys.path.insert(0, str(ROOT))
from tools.l3_usage import summarize_requests
from tools.validate_l3_suite import validate_task, sha


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def live(pid):
    try:
        return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False


def choose_next(pending, byid, parked, slot):
    # Keep unavailable-model probes from blocking untouched runnable-model jobs.
    for rid in pending:
        if byid[rid]['model'] == 'gpt-6-astra' and rid not in parked:
            return rid
    for rid in pending:
        if parked.get(rid) == slot and byid[rid]['model'] == 'gpt-6-astra':
            return rid
    for rid in pending:
        if parked.get(rid) == slot:
            return rid
    return next((rid for rid in pending if rid not in parked), None)


def cleanup(run):
    root = ROOT / run['output']
    file = root / 'environment.json'
    if not file.exists():
        return
    env = json.loads(file.read_text())
    subprocess.run(['docker', 'stop', '--time', '10', env['container']], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid = env.get('gateway_pid')
    cmd = Path('/proc') / str(pid) / 'cmdline'
    if cmd.exists() and str(root / 'model-requests.jsonl').encode() in cmd.read_bytes():
        os.kill(pid, signal.SIGTERM)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', type=Path, required=True)
    args = parser.parse_args()
    checkpoint = args.checkpoint.resolve()
    control = checkpoint.parent
    singleton = (control / 'continuation-controller.lock').open('a')
    fcntl.flock(singleton, fcntl.LOCK_EX | fcntl.LOCK_NB)
    import numpy, PIL  # Fail before dispatch if the configured runtime is incomplete.
    state = json.loads(checkpoint.read_text())
    state['python_executable'] = sys.executable
    runs = json.loads(Path(state['manifest']).read_text())['runs']
    byid = {r['id']: r for r in runs}
    for run in runs:
        task = ROOT / run['task_path']
        validate_task(task)
        if sha(task / 'package-manifest.json') != run['package_manifest_sha256']:
            raise RuntimeError('Task package changed: ' + run['id'])
    active = {int(k): v for k, v in state['active_workers'].items()}
    recoveries = state.setdefault('generation_recoveries', {})
    parked = state['parked_runs']
    pending = state['pending_runs']
    slots = state['slots']
    completed = set(state['completed_runs'])
    failures = state.get('failed_runs', {})
    partition = list(completed) + [j['run_id'] for j in active.values()] + pending + list(failures)
    if len(partition) != len(set(partition)) or set(partition) != set(byid):
        raise RuntimeError('Queue must cover every manifest run exactly once')
    children = {}
    env = {**os.environ, 'L3_BATCH_CONTROL': str(control), 'L3_API_CONCURRENCY': '10', 'PYTHONUNBUFFERED': '1'}

    def save():
        state.update(active_workers=active, parked_runs=parked, pending_runs=pending, slots=slots,
                     completed_runs=sorted(completed), failed_runs=failures, supervisor_pid=os.getpid(), updated_unix=time.time())
        write(checkpoint, state)

    while True:
        balance = (control / 'balance-exhausted.json').exists()
        for slot, job in list(active.items()):
            child = children.get(slot)
            if (child.poll() is None) if child else live(job['pid']):
                continue
            rid = job['run_id']
            parent = job.get('adopted_parent')
            if parent and live(parent):
                os.kill(parent, signal.SIGKILL)
            cleanup(byid[rid])
            path = ROOT / byid[rid]['output'] / 'trial.json'
            status = json.loads(path.read_text())['status'] if path.exists() else 'failed_before_trial_record'
            trial = json.loads(path.read_text()) if path.exists() else {}
            retries = state.setdefault('infrastructure_retries', {})
            if status == 'generated_awaiting_independent_verification':
                completed.add(rid)
            elif status == 'blocked_preflight' and trial.get('error') == "No module named 'numpy'" and retries.get(rid, 0) == 0:
                archive = path.parent / 'infrastructure-attempts'
                archive.mkdir(exist_ok=True)
                write(archive / ('system-python-%d.json' % time.time_ns()), trial)
                trial.update(status='queued_preflight', queue_reason='resume_with_repository_python')
                write(path, trial)
                parked[rid] = slot
                pending.append(rid)
                retries[rid] = 1
            elif status in {'generation_incomplete_candidate_frozen','recovery_failed'}:
                from tools.l3_api_control import is_transient
                event_file=path.parent/'agent-events.jsonl'
                if trial.get('recovery_directory'):
                    event_file=Path(trial['recovery_directory'])/'agent-events.jsonl'
                tail=event_file.read_text(errors='replace')[-24000:] if event_file.exists() else ''
                if not balance and is_transient(tail):
                    recoveries[rid]='resume_preserved_candidate_after_transient_failure'
                    pending.append(rid)
                else:
                    failures[rid]=status
            else:
                failures[rid] = status
            del active[slot]
            children.pop(slot, None)
            save()
        if not balance:
            for slot in slots:
                n = slot['slot']
                if n in active:
                    continue
                rid = choose_next(pending, byid, parked, n)
                if rid is None:
                    continue
                run = byid[rid]
                output = ROOT / run['output']
                resuming = rid in parked
                if rid in recoveries:
                    command = [sys.executable, str(ROOT / 'tools/recover_l3_generation.py'),
                               '--output', str(output), '--engine', slot['engine'], '--gpu', str(slot['gpu'])]
                elif resuming:
                    from tools.resume_l3_preflight import validate_parked
                    expected = validate_parked(output)
                    if expected['engine_copy'] != slot['engine']:
                        raise RuntimeError('Parked engine mismatch')
                    command = [sys.executable, str(ROOT / 'tools/resume_l3_preflight.py'), '--output', str(output)]
                else:
                    if output.exists():
                        raise RuntimeError('Refusing duplicate dispatch: ' + rid)
                    command = [sys.executable, str(ROOT / 'tools/run_l3_suite.py'), '--manifest', state['manifest'],
                               '--model', run['model'], '--tasks', run['task_key'], '--engine', slot['engine'],
                               '--gpu', str(slot['gpu']), '--shared-gpu', '--generate']
                logfile = control / ('queue-%02d-%s-%d.log' % (n, rid, time.time_ns()))
                with logfile.open('x') as log:
                    child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, env=env, start_new_session=True)
                pending.remove(rid)
                parked.pop(rid, None)
                active[n] = {'run_id': rid, 'pid': child.pid, 'adopted': False, 'resumed_preflight': resuming, 'log': str(logfile)}
                children[n] = child
                save()
        rows = []
        for run in runs:
            root = ROOT / run['output']
            row = {k: run[k] for k in ['id', 'task_key', 'model', 'output']}
            row['status'] = 'queued' if run['id'] in pending else 'preparing'
            try:
                if (root / 'trial.json').exists():
                    trial = json.loads((root / 'trial.json').read_text())
                    row.update(status=trial['status'], generation_seconds=trial.get('elapsed_seconds'),
                               started_unix=trial.get('started_unix'), finished_unix=trial.get('finished_unix'))
            except (ValueError, OSError):
                row['status'] = 'status_write_in_progress'
            if (root / 'model-requests.jsonl').exists():
                row['usage'] = summarize_requests(root / 'model-requests.jsonl')
            rows.append(row)
        status = ('completed' if len(completed) == len(runs) else 'stopped_api_balance_exhausted' if balance and not active
                  else 'stopping_api_balance_exhausted' if balance else 'requires_inspection' if not active and not pending else 'running')
        save()
        write(control / 'summary.json', dict(status=status, updated_unix=time.time(), supervisor_pid=os.getpid(),
              completed=len(completed), expected=len(runs), api_concurrency_limit=10, task_concurrency_limit=10,
              active_workers=active, pending_runs=pending, parked_runs=parked, failed_runs=failures, slots=slots, runs=rows))
        if status in {'completed', 'stopped_api_balance_exhausted', 'requires_inspection'}:
            break
        time.sleep(5)


if __name__ == '__main__':
    main()
