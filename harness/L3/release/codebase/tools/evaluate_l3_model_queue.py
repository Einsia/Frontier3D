"""Finite evaluation queue for all Luna and Sol L3 submissions."""
import fcntl,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.continue_l3_suite import write,live
def resume_engine(output):
    record=Path(output)/'verification/run.json'
    if not record.exists():return None
    values=json.loads(record.read_text()).get('command',[])
    for value in values:
        if value.startswith('type=bind,src=') and '/engines/' in value:
            return value.split('src=',1)[1].split(',dst=',1)[0]
    return None
def main():
    control=ROOT/'data/l3/evaluations/luna-sol-20261026';control.mkdir(parents=True,exist_ok=True)
    with (control/'controller.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        statefile=control/'state.json'
        slots=json.loads((ROOT/'data/l3/suite-20261023/batch-control/queue-checkpoint.json').read_text())['slots']
        slots=[s for s in slots if s['slot'] in [0,1,3,4]]
        runs=json.loads((ROOT/'tasks/L3/generation-batch.json').read_text())['runs']
        todo=[x for x in runs if x['model'] in {'gpt-6-luna','gpt-6-sol'}]
        todo.sort(key=lambda r:(r['task_key']=='l3-g01',r['task_key'],r['model']))
        saved=json.loads(statefile.read_text()) if statefile.exists() else {}
        active={int(k):v for k,v in saved.get('active',{}).items()}
        done=saved.get('completed',{});errors=saved.get('errors',{});children={}
        while len(done)+len(errors)<len(todo):
            for slot,row in list(active.items()):
                proc=children.get(slot)
                if (proc.poll() is None) if proc else live(row['pid']):continue
                summary=Path(row['output'])/'summary.json'
                if (proc is None or proc.returncode==0) and summary.exists() and json.loads(summary.read_text()).get('status')=='measured':
                    done[row['id']]=json.loads(summary.read_text())['score_100']
                    with (control/'publication.log').open('a') as log:
                        subprocess.run([sys.executable,str(ROOT/'tools/publish_l3_multimodel_scores.py'),'--model',row['model']],cwd=ROOT,stdout=log,stderr=log)
                else:errors[row['id']]={'return_code':proc.returncode if proc else None,'log':row['log']}
                del active[slot];children.pop(slot,None)
            for s in slots:
                if s['slot'] in active:continue
                candidates=[r for r in todo if r['id'] not in done and r['id'] not in errors and not any(x['id']==r['id'] for x in active.values())]
                for r in candidates:
                    trial=ROOT/r['output'];tf=trial/'trial.json'
                    if not tf.exists() or json.loads(tf.read_text()).get('status')!='generated_awaiting_independent_verification':continue
                    out=ROOT/'data/l3/evaluations'/('suite-'+r['model'].removeprefix('gpt-6-')+'-v1')/r['task_key']
                    if (out/'summary.json').exists() and json.loads((out/'summary.json').read_text()).get('status')=='measured':
                        done[r['id']]=json.loads((out/'summary.json').read_text())['score_100'];continue
                    retained=resume_engine(out) if r['task_key']=='l3-g01' else None
                    if retained and Path(retained).resolve()!=Path(s['engine']).resolve():continue
                    env={**os.environ,'L3_EVAL_MODEL':r['model'],'L3_BATCH_CONTROL':str(ROOT/'data/l3/suite-20261023/batch-control'),'L3_API_CONCURRENCY':'10','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','PYTHONUNBUFFERED':'1'}
                    logfile=control/(r['id']+'-'+str(time.time_ns())+'.log')
                    with logfile.open('x') as log:
                        proc=subprocess.Popen([sys.executable,str(ROOT/'tools/evaluate_l3_submission.py'),'--key',r['task_key'],'--engine',s['engine'],'--gpu',str(s['gpu'])],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
                    active[s['slot']]={'id':r['id'],'pid':proc.pid,'model':r['model'],'output':str(out),'log':str(logfile)};children[s['slot']]=proc;break
            write(statefile,{'pid':os.getpid(),'expected':len(todo),'completed':done,'active':active,'errors':errors,'updated_unix':time.time()})
            if (ROOT/'data/l3/suite-20261023/batch-control/balance-exhausted.json').exists() and not active:break
            time.sleep(5)
if __name__=='__main__':main()
