import json,tempfile,unittest
from pathlib import Path
from harness.L3.Suite.replay_budget import retry_budget
class ReplayBudget(unittest.TestCase):
 def test_slow_matching_replay_gets_time_without_plan_change(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);a=p/'workflow-failed-1';a.mkdir()
   plan={'steps':[{'seconds':255.15}]};original=json.dumps(plan)
   (a/'plan.json').write_text(original)
   for i,t in enumerate([0,160.8]):(a/f'trajectory_{i:05}.json').write_text(json.dumps({'time':t}))
   log=p/'workflow.log';log.write_text('Command timed out after 3961s')
   budget,evidence=retry_budget(plan,p,'workflow',log)
   self.assertGreater(budget,9000);self.assertTrue(evidence)
   self.assertEqual(json.dumps(plan),original)
 def test_non_timeout_failure_or_unrelated_plan_stays_default(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);a=p/'workflow-failed-1';a.mkdir();plan={'steps':[{'seconds':100}]}
   (a/'plan.json').write_text(json.dumps({'steps':[]}));log=p/'workflow.log'
   log.write_text('candidate crash')
   self.assertEqual(retry_budget(plan,p,'workflow',log),(3600,[]))
   log.write_text('Command timed out after 3961s')
   self.assertEqual(retry_budget(plan,p,'workflow',log),(3600,[]))

 def test_utf16_engine_trajectories_keep_progress_evidence(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);a=p/'local-failed-1';a.mkdir()
   plan={'steps':[{'seconds':200}]}
   (a/'plan.json').write_text(json.dumps(plan),encoding='utf-16')
   for i,t in enumerate([0,50]):
    (a/f'trajectory_{i:05}.json').write_text(json.dumps({'time':t,'label':'设备'}),encoding='utf-16')
   log=p/'local.log';log.write_text('Command timed out after 3600s')
   budget,evidence=retry_budget(plan,p,'local',log)
   self.assertEqual(budget,22500)
   self.assertEqual(evidence[0]['observed_sim_seconds'],50)
   (a/'trajectory_00001.json').write_bytes(b'invalid JSON')
   self.assertEqual(retry_budget(plan,p,'local',log),(3600,[]))

if __name__=='__main__':unittest.main()
