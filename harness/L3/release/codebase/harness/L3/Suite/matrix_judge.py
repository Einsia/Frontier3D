"""Host-only image judge transport with provider admission and durable usage."""
import base64,gzip,hashlib,http.client,json,mimetypes,os,time,urllib.parse
from pathlib import Path
from .policy import ROOT,read,write
from tools.l3_batch_control import api_slot,observe_status,mark_balance_exhausted
from tools.l3_api_control import is_balance_error

def request_body(payload):
 raw=json.dumps(payload).encode()
 packed=gzip.compress(raw,compresslevel=3,mtime=0) if len(raw)>=262144 else raw
 compressed=len(packed)<len(raw)*0.95
 body=packed if compressed else raw
 return body,({'Content-Encoding':'gzip'} if compressed else {}),{
  'raw_bytes':len(raw),'wire_bytes':len(body),'encoding':'gzip' if compressed else 'identity',
  'raw_sha256':hashlib.sha256(raw).hexdigest(),'wire_sha256':hashlib.sha256(body).hexdigest()}

def output_value(response):
 if response.get('status')!='completed':raise ValueError('Judge did not complete')
 text=''.join(c.get('text','') for item in response.get('output',[]) if item.get('type')=='message'
              for c in item.get('content',[]) if c.get('type')=='output_text')
 return json.loads(text)

def legacy_route_cache_matches(packet,identity,value):
 """Validate existing text-only route evidence without inventing provenance."""
 if packet.name!='route-translation' or identity['images']:return False
 try:
  protocol=read(packet/'protocol.json')
  if protocol.get('model')!='gpt-6-astra' or protocol.get('reasoning_effort')!='medium':return False
  if protocol.get('images')!={} or protocol.get('prompt_sha256')!=identity['prompt_sha256']:return False
  if hashlib.sha256((packet/'prompt.txt').read_bytes()).hexdigest()!=identity['prompt_sha256']:return False
  if read(packet/'schema.json')!=identity['schema']:return False
  return any(a.get('status')=='success' and a.get('returncode')==0
             and read(packet/('verdict-'+str(a['attempt'])+'.json'))==value
             for a in protocol.get('attempts',[]))
 except (OSError,ValueError,KeyError,TypeError):return False

def call(packet,prompt,images,schema):
 import sys
 import jsonschema
 packet=Path(packet);packet.mkdir(parents=True,exist_ok=True)
 hashes={str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in images}
 identity={'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'images':hashes,'schema':schema}
 if (packet/'result.json').exists():
  value=read(packet/'result.json')
  if (packet/'request-identity.json').exists():
   matched=read(packet/'request-identity.json')==identity
  else:matched=legacy_route_cache_matches(packet,identity,value)
  if not matched:raise ValueError('Judge cache evidence mismatch')
  jsonschema.validate(value,schema);return value
 write(packet/'request-identity.json',identity);write(packet/'schema.json',schema);(packet/'prompt.txt').write_text(prompt)
 provider=read(Path(os.environ['L3_MATRIX_JUDGE_PROVIDER']))
 endpoint=urllib.parse.urlsplit(provider['base_url'])
 if endpoint.scheme!='https':raise ValueError('HTTPS provider required')
 content=[{'type':'input_text','text':prompt}]
 for p in images:
  p=Path(p);mime=mimetypes.guess_type(str(p))[0] or 'image/png'
  content.append({'type':'input_image','image_url':'data:'+mime+';base64,'+base64.b64encode(p.read_bytes()).decode()})
 payload={'model':'gpt-6-astra','reasoning':{'effort':'medium'},'input':[{'role':'user','content':content}],
          'text':{'format':{'type':'json_schema','name':'l3_verdict','strict':True,'schema':schema}},
          'stream':True,'store':False}
 body,body_headers,body_metadata=request_body(payload)
 protocol=read(packet/'protocol.json') if (packet/'protocol.json').exists() else {'model':'gpt-6-astra','reasoning_effort':'medium','images':hashes,'attempts':[]}
 attempt=max([x['attempt'] for x in protocol['attempts']]+[0])
 while True:
  attempt+=1;started=time.time();status=None;response=None;failure=None;transport=dict(body_metadata)
  protocol['active_attempt']={'attempt':attempt,'started_unix':started,'image_count':len(images)}
  write(packet/'protocol.json',protocol)
  try:
   with api_slot():
    conn=http.client.HTTPSConnection(endpoint.hostname,endpoint.port or 443,timeout=600)
    try:
     upload_started=time.time()
     conn.request('POST',endpoint.path.rstrip('/')+'/responses',body=body,
                  headers={'Authorization':'Bearer '+provider['api_key'],'Content-Type':'application/json','Accept-Encoding':'identity',**body_headers})
     transport['upload_seconds']=time.time()-upload_started
     result=conn.getresponse();status=result.status
     transport['headers_seconds']=time.time()-upload_started
     transport['request_id']=result.getheader('x-request-id')
     if status>=400:
      error=result.read(65536).decode(errors='replace').replace(provider['api_key'],'[REDACTED]')
      if is_balance_error(status,error):
       mark_balance_exhausted(status,'gpt-6-astra',result.getheader('x-request-id'));raise RuntimeError('Provider balance exhausted: '+error[:1000])
      observe_status(status)
      raise RuntimeError('HTTP '+str(status)+': '+error[:1000])
     observe_status(status)
     if 'text/event-stream' in (result.getheader('Content-Type') or ''):
      while True:
       line=result.readline()
       if not line:break
       if not line.startswith(b'data:'):continue
       raw=line[5:].strip()
       if raw==b'[DONE]':continue
       event=json.loads(raw)
       if event.get('type')=='response.completed':response=event['response'];break
       if event.get('type') in {'response.failed','error'}:raise RuntimeError(str(event)[:1000])
     else:response=json.loads(result.read())
     if response is None:raise RuntimeError('Stream ended without response.completed')
     value=output_value(response);jsonschema.validate(value,schema)
     for p,sha in hashes.items():
      if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=sha:raise ValueError('Image evidence changed')
    finally:conn.close()
  except Exception as exc:failure=str(exc).replace(provider['api_key'],'[REDACTED]')[:1500]
  row={'attempt':attempt,'http_status':status,'started_unix':started,'elapsed_seconds':time.time()-started,
       'error':failure,'usage':response.get('usage') if response else None,'image_count':len(images),'transport':transport}
  protocol.pop('active_attempt',None);protocol['attempts'].append(row);write(packet/'protocol.json',protocol)
  if status==415 and body_headers:
   body=json.dumps(payload).encode();body_headers={};body_metadata={**body_metadata,'wire_bytes':len(body),'wire_sha256':hashlib.sha256(body).hexdigest(),'encoding':'identity'}
   continue
  if failure is None:
   write(packet/('verdict-'+str(attempt)+'.json'),value);write(packet/'result.json',value);return value
  if 'balance exhausted' in failure.lower() or status in {400,401,404,422}:raise RuntimeError(failure)
  time.sleep(min(300,15*2**min(attempt,4)))
