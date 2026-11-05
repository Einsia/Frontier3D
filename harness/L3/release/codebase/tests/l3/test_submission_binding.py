import unittest,tempfile,json,hashlib
from pathlib import Path
from harness.L3.Suite.submission_binding import validate_submission
class BindingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  p=self.root/'workspace/project/Source/a.cpp';p.parent.mkdir(parents=True);p.write_text('scene')
  self.files={'Source/a.cpp':hashlib.sha256(b'scene').hexdigest()}
  self.write('trial.json',{'status':'generated_awaiting_independent_verification','model':'gpt-6-astra','reasoning_effort':'max'})
  self.write('environment.json',{'task_key':'l3-e01'})
  self.write('submission-manifest.json',{'files':self.files,'model':'gpt-6-astra','effort':'max'})
 def tearDown(self):self.tmp.cleanup()
 def write(self,name,value):(self.root/name).write_text(json.dumps(value))
 def check(self,effort='max'):return validate_submission(self.root,'l3-e01','gpt-6-astra',effort)
 def test_nested(self):self.assertEqual(self.check(),self.files)
 def test_legacy(self):
  self.write('submission-manifest.json',self.files);self.assertEqual(self.check(),self.files)
 def test_wrong_effort(self):
  with self.assertRaises(ValueError):self.check('medium')
 def test_modified_source(self):
  (self.root/'workspace/project/Source/a.cpp').write_text('changed')
  with self.assertRaises(ValueError):self.check()
 def test_wrong_task(self):
  self.write('environment.json',{'task_key':'l3-e02'})
  with self.assertRaises(ValueError):self.check()
if __name__=='__main__':unittest.main()
