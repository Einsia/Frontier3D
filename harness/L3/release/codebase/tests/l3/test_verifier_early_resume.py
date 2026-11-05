import json,tempfile,unittest
from pathlib import Path
from tools.verify_l3_submission import prepare_verifier_project,validate_early_startup

class EarlyResume(unittest.TestCase):
 def fixture(self,root):
  source=root/'source';source.mkdir();(source/'Demo.uproject').write_text('{"Plugins":[]}')
  (source/'source.cpp').write_text('original')
  observer=root/'observer';observer.mkdir();(observer/'observer.cpp').write_text('trusted')
  project=root/'workspace/project';project.parent.mkdir()
  prepare_verifier_project(source,project,observer)
  return source,project,observer
 def test_pristine_startup_can_resume_without_calibration(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);s,p,o=self.fixture(root)
   self.assertEqual(len(validate_early_startup(s,p,o,{'episodes':{}},root)),64)
 def test_changed_source_is_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);s,p,o=self.fixture(root);(p/'source.cpp').write_text('modified')
   with self.assertRaisesRegex(ValueError,'project changed'):
    validate_early_startup(s,p,o,{'episodes':{}},root)
 def test_existing_measurements_cannot_take_early_recovery_path(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);s,p,o=self.fixture(root)
   for prior in [{'episodes':{'view':{'completed':True}}},{'verification_source_sha256':'frozen'}]:
    with self.assertRaisesRegex(ValueError,'frozen measurement'):
     validate_early_startup(s,p,o,prior,root)

 def test_failed_build_output_is_preserved_before_retry(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);s,p,o=self.fixture(root);build=p.parent/'build';build.mkdir()
   (build/'build.log').write_bytes(b'original failure\n')
   original=(p/'source.cpp').read_bytes()
   validate_early_startup(s,p,o,{'episodes':{}},root)
   self.assertFalse(build.exists())
   archives=list((root/'failed-attempts').glob('startup-proof-*/build-output/build.log'))
   self.assertEqual(len(archives),1)
   self.assertEqual(archives[0].read_bytes(),b'original failure\n')
   self.assertEqual((p/'source.cpp').read_bytes(),original)
 def test_invalid_source_preserves_build_in_place(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);s,p,o=self.fixture(root);build=p.parent/'build';build.mkdir()
   (build/'build.log').write_text('failure');(p/'source.cpp').write_text('changed')
   with self.assertRaisesRegex(ValueError,'project changed'):
    validate_early_startup(s,p,o,{'episodes':{}},root)
   self.assertEqual((build/'build.log').read_text(),'failure')
 def test_build_symlink_is_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);s,p,o=self.fixture(root);target=root/'external';target.mkdir()
   (p.parent/'build').symlink_to(target,target_is_directory=True)
   with self.assertRaisesRegex(ValueError,'symlink'):
    validate_early_startup(s,p,o,{'episodes':{}},root)
   self.assertTrue((p.parent/'build').is_symlink())
