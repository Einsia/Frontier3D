import tempfile,unittest,json
from pathlib import Path
from tools.repair_l3_runtime import reusable_episode
from tools.l3_leaderboard_batch import write
class RuntimeResumeTests(unittest.TestCase):
 def test_complete_episode_reuses_then_rejects_changed_evidence(self):
  with tempfile.TemporaryDirectory() as temp:
   sub=Path(temp);plan={'steps':[{'op':'snapshot','name':'proof'}]}
   write(sub/'flow-plan.json',plan);write(sub/'flow/completed.json',{'completed':True})
   record={'completed':True}
   self.assertTrue(reusable_episode(sub,'flow',plan,record));self.assertTrue(record['evidence_sha256'])
   write(sub/'flow/changed.json',{})
   with self.assertRaisesRegex(ValueError,'evidence changed'):reusable_episode(sub,'flow',plan,record)
 def test_incomplete_or_different_plan_is_not_reused(self):
  with tempfile.TemporaryDirectory() as temp:
   sub=Path(temp);plan={'steps':[]}
   write(sub/'flow-plan.json',plan);write(sub/'flow/completed.json',{'completed':True})
   self.assertFalse(reusable_episode(sub,'flow',plan,{}))
   self.assertFalse(reusable_episode(sub,'flow',{'steps':[{}]},{'completed':True}))
if __name__=='__main__':unittest.main()
