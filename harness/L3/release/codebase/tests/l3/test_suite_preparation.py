import json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.validate_l3_suite import check_hashes,sha,validate
from tools.l3_generation_retry import run_generation

def test_package_hash_rejects_changed_file_and_escape(tmp_path):
 p=tmp_path/'input.txt';p.write_text('original');digest=sha(p);check_hashes(tmp_path,{'input.txt':digest})
 p.write_text('changed')
 with pytest.raises(ValueError,match='changed'):check_hashes(tmp_path,{'input.txt':digest})
 with pytest.raises(ValueError,match='outside'):check_hashes(tmp_path,{'../outside':digest})

def test_open_ended_run_resumes_transient_failure_same_model(tmp_path):
 now=[0];calls=[];session='12345678-1234-1234-1234-123456789abc'
 cmd=['codex','exec','--model','gpt-6-astra','--json','--output-last-message','/workspace/agent-final.txt','-']
 def runner(command,prompt,root,budget,**kwargs):
  calls.append((command,prompt,budget,kwargs));now[0]+=4000
  events=[{'type':'thread.started','thread_id':session},{'type':'turn.failed','error':{'message':'HTTP 503 overloaded'}}] if len(calls)==1 else [{'type':'turn.completed'}]
  with (root/'agent-events.jsonl').open('a') as f:
   for event in events:f.write(json.dumps(event)+'\n')
  return {'generation_status':'process_error' if len(calls)==1 else 'completed','return_code':1 if len(calls)==1 else 0,'unfinished_tool_ids':[]}
 result=run_generation(cmd,b'task',tmp_path,None,runner=runner,clock=lambda:now[0],sleep=lambda t:now.__setitem__(0,now[0]+t))
 assert result['generation_status']=='completed' and result['elapsed_seconds']==8015
 assert all(c[2] is None for c in calls)
 assert calls[1][0][-2]==session and 'gpt-6-astra' in calls[1][0]
 assert b'without a fixed deadline' in calls[1][1]
 assert result['resumes']==1

def test_frozen_suite_and_paired_manifest():
 root=Path(__file__).resolve().parents[2];batch=root/'tasks/L3/generation-batch.json'
 if not batch.exists():pytest.skip('Server preparation artifacts required')
 report=validate(root,batch,libraries=False)
 assert report['passed'] and report['planned_runs']==json.loads(batch.read_text())['total_runs']
 assert sum(t['references'] for t in report['tasks'])==23
 assert sum(t['input_mode']=='text' for t in report['tasks'])==5


def test_multimodel_manifest_rejects_missing_task_for_one_model(tmp_path):
 root=Path(__file__).resolve().parents[2]
 source=root/'tasks/L3/generation-batch.json'
 if not source.exists():pytest.skip('Server preparation artifacts required')
 value=json.loads(source.read_text())
 value['runs']=[r for r in value['runs'] if r['id']!='l3-g02-astra']
 value['total_runs']=len(value['runs'])
 p=tmp_path/'batch.json';p.write_text(json.dumps(value))
 with pytest.raises(AssertionError):validate(root,p,libraries=False)
