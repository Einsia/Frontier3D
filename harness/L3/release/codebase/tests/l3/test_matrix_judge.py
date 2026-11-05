import unittest,tempfile,json,hashlib
from pathlib import Path
from harness.L3.Suite.matrix_judge import output_value
class JudgeTests(unittest.TestCase):
 def test_completed_output(self):
  response={'status':'completed','output':[{'type':'reasoning','content':[]},{'type':'message','content':[{'type':'output_text','text':'{"score":3}'}]}]}
  self.assertEqual(output_value(response),{'score':3})
 def test_incomplete_never_scored(self):
  with self.assertRaises(ValueError):output_value({'status':'incomplete','output':[]})
 def test_missing_json_never_scored(self):
  with self.assertRaises(ValueError):output_value({'status':'completed','output':[]})
class CachedEvidenceTests(unittest.TestCase):
 def test_cached_verdict_rejects_changed_image(self):
  from harness.L3.Suite.matrix_judge import call
  with tempfile.TemporaryDirectory() as root:
   p=Path(root);im=p/'view.png';im.write_bytes(b'first')
   schema={'type':'object','properties':{'grade':{'type':'integer'}},'required':['grade']}
   identity={'prompt_sha256':hashlib.sha256(b'judge').hexdigest(),'images':{str(im):hashlib.sha256(b'first').hexdigest()},'schema':schema}
   (p/'request-identity.json').write_text(json.dumps(identity));(p/'result.json').write_text('{"grade":3}')
   self.assertEqual(call(p,'judge',[im],schema),{'grade':3})
   im.write_bytes(b'changed')
   with self.assertRaisesRegex(ValueError,'evidence mismatch'):call(p,'judge',[im],schema)

class LegacyRouteCacheTests(unittest.TestCase):
 def packet(self,root):
  p=Path(root)/'route-translation';p.mkdir()
  schema={'type':'object','properties':{'grade':{'type':'integer'}},'required':['grade']}
  (p/'prompt.txt').write_text('route');(p/'schema.json').write_text(json.dumps(schema))
  protocol={'model':'gpt-6-astra','reasoning_effort':'medium','images':{},
   'prompt_sha256':hashlib.sha256(b'route').hexdigest(),
   'attempts':[{'attempt':1,'status':'success','returncode':0}]}
  (p/'protocol.json').write_text(json.dumps(protocol))
  (p/'verdict-1.json').write_text('{"grade":3}');(p/'result.json').write_text('{"grade":3}')
  return p,schema
 def test_verified_legacy_route_cache_reuses_without_provider(self):
  from harness.L3.Suite.matrix_judge import call
  with tempfile.TemporaryDirectory() as root:
   p,schema=self.packet(root)
   self.assertEqual(call(p,'route',[],schema),{'grade':3})
   self.assertFalse((p/'request-identity.json').exists())
 def test_legacy_route_rejects_changed_evidence(self):
  from harness.L3.Suite.matrix_judge import call
  for change in ('prompt','schema','model','effort','verdict','success','missing'):
   with self.subTest(change=change),tempfile.TemporaryDirectory() as root:
    p,schema=self.packet(root);prompt='route'
    if change=='prompt':prompt='different'
    elif change=='schema':schema={**schema,'additionalProperties':False}
    elif change=='verdict':(p/'verdict-1.json').write_text('{"grade":4}')
    elif change=='missing':(p/'protocol.json').unlink()
    else:
     protocol=json.loads((p/'protocol.json').read_text())
     if change=='model':protocol['model']='other'
     elif change=='effort':protocol['reasoning_effort']='high'
     else:protocol['attempts'][0]['status']='failed'
     (p/'protocol.json').write_text(json.dumps(protocol))
    with self.assertRaisesRegex(ValueError,'evidence mismatch'):call(p,prompt,[],schema)
 def test_legacy_cache_does_not_apply_to_image_or_score_packets(self):
  from harness.L3.Suite.matrix_judge import call
  with tempfile.TemporaryDirectory() as root:
   p,schema=self.packet(root);im=p/'view.png';im.write_bytes(b'image')
   with self.assertRaisesRegex(ValueError,'evidence mismatch'):call(p,'route',[im],schema)
   other=p.with_name('score');p.rename(other)
   with self.assertRaisesRegex(ValueError,'evidence mismatch'):call(other,'route',[],schema)


class QuotaAdmissionTests(unittest.TestCase):
 def test_quota_429_does_not_reduce_rate_admission(self):
  from unittest.mock import patch,MagicMock
  from contextlib import nullcontext
  from harness.L3.Suite.matrix_judge import call
  import os
  with tempfile.TemporaryDirectory() as root:
   p=Path(root);provider=p/'provider.json'
   provider.write_text(json.dumps({'base_url':'https://example.invalid/v1','api_key':'test-private-key'}))
   response=MagicMock();response.status=429
   response.read.return_value=b'{"error":{"code":"insufficient_quota","message":"API key quota exhausted"}}'
   response.getheader.return_value='quota-request'
   conn=MagicMock();conn.getresponse.return_value=response
   with patch.dict(os.environ,{'L3_MATRIX_JUDGE_PROVIDER':str(provider)}), patch('harness.L3.Suite.matrix_judge.http.client.HTTPSConnection',return_value=conn), patch('harness.L3.Suite.matrix_judge.api_slot',return_value=nullcontext()), patch('harness.L3.Suite.matrix_judge.observe_status') as observe, patch('harness.L3.Suite.matrix_judge.mark_balance_exhausted') as mark:
    with self.assertRaisesRegex(RuntimeError,'balance exhausted'):call(p/'packet','judge',[],{'type':'object'})
    observe.assert_not_called();mark.assert_called_once_with(429,'gpt-6-astra','quota-request')

if __name__=='__main__':unittest.main()
