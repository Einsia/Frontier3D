"""Append an explicitly selected model to the finite L3 queue without stopping active trials."""
import argparse,copy,fcntl,json,os,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.validate_l3_suite import validate_task,sha
from tools.continue_l3_suite import live,write

def extend_batch(batch,model,extra_tasks=()):
    if model not in {'gpt-6-luna','gpt-6-sol','gpt-6-astra'}:
        raise ValueError('Unsupported model')
    slug=model.removeprefix('gpt-6-')
    result=copy.deepcopy(batch);existing={r['id']:r for r in result['runs']}
    if len(existing)!=len(result['runs']):raise ValueError('Duplicate run IDs')
    templates={}
    for run in batch['runs']:
        key=run['task_key']
        if key in templates:
            for field in ['task_path','package_manifest_sha256']:
                if templates[key][field]!=run[field]:raise ValueError('Mismatched model inputs: '+key)
        else:templates[key]=run
    for task in extra_tasks:
        key=task['task_key']
        if key in templates:
            for field in ['task_path','package_manifest_sha256']:
                if templates[key][field]!=task[field]:raise ValueError('Conflicting task package: '+key)
        else:templates[key]=task
    added=[]
    for key,template in templates.items():
        run={'id':key+'-'+slug,'task_key':key,'task_path':template['task_path'],'model':model,
             'package_manifest_sha256':template['package_manifest_sha256'],'status':'not_started',
             'reasoning_effort':'high','output':str(Path(template['output']).parent/slug)}
        if run['id'] in existing:
            for field in ['task_key','task_path','model','package_manifest_sha256','output']:
                if existing[run['id']][field]!=run[field]:raise ValueError('Conflicting existing run '+run['id'])
            continue
        result['runs'].append(run);added.append(run)
    result['total_runs']=len(result['runs'])
    return result,added

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--model',required=True,choices=['gpt-6-sol','gpt-6-luna','gpt-6-astra'])
    parser.add_argument('--task',type=Path,action='append',default=[],help='Include an additional frozen task package')
    args=parser.parse_args();cp=args.checkpoint.resolve();control=cp.parent
    with (control/'model-admission.lock').open('a') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=json.loads(cp.read_text());manifest=Path(state['manifest']);batch=json.loads(manifest.read_text())
        extra=[]
        for selected in args.task:
            task=selected.resolve();checked=validate_task(task);key=checked['task_key']
            extra.append({'task_key':key,'task_path':str(task.relative_to(ROOT)),
                          'package_manifest_sha256':checked['manifest_sha256'],
                          'output':str(Path(batch['runs'][0]['output']).parent.parent/key/'template')})
        expanded,added=extend_batch(batch,args.model,extra)
        if not added:
            print(json.dumps({'status':'already_queued','model':args.model,'total_runs':len(batch['runs'])}));return
        for run in added:
            task=ROOT/run['task_path'];validate_task(task)
            if sha(task/'package-manifest.json')!=run['package_manifest_sha256']:raise RuntimeError('Task package changed')
            if (ROOT/run['output']).exists():raise RuntimeError('Existing output requires inspection: '+run['id'])
        pid=state['supervisor_pid'];cmd=Path('/proc',str(pid),'cmdline')
        if not live(pid) or b'tools/continue_l3_suite.py' not in cmd.read_bytes():raise RuntimeError('Expected queue controller is not running')
        os.kill(pid,signal.SIGTERM)
        for _ in range(100):
            if not live(pid):break
            time.sleep(.1)
        if live(pid):raise RuntimeError('Queue controller did not stop; no queue files changed')
        # Active generation workers have their own process groups and keep running.
        lock=(control/'continuation-controller.lock').open('a')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=json.loads(cp.read_text())
        archive=control/('add-'+args.model+'-'+str(time.time_ns()));archive.mkdir()
        (archive/'generation-batch.json').write_bytes(manifest.read_bytes())
        (archive/'queue-checkpoint.json').write_bytes(cp.read_bytes())
        before={slot:job['pid'] for slot,job in state['active_workers'].items()}
        state['pending_runs'] += [r['id'] for r in added]
        partition=state['completed_runs']+[j['run_id'] for j in state['active_workers'].values()]+state['pending_runs']+list(state.get('failed_runs',{}))
        if len(partition)!=len(set(partition)) or set(partition)!={r['id'] for r in expanded['runs']}:
            raise RuntimeError('Queue partition is not complete and unique; original files are archived')
        write(manifest,expanded);write(cp,state)
        lock.close()
        env={**os.environ,'L3_BATCH_CONTROL':str(control),'L3_API_CONCURRENCY':'10','PYTHONUNBUFFERED':'1'}
        with (control/'queue-controller.log').open('ab') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'tools/continue_l3_suite.py'),'--checkpoint',str(cp)],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
        models=list(dict.fromkeys(r['model'] for r in expanded['runs']))
        write(control/'queue-controller-process.json',{'pid':child.pid,'models':models,'time_unix':time.time(),'python':sys.executable})
        result={'model':args.model,'reasoning_effort':'high','added_runs':[r['id'] for r in added],'total_runs':len(expanded['runs']),
                'api_concurrency_limit':10,'controller_pid':child.pid,'preserved_worker_pids':before,'archive':str(archive),'time_unix':time.time()}
        write(archive/'admission.json',result);print(json.dumps(result))
if __name__=='__main__':main()
