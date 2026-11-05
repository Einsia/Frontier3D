"""Recoverable independent collection with stable configurable engine slots."""
import concurrent.futures,fcntl,os,subprocess,sys,time
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R))
from tools.l3_leaderboard_batch import B,read,write,process_matches
from tools.l3_delivery import terminal_complete

def collect_slot(engine,engines):
 resolved=Path(engine).resolve()
 return next((slot for slot,path in engines.items() if path.resolve()==resolved),None)

def confirmed_submission_block(folder,trial):
 block=read(Path(folder)/'collection-block.json',{})
 if block.get('kind')!='confirmed_submission_failure':return False
 from hashlib import sha256
 manifest=Path(trial)/'submission-manifest.json'
 return manifest.is_file() and block.get('manifest_sha256')==sha256(manifest.read_bytes()).hexdigest()

def collection_environment(row,trial,out):
 return {**os.environ,'L3_EVAL_MODEL':row['model'],'L3_EVAL_EFFORT':row['effort'],'L3_EVAL_TRIAL':str(trial),
         'L3_EVAL_OUT':str(out),'L3_EXPERIMENT_BATCH':str(B),'L3_MODEL_GROUP':'openai',
         'L3_MATRIX_JUDGE_PROVIDER':os.environ.get('L3_MATRIX_JUDGE_PROVIDER',str(R.parent/'.config/3dbench/providers/openai.json')),
         'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','PYTHONUNBUFFERED':'1'}

def provision(slot,engine,control):
 engine.mkdir(parents=True,exist_ok=True)
 ready=engine.with_suffix('.ready')
 if ready.exists():return
 with (control/('engine-copy-'+str(slot)+'.log')).open('a') as log:
  subprocess.run(['rsync','-a',str(B/'engines/seed')+'/',str(engine)+'/'],stdout=log,stderr=log,check=True)
 if not (engine/'Engine/Binaries/Linux/UnrealEditor-Cmd').is_file():raise RuntimeError('Evaluation engine incomplete')
 ready.write_text(str(time.time()))

def main():
 control=B/'evaluation-control';control.mkdir(exist_ok=True)
 with (control/'collection.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  settings=read(B/'settings.json',{})
  count=max(2,int(settings.get('collection_workers',2)))
  configured=settings.get('evaluation_engine_pool',{})
  engines={i:Path(configured[str(i)]) if str(i) in configured else B/'evaluation-engines'/f'slot-{i:02}' for i in range(count)}
  children={};active={};copy_jobs={}
  with concurrent.futures.ThreadPoolExecutor(max_workers=min(count,2)) as pool:
   for slot,engine in engines.items():copy_jobs[slot]=pool.submit(provision,slot,engine,control)
   while True:
    # Adopt existing independently running children before allocating a slot.
    for launchfile in (B/'evaluations/runtime').glob('*/*/collection-launch.json'):
     launch=read(launchfile,{})
     if process_matches(launch.get('pid'),'tools/evaluate_l3_submission.py'):
      slot=collect_slot(launch['engine'],engines)
      if slot is None:raise RuntimeError('Live evaluator uses an unknown engine')
      active[slot]={**launch,'launchfile':str(launchfile)}
    for slot,launch in list(active.items()):
     if process_matches(launch.get('pid'),'tools/evaluate_l3_submission.py'):continue
     proc=children.pop(slot,None);rc=proc.poll() if proc else None
     folder=Path(launch['output']);record=read(folder/'run.json',{})
     update={**launch,'return_code':rc,'finished_unix':time.time()}
     if record.get('status')!='collected':update['failed_unix']=time.time()
     else:update['evidence_status']='collected'
     update.pop('launchfile',None);write(Path(launch['launchfile']),update);active.pop(slot)
    for slot,engine in engines.items():
     if read(B/'settings.json',{}).get('defer_new_evaluations',False):continue
     future=copy_jobs[slot]
     if slot in active or not future.done():continue
     future.result()
     for row in read(B/'manifest.json')['rows']:
      if row['status']=='reused' or not row.get('enabled',True):continue
      trial=Path(row['output'])
      if read(trial/'state.json',{}).get('status')!='generated':continue
      if not terminal_complete(read(trial/'generation-timing.json',{})):continue
      out=B/'evaluations/runtime'/row['variant'];folder=out/row['task_key'];folder.mkdir(parents=True,exist_ok=True)
      if read(folder/'run.json',{}).get('status')=='collected':continue
      if confirmed_submission_block(folder,trial):continue
      prior=read(folder/'collection-launch.json',{})
      if process_matches(prior.get('pid'),'tools/evaluate_l3_submission.py'):continue
      if time.time()-prior.get('failed_unix',0)<1800:continue
      if prior.get('engine') and collect_slot(prior['engine'],engines)!=slot:continue
      env=collection_environment(row,trial,out)
      logfile=folder/('collection-'+str(time.time_ns())+'.log')
      with logfile.open('a') as log:
       p=subprocess.Popen([sys.executable,str(R/'tools/evaluate_l3_submission.py'),'--collect-only',
         '--key',row['task_key'],'--engine',str(engine),'--gpu',str([0,5][slot%2])],cwd=R,env=env,stdout=log,stderr=log,start_new_session=True)
      launch={'id':row['id'],'pid':p.pid,'started_unix':time.time(),'engine':str(engine),'log':str(logfile),'output':str(folder)}
      write(folder/'collection-launch.json',launch);children[slot]=p;active[slot]={**launch,'launchfile':str(folder/'collection-launch.json')};break
    write(control/'collection.json',{'pid':os.getpid(),'status':'collecting' if active else 'waiting','active':active,
       'engine_ready':{i:f.done() and f.exception() is None for i,f in copy_jobs.items()},'updated_unix':time.time()})
    time.sleep(10)
if __name__=='__main__':main()
