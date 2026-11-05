import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.l3_generation_retry import run_generation, resumable_session

SESSION = '12345678-1234-1234-1234-123456789abc'
COMMAND = ['docker', 'exec', '-i', 'container', 'codex', 'exec', '--json', '--output-last-message', '/workspace/agent-final.txt', '-']


def test_resume_preserves_deadline_and_history(tmp_path):
    now = [0]
    calls = []
    def fake(command, prompt, root, budget, **kwargs):
        calls.append((command, budget, kwargs))
        now[0] += 20
        events = ([{'type': 'thread.started', 'thread_id': SESSION}] if len(calls) == 1 else [])
        events += [{'type': 'turn.failed', 'error': {'message': 'Our servers are overloaded'}}] if len(calls) == 1 else [{'type': 'turn.completed'}]
        with (root / 'agent-events.jsonl').open('a') as f:
            for e in events: f.write(json.dumps(e) + '\n')
        return {'generation_status': 'process_error' if len(calls) == 1 else 'completed', 'return_code': 1 if len(calls) == 1 else 0, 'model_error_events': 1, 'unfinished_tool_ids': [], 'tool_spans': []}
    value = run_generation(COMMAND, b'task', tmp_path, 100, runner=fake, clock=lambda: now[0], sleep=lambda n: now.__setitem__(0, now[0] + n))
    assert [c[1] for c in calls] == [100, 65]
    assert calls[1][0][-2] == SESSION
    assert calls[1][2] == {'append': True, 'elapsed_offset': 35}
    assert value['elapsed_seconds'] == 55
    assert value['resumes'] == 1
    assert value['generation_status'] == 'completed'


def test_backoff_cannot_extend_budget(tmp_path):
    now = [0]
    def fake(command, prompt, root, budget, **kwargs):
        now[0] += 95
        (root / 'agent-events.jsonl').write_text('\n'.join(json.dumps(e) for e in [{'type':'thread.started','thread_id':SESSION},{'type':'turn.failed','error':{'message':'overloaded'}}]))
        return {'generation_status':'process_error','return_code':1,'unfinished_tool_ids':[]}
    value = run_generation(COMMAND, b'task', tmp_path, 100, runner=fake, clock=lambda: now[0], sleep=lambda n: now.__setitem__(0, now[0] + n))
    assert value['elapsed_seconds'] == 100
    assert value['attempts'] == 1
    assert value['generation_status'] == 'timeout'


def test_auth_and_success_are_not_retried():
    start = {'type':'thread.started','thread_id':SESSION}
    assert resumable_session([start, {'type':'turn.failed','error':{'message':'Invalid API key'}}]) is None
    assert resumable_session([start, {'type':'error','message':'overloaded'}, {'type':'turn.completed'}]) is None


def test_ephemeral_is_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError, match='persist'):
        run_generation(COMMAND + ['--ephemeral'], b'task', tmp_path, 100)


def test_retry_limit_and_unfinished_tool_guard(tmp_path):
    now = [0]
    calls = [0]
    unfinished = [False]
    def fake(command, prompt, root, budget, **kwargs):
        calls[0] += 1
        now[0] += 1
        with (root / 'agent-events.jsonl').open('a') as f:
            for event in [{'type':'thread.started','thread_id':SESSION},{'type':'turn.failed','error':{'message':'overloaded'}}]:
                f.write(json.dumps(event) + '\n')
        return {'generation_status':'process_error','return_code':1,'unfinished_tool_ids':['running-tool'] if unfinished[0] else []}
    value = run_generation(COMMAND, b'task', tmp_path, 100, max_resumes=2, runner=fake, clock=lambda:now[0], sleep=lambda n:now.__setitem__(0,now[0]+n))
    assert calls[0] == 3
    assert value['retry_stop_reason'] == 'resume_limit_reached'
    calls[0] = 0
    unfinished[0] = True
    value = run_generation(COMMAND, b'task', tmp_path, 100, runner=fake, clock=lambda:now[0], sleep=lambda n:now.__setitem__(0,now[0]+n))
    assert calls[0] == 1
    assert value['retry_stop_reason'] == 'unfinished_tools_prevent_safe_resume'


def test_default_retries_past_two_resumes_until_success(tmp_path):
    now = [0]
    calls = [0]
    def fake(command, prompt, root, budget, **kwargs):
        calls[0] += 1
        now[0] += 1
        success = calls[0] == 5
        events = [{'type':'thread.started','thread_id':SESSION}] if calls[0] == 1 else []
        events += [{'type':'turn.completed'}] if success else [{'type':'turn.failed','error':{'message':'overloaded'}}]
        with (root / 'agent-events.jsonl').open('a') as f:
            for event in events: f.write(json.dumps(event) + '\n')
        return {'generation_status':'completed' if success else 'process_error','return_code':0 if success else 1,'unfinished_tool_ids':[]}
    value = run_generation(COMMAND, b'task', tmp_path, 200, runner=fake, clock=lambda:now[0], sleep=lambda n:now.__setitem__(0,now[0]+n))
    assert calls[0] == 5
    assert value['resumes'] == 4
    assert value['elapsed_seconds'] == 110
    assert value['generation_status'] == 'completed'


def test_resume_preserves_explicit_model_and_never_silently_switches():
    from tools.l3_generation_retry import resume_command
    cmd = COMMAND[:-1] + ['--model', 'gpt-6-astra', '-']
    resumed = resume_command(cmd, SESSION)
    assert resumed[resumed.index('--model') + 1] == 'gpt-6-astra'
    assert '--model' not in resume_command(COMMAND, SESSION)

def test_transient_unfinished_tools_reconciled_before_resuming(tmp_path):
    calls=[]; reconciled=[]
    def fake(command,prompt,root,budget,**kwargs):
        calls.append(command)
        events=[{'type':'thread.started','thread_id':SESSION},
                {'type':'turn.failed','error':{'message':'429 rate limit'}}] if len(calls)==1 else [{'type':'turn.completed'}]
        with (root/'agent-events.jsonl').open('a') as f:
            for e in events:f.write(json.dumps(e)+'\n')
        return {'generation_status':'process_error' if len(calls)==1 else 'completed',
                'return_code':1 if len(calls)==1 else 0,
                'unfinished_tool_ids':['tool'] if len(calls)==1 else []}
    value=run_generation(COMMAND,b'task',tmp_path,None,runner=fake,sleep=lambda n:None,
                         reconcile_unfinished=lambda v:reconciled.append(v['unfinished_tool_ids']))
    assert reconciled==[['tool']]
    assert len(calls)==2 and calls[1][-2]==SESSION
    assert value['generation_status']=='completed'
