import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from tools.l3_delivery import terminal_complete,delivery_feedback
from tools import l3_leaderboard_batch as b
GOOD={'generation_status':'completed','terminal_event':'turn.completed','return_code':0}
class DeliveryTerminal(unittest.TestCase):
 def test_files_alone_cannot_override_agent_error(self):
  with tempfile.TemporaryDirectory() as t:
   w=Path(t);(w/'project').mkdir()
   with patch('tools.l3_trial_status.completion_evidence',return_value={'missing_delivery_evidence':[]}):
    self.assertIsNone(delivery_feedback(w,GOOD,False))
    self.assertIn('normal agent completion',delivery_feedback(w,{**GOOD,'return_code':1},False))
 def test_success_requires_all_terminal_fields(self):
  self.assertTrue(terminal_complete(GOOD))
  for key in GOOD:
   self.assertFalse(terminal_complete({k:v for k,v in GOOD.items() if k!=key}))
 def test_recovery_keeps_candidate_and_paused_results(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);rows=[]
   for name,enabled,timing in [('bad',True,{}),('good',True,GOOD),('paused',False,{})]:
    out=root/name;(out/'workspace').mkdir(parents=True);(out/'workspace/candidate').write_text('authored')
    b.write(out/'state.json',{'status':'generated','slot':22});b.write(out/'trial.json',{'status':'generated'})
    b.write(out/'generation-timing.json',timing);b.write(out/'submission-manifest.json',{'files':{}})
    rows.append({'id':name,'output':str(out),'enabled':enabled,'status':'queued'})
   b.write(root/'manifest.json',{'rows':rows})
   with patch.object(b,'B',root),patch.object(b,'process_matches',return_value=False),patch.object(b,'trial_agent_live',return_value=False):
    self.assertEqual(b.recover_incomplete_deliveries(),['bad'])
   self.assertEqual(b.read(root/'bad/state.json')['failed_unix'],0)
   self.assertEqual((root/'bad/workspace/candidate').read_text(),'authored')
   self.assertEqual(b.read(root/'good/state.json')['status'],'generated')
   self.assertEqual(b.read(root/'paused/state.json')['status'],'generated')
   self.assertTrue(list((root/'bad/infrastructure-attempts').glob('*/submission-manifest.json')))
if __name__=='__main__':unittest.main()
