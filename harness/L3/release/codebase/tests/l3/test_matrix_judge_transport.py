import gzip,hashlib,json
from harness.L3.Suite.matrix_judge import request_body

def test_gzip_preserves_complete_request():
 payload={'model':'gpt-6-astra','reasoning':{'effort':'medium'},'input':[{'image':'abc123'*100000,'text':'全部图片保持原样'}]}
 raw=json.dumps(payload).encode();body,headers,meta=request_body(payload)
 assert headers=={'Content-Encoding':'gzip'}
 assert gzip.decompress(body)==raw
 assert meta['raw_sha256']==hashlib.sha256(raw).hexdigest()
 assert meta['wire_bytes']==len(body)<len(raw)

def test_small_request_remains_identity():
 payload={'model':'gpt-6-astra'}
 body,headers,meta=request_body(payload)
 assert not headers and json.loads(body)==payload and meta['encoding']=='identity'
