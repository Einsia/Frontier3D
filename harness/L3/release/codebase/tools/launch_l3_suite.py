"""Run two finite generation queues with shared request limits and persistent progress."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.l3_usage import summarize_requests

def write(path,value):
 temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)
def main():
 p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--luna-engine',type=Path,required=True);p.add_argument('--astra-engine',type=Path,required=True);p.add_argument('--luna-gpu',type=int,default=0);p.add_argument('--astra-gpu',type=int,default=3);a=p.parse_args()
 if a.luna_engine.resolve()==a.astra_engine.resolve() or a.luna_gpu==a.astra_gpu:raise ValueError('Workers require separate engines and GPUs')
 control=ROOT/'data/l3/suite-20261023/batch-control';control.mkdir(parents=True,exist_ok=True)
 if (control/'launch.json').exists():raise RuntimeError('Batch already launched; inspect recorded processes before any recovery')
 manifest=a.manifest.resolve();batch=json.loads(manifest.read_text());environment={**os.environ,'L3_BATCH_CONTROL':str(control),'L3_API_CONCURRENCY':'2','PYTHONUNBUFFERED':'1'}
 launch={'supervisor_pid':os.getpid(),'started_unix':time.time(),'expected_runs':28,'api_concurrency_limit':2,'reasoning_effort':'high','generation_time_limit':None,'connection_retry_limit':None,'repository_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'manifest':str(manifest),'workers':[]}
 write(control/'launch.json',launch);workers=[]
 for label,model,engine,gpu in [('luna','gpt-6-luna',a.luna_engine,a.luna_gpu),('astra','gpt-6-astra',a.astra_engine,a.astra_gpu)]:
  cmd=[sys.executable,str(ROOT/'tools/run_l3_suite.py'),'--manifest',str(manifest),'--model',model,'--engine',str(engine.resolve()),'--gpu',str(gpu),'--generate']
  with (control/(label+'.log')).open('x') as log:proc=subprocess.Popen(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=environment,start_new_session=True)
  launch['workers'].append({'model':model,'pid':proc.pid,'gpu':gpu,'engine':str(engine.resolve()),'log':str(control/(label+'.log'))});workers.append(proc);write(control/'launch.json',launch)
 while True:
  rows=[]
  for r in batch['runs']:
   root=ROOT/r['output'];row={k:r[k] for k in ['id','task_key','model','output']};row['status']='not_started'
   try:
    if (root/'trial.json').exists():
     t=json.loads((root/'trial.json').read_text());row.update(status=t['status'],generation_seconds=t.get('elapsed_seconds'),started_unix=t.get('started_unix'),finished_unix=t.get('finished_unix'))
    elif (root/'environment.json').exists():row['status']='prepared'
   except (ValueError,OSError):row['status']='status_write_in_progress'
   if (root/'model-requests.jsonl').exists():row['usage']=summarize_requests(root/'model-requests.jsonl')
   rows.append(row)
  exits=[proc.poll() for proc in workers];complete=sum(r['status']=='generated_awaiting_independent_verification' for r in rows);balance=(control/'balance-exhausted.json').exists()
  state='completed' if complete==28 and all(x==0 for x in exits) else 'stopped_api_balance_exhausted' if balance and all(x is not None for x in exits) else 'stopping_api_balance_exhausted' if balance else 'requires_inspection' if all(x is not None for x in exits) else 'running_with_worker_failure' if any(x not in {0,None} for x in exits) else 'running'
  write(control/'summary.json',{'status':state,'updated_unix':time.time(),'completed':complete,'expected':28,'worker_exit_codes':exits,'runs':rows})
  if all(x is not None for x in exits):break
  time.sleep(10)
 print(state,complete,'/ 28',flush=True)
if __name__=='__main__':main()
