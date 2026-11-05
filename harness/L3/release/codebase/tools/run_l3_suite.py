"""Run an explicit finite batch on one dedicated UE engine/GPU; no scheduler is created."""
import argparse, fcntl, hashlib, json, os, signal, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.validate_l3_suite import validate_task, sha
from tools.l3_api_control import stopped,BalanceExhausted

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--model',choices=['gpt-6-luna','gpt-6-astra','gpt-6-sol']);p.add_argument('--tasks',nargs='+');p.add_argument('--engine',type=Path);p.add_argument('--gpu',type=int);p.add_argument('--generate',action='store_true');p.add_argument('--shared-gpu',action='store_true');a=p.parse_args()
 batch=json.loads(a.manifest.read_text());runs=[r for r in batch['runs'] if (a.model is None or a.model==r['model']) and (not a.tasks or r['task_key'] in a.tasks)]
 if not runs:raise SystemExit('No matching runs')
 for r in runs:
  task=ROOT/r['task_path'];validate_task(task)
  if sha(task/'package-manifest.json')!=r['package_manifest_sha256']:raise ValueError('Batch input changed: '+r['id'])
 if not a.generate:print(json.dumps({'mode':'plan','runs':runs},indent=2));return
 if a.engine is None or a.gpu is None:p.error('--generate requires --engine and --gpu')
 engine=a.engine.resolve();lockroot=ROOT/'data/l3/locks';lockroot.mkdir(parents=True,exist_ok=True);locks=[]
 resources=['engine-'+hashlib.sha256(str(engine).encode()).hexdigest()[:16]]
 if not a.shared_gpu:resources.append('gpu-'+str(a.gpu))
 for name in resources:
  f=(lockroot/(name+'.lock')).open('a');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(f)
 runroot=ROOT/'data/l3/suite-20261023/batch-runs';runroot.mkdir(parents=True,exist_ok=True)
 ledger=runroot/(time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid())+'.json');results=[]
 def save():ledger.write_text(json.dumps({'pid':os.getpid(),'engine':str(engine),'gpu':a.gpu,'runs':results},indent=2)+'\n')
 for r in runs:
  if stopped():raise BalanceExhausted('API balance exhausted; remaining tasks not started')
  output=ROOT/r['output'];row={'id':r['id'],'model':r['model'],'output':str(output),'started_unix':time.time()};results.append(row);save()
  if output.exists():
   row['status']='existing_output_requires_inspection';save();raise RuntimeError('Refusing to overwrite or regenerate '+str(output))
  logfile=runroot/(r['id']+'.log')
  try:
   with logfile.open('x') as log:
    subprocess.run([sys.executable,str(ROOT/'tools/prepare_l3_trial.py'),'--task',str(ROOT/r['task_path']),'--output',str(output),'--engine',str(engine),'--gpu',str(a.gpu),'--model',r['model']],stdout=log,stderr=subprocess.STDOUT,check=True)
    subprocess.run([sys.executable,str(ROOT/'tools/run_l3_trial.py'),'--output',str(output),'--generate'],stdout=log,stderr=subprocess.STDOUT,check=True)
   trial=json.loads((output/'trial.json').read_text());row.update(status=trial['status'],generation_seconds=trial.get('elapsed_seconds'),finished_unix=time.time(),usage=str(output/'generation-usage.json'));save()
   if trial['status']!='generated_awaiting_independent_verification':raise RuntimeError(r['id']+' did not complete; inspect preserved logs')
  except BaseException as error:
   row.update(status='stopped_api_balance_exhausted' if stopped() else 'failed_requires_inspection',error=type(error).__name__+': '+str(error),finished_unix=time.time());save();raise
  finally:
   if (output/'environment.json').is_file():
    env=json.loads((output/'environment.json').read_text())
    subprocess.run(['docker','stop','--time','10',env['container']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    pid=env.get('gateway_pid');cmd=Path('/proc')/str(pid)/'cmdline'
    if pid and cmd.exists() and str(output/'model-requests.jsonl').encode() in cmd.read_bytes():os.kill(pid,signal.SIGTERM)
 print(ledger)
if __name__=='__main__':main()
