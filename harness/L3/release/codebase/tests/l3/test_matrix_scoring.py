import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.l3_leaderboard_batch import write
from tools.l3_matrix_scoring import active_scores
class ScoreRecoveryTests(unittest.TestCase):
 def test_configured_score_capacity(self):
  from tools.l3_matrix_scoring import score_worker_limit
  with tempfile.TemporaryDirectory() as tmp,patch('tools.l3_matrix_scoring.B',Path(tmp)):
   self.assertEqual(score_worker_limit(),2)
   write(Path(tmp)/'settings.json',{'scoring_workers':4})
   self.assertEqual(score_worker_limit(),4)
 def test_adopts_only_live_workers_and_preserves_identity(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   write(root/'variant/task/model/launch.json',{'id':'running','pid':123})
   write(root/'variant/other/model/launch.json',{'id':'dead','pid':456})
   with patch('tools.l3_matrix_scoring.process_matches',side_effect=lambda pid,cmd: pid==123 and cmd=='l3_matrix_scoring.py worker'):
    active=active_scores(root)
   self.assertEqual(set(active),{'running'})
   self.assertEqual(active['running']['pid'],123)
   self.assertTrue(active['running']['launchfile'].endswith('variant/task/model/launch.json'))
if __name__=='__main__':unittest.main()
