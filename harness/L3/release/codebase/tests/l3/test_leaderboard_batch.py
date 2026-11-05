import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.l3_model_bridge import model_payload,upstream_headers,image_count
from tools.l3_batch_control import MultiUsageParser,observe_status,limit
from tools.prepare_l3_trial import codex_config
from tools.l3_leaderboard_batch import VARIANTS,process_matches,probe_ready,native_command,next_attempt

class MatrixTests(unittest.TestCase):
 def test_native_retry_launch_resets_status_without_name_error(self):
  import ast,inspect,types
  from tools.l3_leaderboard_batch import worker
  tree=ast.parse(inspect.getsource(worker))
  calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="update" and any(k.arg=="agent_pid" for k in n.keywords)]
  self.assertEqual(len(calls),1)
  statement=ast.fix_missing_locations(ast.Module(body=[ast.Expr(value=calls[0])],type_ignores=[]))
  for old in ["retry_wait","delivery_continuation"]:
   with self.subTest(old=old):
    status={"status":old}
    exec(compile(statement,"native-launch","exec"),{"status":status,"proc":types.SimpleNamespace(pid=123),"n":2,"started":456})
    self.assertEqual(status,{"status":"generating","agent_pid":123,"attempt":2,"last_attempt_started_unix":456})
 def test_provider_configured_ceiling_and_throttling(self):
  from tools.l3_batch_control import provider_maximum
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'L3_EXPERIMENT_BATCH':d,'L3_MODEL_GROUP':'china'}):
   (Path(d)/'settings.json').write_text(json.dumps({'api_concurrency':{'china':12}}))
   self.assertEqual(provider_maximum(),12);self.assertEqual(limit()['limit'],12)
   observe_status(429);self.assertEqual(limit()['limit'],6)
   with patch('tools.l3_batch_control.time.time',return_value=10**12):
    for _ in range(40):observe_status(200)
   self.assertEqual(limit()['limit'],7)
 def test_engine_slot_count_tracks_worker_caps(self):
  from tools import l3_leaderboard_batch as batch
  with tempfile.TemporaryDirectory() as d,patch.object(batch,'B',Path(d)):
   (Path(d)/'settings.json').write_text(json.dumps({'group_workers':{'openai':8,'claude':8,'china':12}}))
   self.assertEqual(batch.engine_slot_count(),28)
 def test_text_probe_does_not_admit_image_tasks(self):
  self.assertFalse(probe_ready({'status':'passed'}))
  self.assertFalse(probe_ready({'status':'passed','reference_image_count':0}))
  self.assertFalse(probe_ready({'status':'passed','reference_image_count':4}))
  self.assertTrue(probe_ready({'status':'passed','reference_image_count':4,'image_observed_in_model_request':True}))
  self.assertFalse(probe_ready({'status':'failed','reference_image_count':4}))
 def test_api_image_count(self):
  self.assertEqual(image_count({'messages':[{'content':[{'type':'image','source':{'type':'base64','data':'test'}}]}]}),1)
  self.assertEqual(image_count({'input':[{'content':[{'type':'input_image','image_url':'data:test'}]}]}),1)
  self.assertEqual(image_count({'messages':[{'content':[{'type':'image_url','image_url':{'url':'data:test'}}]}]}),1)
  self.assertEqual(image_count({'input':'Read the reference image.'}),0)
  self.assertEqual(image_count({'tools':[{'parameters':{'type':['object','null']}}]}),0)
 def test_dsh_permission_applies_only_inside_container_command(self):
  row={'harness':'dsh','model':'deepseek-v4.1-flash','effort':'max'}
  cmd=native_command(row,'/workspace/prompt','/workspace/result',[])
  self.assertEqual(cmd[:2],['env','DSH_PERMISSION_MODE=danger-full-access'])
  self.assertEqual(cmd[2],'python3')
  row['harness']='codex'
  self.assertEqual(native_command(row,'p','r',[])[0],'python3')
 def test_interrupted_attempt_log_is_never_overwritten(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'workspace').mkdir()
   (root/'attempt-0001.json').write_text('{}')
   (root/'agent-events-0003.jsonl').write_text('interrupted')
   self.assertEqual(next_attempt(root),4)
 def test_scope(self):
  self.assertEqual(len(VARIANTS),11)
  self.assertEqual(len([r for r in VARIANTS if r[0]=='qwen3.8-max' and r[1]=='claude' and r[3]=='xhigh']),1)
  self.assertFalse(any('gemini' in m for m,*_ in VARIANTS))
  self.assertTrue(any(m=='kimi-k3.1-pro' for m,*_ in VARIANTS))
  for model in ['gpt-6-astra','gpt-6-luna','gpt-6.1-sol']:
   self.assertEqual({e for m,h,g,e in VARIANTS if m==model},{'max'})
 def test_effort_preserved(self):
  for m,h,g,e in VARIANTS:
   route='/v1/responses' if h=='codex' else '/v1/messages' if h=='claude' else '/v1/chat/completions'
   data=json.loads(model_payload(b'{"model":"wrong","reasoning":{"effort":"high"}}',route,{'L3_EXPECTED_MODEL':m,'L3_EXPECTED_EFFORT':e}))
   self.assertEqual(data['model'],m)
   actual=data['reasoning']['effort'] if h=='codex' else data['output_config']['effort'] if h=='claude' else data['reasoning_effort']
   self.assertEqual(actual,e)
 def test_legacy_default(self):
  self.assertEqual(json.loads(model_payload(b'{}','/v1/responses',{'L3_EXPECTED_MODEL':'m'}))['reasoning']['effort'],'high')
  self.assertIn('model_reasoning_effort="medium"',codex_config('gpt-6-astra','medium'))
 def test_auth_not_forwarded(self):
  h=upstream_headers({'X-Api-Key':'dummy','Authorization':'Bearer bad','Content-Type':'application/json'},'host-secret')
  self.assertNotIn('x-api-key',h);self.assertEqual(h['authorization'],'Bearer host-secret')
 def test_anthropic_usage(self):
  p=MultiUsageParser()
  for v in [{'type':'message_start','message':{'id':'abc','usage':{'input_tokens':4,'cache_read_input_tokens':20,'cache_creation_input_tokens':6}}},{'type':'message_delta','usage':{'output_tokens':7}},{'type':'message_stop'}]:p.feed(('data: '+json.dumps(v)+'\n\n').encode())
  p.finish();self.assertEqual(p.usage['input_tokens'],30);self.assertEqual(p.usage['output_tokens'],7);self.assertEqual(p.usage['total_tokens'],37)
 def test_chat_usage(self):
  p=MultiUsageParser();p.feed(b'data: {"usage":{"prompt_tokens":40,"completion_tokens":8,"prompt_tokens_details":{"cached_tokens":10}},"choices":[]}\n\n');p.finish();self.assertEqual(p.usage['total_tokens'],48)
 def test_nonstream_usage(self):
  p=MultiUsageParser();p.feed(b'{"usage":{"prompt_tokens":40,"completion_tokens":8}}');p.finish();self.assertEqual(p.usage['total_tokens'],48)
 def test_provider_limits_isolated(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'L3_EXPERIMENT_BATCH':d,'L3_MODEL_GROUP':'china'}):
   self.assertEqual(limit()['limit'],4);observe_status(429);self.assertEqual(limit()['limit'],2)
   with patch.dict(os.environ,{'L3_MODEL_GROUP':'openai'}):self.assertEqual(limit()['limit'],16)
   self.assertEqual(limit()['limit'],2)
 def test_no_pid_false_positive(self):self.assertFalse(process_matches(None,'l3_leaderboard_batch'))
if __name__=='__main__':unittest.main()
