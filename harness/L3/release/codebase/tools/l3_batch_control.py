"""Provider-separated admission, conservative adaptive throttling and usage parsing."""
import contextlib,fcntl,json,os,time,random
from pathlib import Path
from tools.l3_api_control import BalanceExhausted
from tools.l3_usage import UsageParser as ResponsesUsage

def root():
    p=Path(os.environ['L3_EXPERIMENT_BATCH'])/'control'/os.environ['L3_MODEL_GROUP'];p.mkdir(parents=True,exist_ok=True);return p

def write(p,d):
    tmp=p.with_name(p.name+'.'+str(os.getpid())+'.tmp');tmp.write_text(json.dumps(d,indent=2));tmp.replace(p)

def provider_maximum():
    settings=Path(os.environ['L3_EXPERIMENT_BATCH'])/'settings.json'
    d=json.loads(settings.read_text()) if settings.exists() else {}
    group=os.environ['L3_MODEL_GROUP']
    return int(d.get('api_concurrency',{}).get(group,4 if group=='china' else 16))

def limit():
    p=root()/'admission.json'
    return json.loads(p.read_text()) if p.exists() else {'limit':provider_maximum(),'successes':0,'last_throttle':0}

def observe_status(status):
    p=root()
    with (p/'admission.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);d=limit()
        if status==429:
            d['limit']=max(1,d['limit']//2);d['successes']=0;d['last_throttle']=time.time()
        elif 200<=status<300:
            d['successes']+=1
            maximum=provider_maximum()
            if d['successes']>=40 and time.time()-d['last_throttle']>600:d['limit']=min(maximum,d['limit']+1);d['successes']=0
        d['updated_unix']=time.time();write(p/'admission.json',d)

def mark_balance_exhausted(status,model,request_id=None):
    write(root()/'balance-exhausted.json',{'status':status,'model':model,'request_id':request_id,'time':time.time()})

@contextlib.contextmanager
def api_slot():
    p=root();handle=None
    while handle is None:
        if (p/'balance-exhausted.json').exists():raise BalanceExhausted('Provider balance exhausted')
        slots=list(range(limit()['limit']));random.shuffle(slots)
        for n in slots:
            f=(p/f'request-{n}.lock').open('a')
            try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:f.close();continue
            handle=f;break
        if handle is None:time.sleep(.5)
    try:yield
    finally:fcntl.flock(handle,fcntl.LOCK_UN);handle.close()

class MultiUsageParser(ResponsesUsage):
    def __init__(self):
        super().__init__();self.multi_buffer=b'';self.anthropic={}
    def accept_gemini(self,value):
        if isinstance(value,list):
            for item in value:self.accept_gemini(item)
        if not isinstance(value,dict):return
        u=value.get('usageMetadata')
        if not isinstance(u,dict) or 'promptTokenCount' not in u:return
        inputs=u['promptTokenCount'];outputs=(u['totalTokenCount']-inputs) if 'totalTokenCount' in u else u.get('candidatesTokenCount',0)+u.get('thoughtsTokenCount',0)
        self.usage={'input_tokens':inputs,'output_tokens':outputs,'total_tokens':inputs+outputs,
                    'cached_input_tokens':u.get('cachedContentTokenCount'),'reasoning_output_tokens':u.get('thoughtsTokenCount')}
    def feed(self,data):
        super().feed(data);self.multi_buffer+=data
        if len(self.multi_buffer)>8*1024*1024:self.multi_buffer=b'';self.overflow=True
        while b'\n' in self.multi_buffer:
            line,self.multi_buffer=self.multi_buffer.split(b'\n',1)
            if not line.startswith(b'data:'):continue
            try:v=json.loads(line[5:].strip())
            except ValueError:continue
            self.accept_gemini(v)
            typ=v.get('type')
            if typ=='message_start':self.anthropic.update(v.get('message',{}).get('usage',{}));self.response_id=v.get('message',{}).get('id')
            if typ=='message_delta':self.anthropic.update(v.get('usage',{}))
            if typ=='message_stop':self.terminal_event=typ
            if self.anthropic:
                u=self.anthropic;self.usage={'input_tokens':u.get('input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0),
                    'output_tokens':u.get('output_tokens',0),'cached_input_tokens':u.get('cache_read_input_tokens',0),'cache_write_input_tokens':u.get('cache_creation_input_tokens',0)}
            u=v.get('usage')
            if u and 'prompt_tokens' in u:self.usage={'input_tokens':u['prompt_tokens'],'output_tokens':u.get('completion_tokens',0),'cached_input_tokens':u.get('prompt_tokens_details',{}).get('cached_tokens',0)}
            if v.get('choices') and v['choices'][0].get('finish_reason'):self.terminal_event='chat.completion.finished'

    def finish(self):
        value=self.buffer.strip()
        super().finish()
        try:
            v=json.loads(value);self.accept_gemini(v);u=v.get('usage',{}) if isinstance(v,dict) else {}
            if 'prompt_tokens' in u:self.usage={'input_tokens':u['prompt_tokens'],'output_tokens':u.get('completion_tokens',0),'cached_input_tokens':u.get('prompt_tokens_details',{}).get('cached_tokens',0)}
            elif v.get('type')=='message':
                self.usage={'input_tokens':u.get('input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0),'output_tokens':u.get('output_tokens',0),'cached_input_tokens':u.get('cache_read_input_tokens',0),'cache_write_input_tokens':u.get('cache_creation_input_tokens',0)}
        except (ValueError,AttributeError):pass
        if self.usage and self.usage.get('input_tokens') is not None and self.usage.get('output_tokens') is not None:self.usage['total_tokens']=self.usage['input_tokens']+self.usage['output_tokens']
