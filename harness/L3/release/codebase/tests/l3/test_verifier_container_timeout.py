import json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.verify_l3_submission import start_verifier_container,stop_verifier_container

class ContainerTimeouts(unittest.TestCase):
 def test_start_timeout_preserves_partial_output_and_fails(self):
  with tempfile.TemporaryDirectory() as root:
   p=Path(root)
   with patch('tools.verify_l3_submission.subprocess.run',side_effect=subprocess.TimeoutExpired(['docker'],180,output=b'partial')) as run:
    with self.assertRaisesRegex(RuntimeError,'startup timed out'):
     start_verifier_container(['docker','start','own'],p)
   self.assertEqual(run.call_args.kwargs['timeout'],180)
   self.assertIn('partial',(p/'container-start.log').read_text())
 def test_stop_timeout_records_failure_without_discarding_result(self):
  with tempfile.TemporaryDirectory() as root:
   p=Path(root);(p/'run.json').write_text('{"status":"collected"}')
   with patch('tools.verify_l3_submission.subprocess.run',side_effect=subprocess.TimeoutExpired(['docker'],30)):
    stop_verifier_container('own',p)
   self.assertTrue(json.loads((p/'container-stop.json').read_text())['timed_out'])
   self.assertEqual(json.loads((p/'run.json').read_text())['status'],'collected')

class SuiteContainerTimeouts(unittest.TestCase):
 def test_inspect_and_cleanup_timeouts_leave_retryable_failure(self):
  from harness.L3.Suite.collect import collect
  with tempfile.TemporaryDirectory() as root:
   folder=Path(root);(folder/'source.json').write_text('{}')
   def timeout(command,**kwargs):
    expected=20 if command[1]=='inspect' else 30
    self.assertEqual(kwargs['timeout'],expected)
    raise subprocess.TimeoutExpired(command,expected)
   with patch('harness.L3.Suite.collect.prepare',return_value=folder),patch('harness.L3.Suite.collect.subprocess.run',side_effect=timeout):
    with self.assertRaises(subprocess.TimeoutExpired):
     collect('l3-e03',folder/'engine',0)
   self.assertEqual(json.loads((folder/'run.json').read_text())['status'],'failed')
   self.assertTrue(json.loads((folder/'container-stop.json').read_text())['timed_out'])
