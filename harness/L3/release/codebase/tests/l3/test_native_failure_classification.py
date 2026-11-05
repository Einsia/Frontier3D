import json,unittest
from tools.l3_leaderboard_batch import native_configuration_failure
class NativeFailure(unittest.TestCase):
 def test_candidate_command_error_is_not_configuration(self):
  log='\n'.join(json.dumps(x) for x in [
   {'type':'user','tool_use_result':{'stdout':'/bin/bash: line 1: free: command not found'}},
   {'type':'result','is_error':True,'terminal_reason':'api_error','result':"API Error: JSON Parse error: Unexpected token '('"},
   {'type':'native_runner.finished','return_code':1}])
  self.assertFalse(native_configuration_failure(log))
 def test_genuine_terminal_configuration_error(self):
  for error in ['invalid api key','unsupported model','unsupported effort','invalid reasoning']:
   self.assertTrue(native_configuration_failure(json.dumps({'type':'result','is_error':True,'result':error})))
 def test_native_cli_option_error(self):
  self.assertTrue(native_configuration_failure('error: unknown option --invalid'))
 def test_reasoning_and_tool_outputs_are_not_configuration(self):
  self.assertFalse(native_configuration_failure(json.dumps({'type':'item.completed','item':{'type':'reasoning','text':'unknown option'}})))
  self.assertFalse(native_configuration_failure(json.dumps({'type':'item.completed','item':{'type':'command_execution','aggregated_output':'error: unsupported model'}})))
 def test_transient_errors_remain_retryable(self):
  for msg in ['HTTP524 timeout','API Error: 429 overload',"JSON Parse error: Unexpected token '('"]:
   self.assertFalse(native_configuration_failure(json.dumps({'type':'error','message':msg})))

class Recovery(unittest.TestCase):
 def test_recovery_preserves_evidence_and_leaves_paused_or_live_alone(self):
  import tempfile
  from pathlib import Path
  from unittest.mock import patch
  from tools import l3_leaderboard_batch as b
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);rows=[]
   for name,enabled in [('stopped',True),('paused',False),('live',True)]:
    out=root/name;(out/'workspace').mkdir(parents=True)
    rows.append({'id':name,'enabled':enabled,'status':'queued','output':str(out)})
    b.write(out/'state.json',{'status':'failed','error':'Native configuration failure; see preserved attempt log','attempt':1,'pid':name,'agent_pid':None})
    b.write(out/'workspace/native-result-0001.json',{'return_code':1,'completed':False})
    (out/'agent-events-0001.jsonl').write_text(json.dumps({'type':'result','is_error':True,'result':'API Error: JSON Parse error'}))
   b.write(root/'manifest.json',{'rows':rows})
   with patch.object(b,'B',root),patch.object(b,'process_matches',side_effect=lambda pid,part:pid=='live'):
    self.assertEqual(b.recover_misclassified_native_errors(),['stopped'])
   self.assertEqual(b.read(root/'stopped/state.json')['failed_unix'],0)
   self.assertTrue(list((root/'stopped/infrastructure-attempts').glob('*.json')))
   for name in ['paused','live']:
    self.assertEqual(b.read(root/name/'state.json')['error'],'Native configuration failure; see preserved attempt log')

if __name__=='__main__':unittest.main()
