"""Resume a preserved L3 candidate without a deadline, only when explicitly authorized."""
import argparse,fcntl,hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.l3_usage import timed_generation,summarize_requests
from tools.l3_generation_retry import read_events
from tools.l3_trial_status import completion_evidence

def dump(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(root):
    lock=(root/'continuation.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    env=json.loads((root/'environment.json').read_text());trial=json.loads((root/'trial.json').read_text())
    if trial.get('generation_status')=='completed':raise RuntimeError('Already completed; refusing automatic additional authoring')
    if trial.get('status')=='generating':raise RuntimeError('Generation already active')
    events=read_events(root/'agent-events.jsonl')
    session=next(e['thread_id'] for e in events if e.get('type')=='thread.started')
    n=1
    while (root/'continuations'/f'{n:03}').exists():n+=1
    out=root/'continuations'/f'{n:03}';out.mkdir(parents=True)
    archive=out/'before';archive.mkdir()
    for p in root.iterdir():
        if p.is_file() and p.suffix in {'.json','.jsonl','.log','.txt'}:shutil.copy2(p,archive/p.name)
    shutil.copytree(root/'workspace/project',archive/'project',ignore=shutil.ignore_patterns('Binaries','Intermediate','Saved','DerivedDataCache','.git'))
    command=['docker','exec','-i',env['container'],'codex','exec','resume',
             '--dangerously-bypass-approvals-and-sandbox','--skip-git-repo-check','--json',
             '--model',env['model'],'--output-last-message','/workspace/agent-final.txt',session,'-']
    prompt=('Continue this same task from your saved session and existing workspace. The previous process was stopped at the one-hour budget while model-service requests were failing. '
            'The user has explicitly removed the 60-minute limit for this continuation and asks you to finish. There is no generation wall-clock deadline for this continuation. '
            'Complete the original open-world Minecraft village request: inspect interrupted work, fix outstanding issues you identify, build and run the project, inspect genuine multi-view renders, '
            'and finish the required deliverables and final response. Preserve the existing work; do not start a separate scene. '
            'Use new check/output directories so previous logs and previews remain intact. Do not use hidden evaluations. '
            'Conclude with final preview paths, build result, controls and remaining limitations.').encode()
    (out/'resume-prompt.txt').write_bytes(prompt)
    start=time.time()
    record={'status':'running','model':env['model'],'session_id':session,'pid':os.getpid(),'started_unix':start,
            'budget_seconds':None,'user_authorized_unlimited':True,'initial_budget_seconds':3600,'initial_active_seconds':trial.get('elapsed_seconds'),
            'evaluation_status':'deferred_by_user','formal_score':None,'attempts':[]}
    dump(out/'continuation.json',record)
    dump(root/'active-continuation.json',{'directory':str(out),'pid':os.getpid(),'started_unix':start,'budget_seconds':None})
    trial.update(status='generating_continuation',continuation_directory=str(out),budget_seconds=None,initial_budget_seconds=3600,
                 comparable_with_one_hour_baseline=False,benchmark_score=None)
    dump(root/'trial.json',trial)
    subprocess.run(['docker','start',env['container']],check=True,capture_output=True)
    subprocess.run(['docker','exec','-d',env['container'],'python3','/opt/l3-public/l3_model_bridge.py','bridge','--socket','/model-gateway/api.sock'],check=True)
    time.sleep(1)  # Wait for the container-local relay to bind before Codex starts.
    (root/'model-stage.txt').write_text('continuation')
    while True:
        value=timed_generation(command,prompt,out,None,append=bool(record['attempts']),elapsed_offset=time.time()-start)
        record['attempts'].append(value);dump(out/f'attempt-{len(record["attempts"]):03}.json',value)
        dump(out/'continuation.json',record)
        if value['generation_status']=='completed':break
        tail=read_events(out/'agent-events.jsonl')[-12:]
        text=json.dumps(tail).lower()
        transient=any(s in text for s in ['overloaded','rate limit','429','502','503','504','524','stream disconnected','connection reset','timed out','timeout','service unavailable','connection failed','error sending request','waiting for network'])
        if not transient or value.get('unfinished_tool_ids'):break
        record['status']='retrying_service';dump(out/'continuation.json',record)
        time.sleep(min(15*len(record['attempts']),60))
        prompt=b'Continue the same task after the transient model-service failure. The user removed the wall-clock deadline for this continuation. Inspect interrupted work and finish the existing project and final deliverables. Preserve previous evidence in separate output directories.'
        record['status']='running'
    finish=time.time()
    stop=subprocess.run(['docker','stop','--time','10',env['container']],capture_output=True,text=True)
    (out/'container-stop.log').write_text(stop.stdout+stop.stderr)
    record.update(status='completed' if value['generation_status']=='completed' and stop.returncode==0 else 'needs_attention',
                  finished_unix=finish,continuation_elapsed_seconds=finish-start,
                  total_active_seconds=(record['initial_active_seconds'] or 0)+finish-start,
                  generation_status=value['generation_status'],return_code=value['return_code'])
    record['completion_evidence']=completion_evidence(root/'workspace',value)
    if not record['completion_evidence']['delivery_complete']:record['status']='needs_attention'
    if stop.returncode:record['status']='cleanup_failed'
    files={str(p.relative_to(root/'workspace/project')):sha(p) for p in (root/'workspace/project').rglob('*')
           if p.is_file() and not set(p.relative_to(root/'workspace/project').parts)&{'Binaries','Intermediate','Saved','DerivedDataCache','.git'}}
    dump(out/'submission-manifest.json',files)
    record['submission_manifest_sha256']=sha(out/'submission-manifest.json')
    shutil.copy2(out/'submission-manifest.json',root/'submission-manifest.json')
    record['provider_usage']=summarize_requests(root/'model-requests.jsonl','continuation')
    dump(out/'continuation.json',record)
    trial.update(status='generated_evaluation_deferred' if record['status']=='completed' else 'continuation_needs_attention',
                 generation_status=value['generation_status'],elapsed_seconds=record['total_active_seconds'],
                 finished_unix=finish,completion_evidence=record['completion_evidence'],continuation_seconds=finish-start,
                 submission_manifest_sha256=record['submission_manifest_sha256'],evaluation_status='deferred_by_user')
    dump(root/'trial.json',trial)
    (root/'model-stage.txt').write_text('post_generation')
    dump(root/'active-continuation.json',{'directory':str(out),'status':record['status'],'pid':os.getpid(),'finished_unix':finish})
    print(json.dumps({k:record[k] for k in ['status','continuation_elapsed_seconds','total_active_seconds','generation_status']}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--trial',required=True,type=Path);p.add_argument('--unlimited-authorized',required=True,action='store_true')
    a=p.parse_args();run(a.trial.resolve())
