"""Continue one persisted authoring session until delivery, deadline or balance exhaustion."""
import json,time,uuid
from tools.l3_usage import timed_generation
from tools.l3_api_control import stopped,is_balance_error,is_transient,mark_balance_exhausted

def read_events(path):
 events=[]
 if path.exists():
  for line in path.read_text(errors='replace').splitlines():
   try:events.append(json.loads(line))
   except ValueError:pass
 return events

def latest_session(events):
 for event in reversed(events):
  if event.get('type')=='thread.started':
   try:return str(uuid.UUID(event['thread_id']))
   except (ValueError,KeyError,TypeError):return None
 return None

def resumable_session(events):
 terminals=[e for e in events if e.get('type') in {'turn.failed','turn.completed'}]
 if not terminals or terminals[-1]['type']!='turn.failed' or not is_transient(json.dumps(terminals[-1])):return None
 return latest_session(events)

def resume_command(command,session):
 index=command.index('codex');output=command[command.index('--output-last-message')+1]
 model_args=['--model',command[command.index('--model')+1]] if '--model' in command else []
 return command[:index+1]+['exec','resume','--dangerously-bypass-approvals-and-sandbox','--skip-git-repo-check','--json']+model_args+['--output-last-message',output,session,'-']

def run_generation(command,prompt,root,budget,max_resumes=None,runner=timed_generation,clock=time.monotonic,sleep=time.sleep,completion_feedback=None,reconcile_unfinished=None):
 if '--ephemeral' in command:raise ValueError('Generation must persist its session before resuming is enabled')
 start=clock();attempts=[];original=list(command);original_prompt=prompt;stop_reason=None;continuations=0
 while True:
  if stopped():stop_reason='api_balance_exhausted';break
  remaining=None if budget is None else budget-(clock()-start)
  if remaining is not None and remaining<=0:stop_reason='deadline_reached';break
  prior_events=len(read_events(root/'agent-events.jsonl')) if attempts else 0
  value=runner(command,prompt,root,remaining,append=bool(attempts),elapsed_offset=clock()-start)
  attempts.append(value);(root/('generation-attempt-%03d.json'%len(attempts))).write_text(json.dumps(value,indent=2)+'\n')
  events=read_events(root/'agent-events.jsonl');recent=events[prior_events:];error_text=json.dumps([e for e in recent if e.get('type') in {'turn.failed','error'}],ensure_ascii=False)
  if stopped() or value['generation_status']=='api_balance_exhausted' or is_balance_error(None,error_text):
   mark_balance_exhausted(None,None);stop_reason='api_balance_exhausted';break
  completed=value['generation_status']=='completed'
  feedback=completion_feedback(value) if completed and completion_feedback else None
  if completed and not feedback:break
  if not completed and value['generation_status']!='process_error':break
  if value.get('unfinished_tool_ids'):
   if not completed and is_transient(error_text) and reconcile_unfinished:
    reconcile_unfinished(value)
   else:
    stop_reason='unfinished_tools_prevent_safe_resume';break
  if max_resumes is not None and len(attempts)>max_resumes:stop_reason='resume_limit_reached';break
  if completed:
   session=latest_session(events)
   if session is None:stop_reason='missing_session_for_delivery_continuation';break
   continuations+=1
   command=resume_command(original,session)
   prompt=('Continue the same task in the same workspace. Finish the publicly required deliverables and validate them before ending. '+str(feedback)+' Do not reset or replace your workspace with a fresh attempt.').encode()
   (root/('delivery-continuation-%03d.json'%continuations)).write_text(json.dumps({'feedback':feedback,'session':session,'elapsed_seconds':clock()-start},indent=2)+'\n')
   continue
  if not any(e.get('type')=='turn.failed' for e in recent):
   # A connection can fail before the first streamed event/session identifier.
   raw=(root/'agent-events.jsonl').read_text(errors='replace')[-16000:]
   if not is_transient(raw):stop_reason='no_new_terminal_failure';break
  session=resumable_session(events)
  if session is None and not (latest_session(events) is None and is_transient(error_text+(root/'agent-events.jsonl').read_text(errors='replace')[-16000:])):
   stop_reason='no_resumable_transient_failure';break
  remaining=None if budget is None else budget-(clock()-start)
  delay=min(15*len(attempts),120) if remaining is None else min(15*len(attempts),30,max(0,remaining))
  sleep(delay)
  remaining=None if budget is None else budget-(clock()-start)
  if remaining is not None and remaining<=0:stop_reason='deadline_reached';break
  command=resume_command(original,session) if session else original
  prompt=(('Continue the same task from your saved session and workspace. The previous turn stopped due to a transient model-service failure. '+(f'The original deadline is unchanged; approximately {int(remaining)} seconds remain. ' if remaining is not None else 'Finish the original deliverables without a fixed deadline. ')+'Inspect any interrupted work before continuing.').encode() if session else original_prompt)
 result=dict(attempts[-1]) if attempts else {'return_code':None,'unfinished_tool_ids':[],'generation_status':'not_started'}
 result.update(elapsed_seconds=clock()-start,model_error_events=sum(a.get('model_error_events',0) for a in attempts),tool_spans=[s for a in attempts for s in a.get('tool_spans',[])],attempts=len(attempts),resumes=max(0,len(attempts)-1),delivery_continuations=continuations,retry_stop_reason=stop_reason,budget_seconds=budget)
 if stop_reason=='deadline_reached':result['generation_status']='timeout'
 if stop_reason=='api_balance_exhausted':result['generation_status']='api_balance_exhausted'
 (root/'generation-timing.json').write_text(json.dumps(result,indent=2)+'\n');return result
