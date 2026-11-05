import json,threading,time
from pathlib import Path
from tools.l3_api_control import api_slot,stopped,is_balance_error,is_transient,mark_balance_exhausted,BalanceExhausted
from tools.l3_generation_retry import run_generation
import pytest

def test_rate_limit_does_not_mean_balance_exhaustion():
 assert not is_balance_error(429,{'message':'rate limit exceeded'})
 assert is_transient('HTTP 429 rate limit exceeded')
 assert is_balance_error(429,{'code':'insufficient_quota'})
 assert is_balance_error(403,{'message':'用户额度不足'})
 assert not is_transient('insufficient_quota')
 assert is_transient('error sending request: connection closed')

def test_shared_concurrency_and_balance_guard(tmp_path,monkeypatch):
 monkeypatch.setenv('L3_BATCH_CONTROL',str(tmp_path));monkeypatch.setenv('L3_API_CONCURRENCY','2')
 acquired=threading.Event()
 def reserve():
  with api_slot():acquired.set()
 with api_slot():
  with api_slot():
   t=threading.Thread(target=reserve);t.start();assert not acquired.wait(.4)
  assert acquired.wait(2)
 t.join();mark_balance_exhausted(402,'gpt-5.6-luna');assert stopped()
 with pytest.raises(BalanceExhausted):
  with api_slot():pass
 assert json.loads((tmp_path/'balance-exhausted.json').read_text())['reason']=='api_balance_exhausted'

def test_completed_turn_continues_for_missing_public_delivery(tmp_path):
 calls=[];session='12345678-1234-1234-1234-123456789abc'
 def runner(command,prompt,root,budget,**kwargs):
  calls.append((command,prompt,kwargs))
  with (root/'agent-events.jsonl').open('a') as f:
   for event in [{'type':'thread.started','thread_id':session},{'type':'turn.completed'}]:f.write(json.dumps(event)+'\n')
  return {'generation_status':'completed','terminal_event':'turn.completed','return_code':0,'unfinished_tool_ids':[]}
 result=run_generation(['codex','exec','--model','gpt-5.6-luna','--output-last-message','final','-'],b'task',tmp_path,None,runner=runner,completion_feedback=lambda result:'README is missing' if len(calls)==1 else None)
 assert len(calls)==2 and calls[1][0][-2]==session
 assert calls[1][2]['append']
 assert b'README is missing' in calls[1][1]
 assert result['delivery_continuations']==1

def test_existing_balance_stop_makes_no_model_call(tmp_path,monkeypatch):
 monkeypatch.setenv('L3_BATCH_CONTROL',str(tmp_path));mark_balance_exhausted(402,'gpt-6-astra')
 def forbidden(*a,**kw):raise AssertionError('No model request allowed')
 result=run_generation(['codex','exec','--output-last-message','final','-'],b'task',tmp_path,None,runner=forbidden)
 assert result['generation_status']=='api_balance_exhausted' and result['attempts']==0

def test_ten_slot_limit_includes_legacy_two_slot_gateways(tmp_path,monkeypatch):
 from contextlib import ExitStack
 monkeypatch.setenv("L3_BATCH_CONTROL",str(tmp_path));monkeypatch.setenv("L3_API_CONCURRENCY","2")
 acquired=threading.Event()
 def eleventh():
  with api_slot():acquired.set()
 with ExitStack() as legacy:
  legacy.enter_context(api_slot());legacy.enter_context(api_slot())
  monkeypatch.setenv("L3_API_CONCURRENCY","10")
  with ExitStack() as expanded:
   for _ in range(8):expanded.enter_context(api_slot())
   t=threading.Thread(target=eleventh);t.start();assert not acquired.wait(.4)
  assert acquired.wait(2)
 t.join()


def test_wrapped_upstream_failure_retries_but_invalid_requests_do_not():
 wrapped={'error':{'message':'Upstream request failed','type':'upstream_error'}}
 assert is_transient(json.dumps(wrapped))
 assert is_transient(json.dumps({'type':'turn.failed','error':{'message':json.dumps(wrapped)}}))
 assert not is_transient('HTTP 400 '+json.dumps({'error':{'type':'invalid_request_error','message':'Unknown model'}}))
 assert not is_transient(json.dumps({'error':{'type':'upstream_error','message':'insufficient_quota'}}))


def test_wrapped_upstream_failure_resumes_same_luna_session(tmp_path):
 calls=[];session='12345678-1234-1234-1234-123456789abc'
 def runner(command,prompt,root,budget,**kwargs):
  calls.append(command)
  event={'type':'turn.failed','error':{'message':json.dumps({'error':{'type':'upstream_error','message':'Upstream request failed'}})}} if len(calls)==1 else {'type':'turn.completed'}
  with (root/'agent-events.jsonl').open('a') as f:
   for item in [{'type':'thread.started','thread_id':session},event]:f.write(json.dumps(item)+'\n')
  return {'generation_status':'process_error' if len(calls)==1 else 'completed','return_code':1 if len(calls)==1 else 0,'unfinished_tool_ids':[]}
 result=run_generation(['codex','exec','--model','gpt-6-luna','--output-last-message','final','-'],b'task',tmp_path,None,runner=runner,sleep=lambda _:None)
 assert result['generation_status']=='completed' and len(calls)==2
 assert calls[1][-2]==session and 'gpt-6-luna' in calls[1]
