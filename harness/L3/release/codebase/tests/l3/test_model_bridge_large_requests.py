"""Exercise real Unix gateway transport without making provider requests."""
import http.client,json,multiprocessing,os,socket,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from tools.l3_model_bridge import serve

class FakeProvider:
    def __init__(self,*args,**kwargs):pass
    def connect(self):pass
    def request(self,method,path,body=None,headers=None):
        payload=json.loads(body)
        assert payload['model']=='gpt-6-astra'
        if path.endswith('/compact'):
            assert 'reasoning' not in payload
        else:assert payload['reasoning']['effort']=='high'
        self.result=json.dumps({'object':'response.compaction' if path.endswith('/compact') else 'response','body_bytes':len(body),'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}).encode()
    def getresponse(self):return self
    status=200
    def getheader(self,name,default=None):return 'application/json' if name.lower()=='content-type' else default
    def read1(self,count):
        data=self.result;self.result=b'';return data
    def close(self):pass

def run_gateway(sock,provider,ledger):
    os.environ['L3_EXPECTED_MODEL']='gpt-6-astra'
    os.environ.pop('L3_BATCH_CONTROL',None)
    with patch('tools.l3_model_bridge.http.client.HTTPSConnection',FakeProvider):serve(sock,provider,ledger)

class GatewayPayloadTests(unittest.TestCase):
    def test_multiview_body_larger_than_64_mib_and_compaction(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);sock=root/'api.sock';provider=root/'provider.json';ledger=root/'ledger.jsonl'
            provider.write_text(json.dumps({'base_url':'https://provider.invalid/v1','api_key':'fake-only'}))
            worker=multiprocessing.Process(target=run_gateway,args=(sock,provider,ledger));worker.start()
            try:
                for _ in range(100):
                    if sock.exists():break
                    time.sleep(.05)
                for path,payload in [('/v1/responses',{'model':'wrong','input':'x'*(65*1024*1024)}),('/v1/responses/compact',{'model':'wrong','input':'compact this'})]:
                    conn=http.client.HTTPConnection('localhost',timeout=30);conn.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);conn.sock.settimeout(30);conn.sock.connect(str(sock))
                    conn.request('POST',path,body=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                    result=conn.getresponse();self.assertEqual(result.status,200);data=json.loads(result.read());conn.close()
                    if path.endswith('/compact'):self.assertEqual(data['object'],'response.compaction')
                    else:self.assertGreater(data['body_bytes'],64*1024*1024)
                events=[json.loads(line) for line in ledger.read_text().splitlines()]
                self.assertEqual([e['path'] for e in events if e['event']=='request_finished'],['/v1/responses','/v1/responses/compact'])
            finally:
                worker.terminate();worker.join(timeout=5)
