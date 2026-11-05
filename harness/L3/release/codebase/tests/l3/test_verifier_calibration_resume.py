import unittest,tempfile
from pathlib import Path
from tools.verify_l3_submission import calibration_retry_allowed
class CalibrationResumeTests(unittest.TestCase):
 def test_failed_calibration_can_retry(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);old={'status':'failed','error':'ground_calibration exited 1','verification_source_sha256':'frozen','episodes':{}}
   self.assertTrue(calibration_retry_allowed(old,p))
 def test_complete_or_measured_evidence_cannot_be_replaced(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);old={'status':'failed','error':'ground_calibration exited 1','verification_source_sha256':'frozen','episodes':{}}
   for update in [{'episodes':{'views':{}}},{'error':'episode_views exited 1'},{'verification_source_sha256':None}]:
    self.assertFalse(calibration_retry_allowed({**old,**update},p))
   f=p/'ground_calibration/completed.json';f.parent.mkdir();f.write_text('{}')
   self.assertFalse(calibration_retry_allowed(old,p))
 def test_unindexed_completed_episode_blocks_retry(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);f=p/'episodes/views/completed.json';f.parent.mkdir(parents=True);f.write_text('{}')
   self.assertFalse(calibration_retry_allowed({'status':'failed','error':'ground_calibration exited 1','verification_source_sha256':'frozen'},p))
