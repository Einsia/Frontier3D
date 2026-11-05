import json,tempfile,unittest
from pathlib import Path
from tools.l3_content_protection import content_mounts
class ContentProtectionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.output=self.root/'verification';self.project=self.output/'workspace/project'
  (self.project/'Content/Materials').mkdir(parents=True)
 def config(self,paths,sha='frozen'):
  (self.root/'source-write-protection.json').write_text(json.dumps({'source_sha256':sha,'directories':paths}))
 def test_absent_no_change(self):
  self.assertEqual(content_mounts(self.output,self.project,'frozen'),[])
 def test_source_bound_readonly_mount(self):
  self.config(['Content/Materials'])
  args=content_mounts(self.output,self.project,'frozen')
  self.assertEqual(args,['--mount',f'type=bind,src={self.project}/Content/Materials,dst=/workspace/project/Content/Materials,readonly'])
 def test_wrong_source_rejected(self):
  self.config(['Content/Materials'],'wrong')
  with self.assertRaises(ValueError):content_mounts(self.output,self.project,'frozen')
 def test_unsafe_or_mask_paths_rejected(self):
  for value in ['/Content/Materials','../outside','Content','Content/../Source','Content/L3Verifier','Source/Private']:
   self.config([value])
   with self.assertRaises(ValueError):content_mounts(self.output,self.project,'frozen')
 def test_symlink_rejected(self):
  (self.root/'outside').mkdir();(self.project/'Content/Link').symlink_to(self.root/'outside',target_is_directory=True)
  self.config(['Content/Link'])
  with self.assertRaises(ValueError):content_mounts(self.output,self.project,'frozen')

class RuntimeCopyTests(ContentProtectionTests):
 def seed(self):
  p=self.project/'Content/Materials/a.uasset';p.write_bytes(b'frozen')
  self.config(['Content/Materials'])
  c=json.loads((self.root/'source-write-protection.json').read_text());c['mode']='runtime_copy'
  (self.root/'source-write-protection.json').write_text(json.dumps(c))
  args=content_mounts(self.output,self.project,'frozen')
  from tools.l3_content_protection import audit_content,verify_audit
  host=Path(args[1].split('src=',1)[1].split(',dst=',1)[0])
  return p,host,audit_content,verify_audit
 def test_runtime_write_leaves_frozen_input_and_is_audited(self):
  p,host,audit,verify=self.seed();(host/'a.uasset').write_bytes(b'runtime')
  self.assertEqual(p.read_bytes(),b'frozen')
  ref=audit(self.output,self.project,'frozen','test')
  record=verify(self.output,self.project,'frozen',ref)
  self.assertEqual(record['directories'][0]['changed_runtime_files'],['a.uasset'])
  self.assertFalse(content_mounts(self.output,self.project,'frozen')[1].endswith(',readonly'))
 def test_frozen_input_change_rejected(self):
  p,host,audit,verify=self.seed();p.write_bytes(b'modified')
  with self.assertRaises(ValueError):content_mounts(self.output,self.project,'frozen')
  with self.assertRaises(ValueError):audit(self.output,self.project,'frozen','test')
 def test_post_measurement_runtime_change_rejected(self):
  p,host,audit,verify=self.seed();ref=audit(self.output,self.project,'frozen','test')
  (host/'a.uasset').write_bytes(b'late')
  with self.assertRaises(ValueError):verify(self.output,self.project,'frozen',ref)
