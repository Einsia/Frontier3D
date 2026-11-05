"""Ten-slot finite generation pool, adopting in-flight trials without restarting them."""
import argparse,hashlib,json,os,signal,stat,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.validate_l3_suite import validate_task,sha
from tools.l3_usage import summarize_requests
BASE=ROOT/'data/l3/suite-20261023';CONTROL=BASE/'batch-control'

def write(path,value):
 temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)
def live(pid):
 try:
  raw=(Path('/proc')/str(pid)/'stat').read_text();return raw.rsplit(')',1)[1].split()[0]!='Z'
 except FileNotFoundError:return False

def inventory(root):
 result={}
 for folder,dirs,files in os.walk(root,followlinks=False):
  for name in dirs+files:
   p=Path(folder)/name;relative=str(p.relative_to(root));s=p.lstat()
   if stat.S_ISLNK(s.st_mode):result[relative]=['link',os.readlink(p)]
   elif stat.S_ISREG(s.st_mode):result[relative]=['file',s.st_size]
 return result

def validate_engine(copy,expected):
 dest=Path(copy['engine']);actual=inventory(dest)
 if actual!=expected:
  missing=[k for k,v in expected.items() if actual.get(k)!=v]
  raise RuntimeError('Incomplete engine copy '+str(dest)+' '+str(missing[:10]))
 source=Path(copy['source'])
 for rel in ['Engine/Binaries/Linux/UnrealEditor','Engine/Binaries/Linux/UnrealEditor-Cmd','Engine/Binaries/Linux/libUnrealEditor-Core.so']:
  if sha(source/rel)!=sha(dest/rel):raise RuntimeError('Engine binary differs: '+rel)
 write(CONTROL/('engine-ready-%02d.json'%copy['slot']),{'passed':True,'files':len(actual),'engine':str(dest),'source':str(source),'time_unix':time.time()})
 return True

def cleanup(run):
 root=ROOT/run['output'];path=root/'environment.json'
 if not path.exists():return
 env=json.loads(path.read_text());subprocess.run(['docker','stop','--time','10',env['container']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 pid=env.get('gateway_pid');cmd=Path('/proc')/str(pid)/'cmdline'
 if cmd.exists() and str(root/'model-requests.jsonl').encode() in cmd.read_bytes():os.kill(pid,signal.SIGTERM)

def main():
 p=argparse.ArgumentParser();p.add_argument('--handoff',type=Path,required=True);a=p.parse_args();handoff=json.loads(a.handoff.read_text());batch=json.loads(Path(handoff['manifest']).read_text());runs=batch['runs'];byid={r['id']:r for r in runs}
 for r in runs:
  task=ROOT/r['task_path'];validate_task(task)
  if sha(task/'package-manifest.json')!=r['package_manifest_sha256']:raise RuntimeError('Task changed '+r['id'])
 policy={'api_concurrency_limit':10,'task_concurrency_limit':10,'reasoning_effort':'high','time_limit_seconds':None,'connection_retry_limit':None}
 write(CONTROL/'api-policy.json',policy)
 env={**os.environ,'L3_BATCH_CONTROL':str(CONTROL),'L3_API_CONCURRENCY':'10','PYTHONUNBUFFERED':'1'}
 copies=json.loads((CONTROL/'engine-copies.json').read_text());copy_by_slot={c['slot']:c for c in copies}
 source=Path(copies[0]['source']);executor=ThreadPoolExecutor(max_workers=3);expected_future=executor.submit(inventory,source);validations={}
 slots=[];active={};finished=set();failures={};processes={}
 for d in handoff['adoptions']:
  slots.append({'slot':d['slot'],'engine':d['engine'],'gpu':d['gpu'],'ready':True})
  active[d['slot']]={'run_id':d['run_id'],'pid':d['run_pid'],'adopted_parent':d['paused_parent_pid'],'adopted':True}
 slots += [{'slot':2,'engine':str(ROOT.parent/'engines/UE_5.8.3_trial_20261019_001'),'gpu':0,'ready':True}, {'slot':3,'engine':str(source),'gpu':3,'ready':False}]
 slots += [{'slot':c['slot'],'engine':c['engine'],'gpu':0 if c['slot']%2==0 else 3,'ready':False} for c in copies]
 slots.sort(key=lambda x:x['slot'])
 claimed={v['run_id'] for v in active.values()}
 for r in runs:
  path=ROOT/r['output']/'trial.json'
  if path.exists() and r['id'] not in claimed:
   t=json.loads(path.read_text())
   if t['status']=='generated_awaiting_independent_verification':finished.add(r['id'])
   else:raise RuntimeError('Unadopted existing trial '+r['id'])
 pending=[r['id'] for r in runs if r['id'] not in claimed|finished]
 write(CONTROL/'expansion.json',{'supervisor_pid':os.getpid(),'started_unix':time.time(),'policy':policy,'adoptions':handoff['adoptions'],'slots':slots,'manifest':handoff['manifest']})
 while True:
  balance=(CONTROL/'balance-exhausted.json').exists()
  for slot_id,job in list(active.items()):
   proc=processes.get(slot_id);alive=proc.poll() is None if proc else live(job['pid'])
   if alive:continue
   rid=job['run_id'];path=ROOT/byid[rid]['output']/'trial.json'
   if job.get('adopted_parent') and live(job['adopted_parent']):os.kill(job['adopted_parent'],signal.SIGKILL)
   cleanup(byid[rid]);status=json.loads(path.read_text())['status'] if path.exists() else 'failed_before_trial_record'
   if status=='generated_awaiting_independent_verification':finished.add(rid)
   else:failures[rid]=status
   del active[slot_id];processes.pop(slot_id,None)
  if expected_future.done():
   expected=expected_future.result()
   for c in copies:
    n=c['slot']
    if n not in validations and not live(c['pid']):validations[n]=executor.submit(validate_engine,c,expected)
    if n in validations and validations[n].done():
     try:slots[n]['ready']=validations[n].result()
     except Exception as error:slots[n]['error']=str(error)
   if all(not live(c['pid']) for c in copies):slots[3]['ready']=True
  if not balance:
   for slot in slots:
    n=slot['slot']
    if n in active or not slot['ready'] or not pending:continue
    rid=pending.pop(0);r=byid[rid]
    if (ROOT/r['output']).exists():raise RuntimeError('Refusing duplicate dispatch '+rid)
    cmd=[sys.executable,str(ROOT/'tools/run_l3_suite.py'),'--manifest',handoff['manifest'],'--model',r['model'],'--tasks',r['task_key'],'--engine',slot['engine'],'--gpu',str(slot['gpu']),'--shared-gpu','--generate']
    logpath=CONTROL/('slot-%02d-%s.log'%(n,rid))
    with logpath.open('x') as log:proc=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    processes[n]=proc;active[n]={'run_id':rid,'pid':proc.pid,'adopted':False,'log':str(logpath)}
  rows=[]
  for r in runs:
   root=ROOT/r['output'];row={k:r[k] for k in ['id','task_key','model','output']};row['status']='not_started'
   try:
    if (root/'trial.json').exists():
     t=json.loads((root/'trial.json').read_text());row.update(status=t['status'],generation_seconds=t.get('elapsed_seconds'),started_unix=t.get('started_unix'),finished_unix=t.get('finished_unix'))
    elif (root/'environment.json').exists():row['status']='prepared'
    elif any(j['run_id']==r['id'] for j in active.values()):row['status']='preparing'
   except (ValueError,OSError):row['status']='status_write_in_progress'
   if (root/'model-requests.jsonl').exists():row['usage']=summarize_requests(root/'model-requests.jsonl')
   rows.append(row)
  state='completed' if len(finished)==28 else 'stopped_api_balance_exhausted' if balance and not active else 'stopping_api_balance_exhausted' if balance else 'requires_inspection' if not active and not pending else 'running'
  write(CONTROL/'summary.json',{'status':state,'updated_unix':time.time(),'supervisor_pid':os.getpid(),'completed':len(finished),'expected':28,'api_concurrency_limit':10,'task_concurrency_limit':10,'active_workers':active,'pending_runs':pending,'failed_runs':failures,'slots':slots,'runs':rows})
  if state in {'completed','stopped_api_balance_exhausted','requires_inspection'}:break
  time.sleep(5)
 executor.shutdown(wait=False);print(state,len(finished),'/ 28',flush=True)
if __name__=='__main__':main()
