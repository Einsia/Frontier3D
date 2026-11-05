"""Host-only cross-process API concurrency and explicit balance-exhaustion stop."""
import contextlib,fcntl,json,os,re,time,random
from pathlib import Path
class BalanceExhausted(RuntimeError):pass

def control_root():
 value=os.environ.get('L3_BATCH_CONTROL')
 return Path(value) if value else None

def stopped():
 root=control_root()
 return bool(root and (root/'balance-exhausted.json').exists())

def is_balance_error(status, detail):
 text=(detail if isinstance(detail,str) else json.dumps(detail,ensure_ascii=False)).lower()
 markers=('insufficient_quota','insufficient_balance','insufficient_user_quota','credit balance is too low','credit balance exhausted','credits exhausted','insufficient credits','insufficient funds','balance exhausted','billing_hard_limit_reached','余额不足','余额已耗尽','额度已用尽','额度不足','配额已耗尽')
 return status==402 or any(x in text for x in markers)

def is_transient(text):
 text=str(text).lower()
 if is_balance_error(None,text):return False
 # Some gateways wrap a failed upstream connection in HTTP 400.
 # Match the structured error type, never all bad-request responses.
 normalized=text.replace('\\"','"')
 if re.search(r'"type"\s*:\s*"upstream_error"',normalized):return True
 return bool(re.search(r'\b(?:429|500|502|503|504|520|522|524)\b',text)) or any(x in text for x in ('overloaded','rate limit','stream disconnected','connection reset','connection refused','connection closed','error sending request','failed to connect','timed out','timeout','bad gateway','service unavailable','unexpected eof'))

def mark_balance_exhausted(status, model, request_id=None):
 root=control_root()
 if root is None:return
 root.mkdir(parents=True,exist_ok=True)
 # No raw provider text, credentials or request bodies are persisted here.
 record={'reason':'api_balance_exhausted','http_status':status,'model':model,'request_id':request_id,'time_unix':time.time()}
 try:
  with (root/'balance-exhausted.json').open('x') as f:json.dump(record,f,indent=2)
 except FileExistsError:pass

@contextlib.contextmanager
def api_slot():
 root=control_root()
 if root is None:yield;return
 root.mkdir(parents=True,exist_ok=True);limit=int(os.environ.get('L3_API_CONCURRENCY','2'))
 if not 1<=limit<=10:raise ValueError('Batch concurrency cannot exceed the account limit of 10')
 handle=None
 while handle is None:
  if stopped():raise BalanceExhausted('API balance exhausted; batch stopped')
  indices=list(range(limit));random.shuffle(indices)
  for i in indices:
   candidate=(root/f'api-slot-{i}.lock').open('a')
   try:fcntl.flock(candidate,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:candidate.close();continue
   handle=candidate;break
  if handle is None:time.sleep(.25)
 try:
  if stopped():raise BalanceExhausted('API balance exhausted; batch stopped')
  yield
 finally:
  fcntl.flock(handle,fcntl.LOCK_UN);handle.close()
