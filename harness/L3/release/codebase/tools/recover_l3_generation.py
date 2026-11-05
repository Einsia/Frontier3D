"""Resume failed L3 authoring in its preserved workspace on a free engine."""
import argparse,fcntl,hashlib,json,os,shutil,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.continue_l3_suite import write
from tools.prepare_l3_trial import assert_engine_available
from tools.l3_generation_retry import run_generation,read_events,latest_session
from tools.l3_trial_status import completion_evidence
from tools.l3_delivery import delivery_feedback,sha
from tools.l3_usage import summarize_requests
from tools.l3_api_control import stopped,BalanceExhausted

def relocated_command(env,engine,gpu,gateway,name):
    cmd=list(env['docker_command'])
    cmd[cmd.index('--name')+1]=name
    cmd[cmd.index('--gpus')+1]='device='+str(gpu)
    for i,arg in enumerate(cmd):
        if arg.startswith('type=bind,src='+env['engine_copy']+','):
            cmd[i]=arg.replace('src='+env['engine_copy']+',','src='+str(engine)+',',1)
        if arg.startswith('type=bind,src='+env['gateway_directory']+','):
            cmd[i]=arg.replace('src='+env['gateway_directory']+',','src='+str(gateway)+',',1)
    return cmd

def recover(root,engine,gpu):
    lockfile=ROOT/'data/l3/locks'/('engine-'+hashlib.sha256(str(engine).encode()).hexdigest()[:16]+'.lock')
    with lockfile.open('a') as lock,(root/'recovery.lock').open('a') as trial_lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(trial_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if stopped():raise BalanceExhausted('Balance exhausted')
        env=json.loads((root/'environment.json').read_text());trial=json.loads((root/'trial.json').read_text())
        allowed={'generation_incomplete_candidate_frozen','generation_failed_before_authoring','recovery_failed'}
        if trial['status'] not in allowed:raise RuntimeError('Trial is not a failed candidate: '+trial['status'])
        old=subprocess.run(['docker','inspect','-f','{{.State.Running}}',env['container']],capture_output=True,text=True,check=True)
        if old.stdout.strip()!='false':raise RuntimeError('Original candidate container still running')
        assert_engine_available(engine)
        workspace=root/'workspace'
        frozen=json.loads((root/'preflight-complete.json').read_text())
        for name,digest in frozen['input_and_material_hashes'].items():
            if name.startswith('input/') or name=='PROMPT.md':
                if sha(workspace/name)!=digest:raise RuntimeError('Task input changed: '+name)
        base=root/'recoveries';base.mkdir(exist_ok=True)
        out=base/('%03d'%(len(list(base.iterdir()))+1));out.mkdir()
        archive=out/'before';archive.mkdir()
        for p in root.iterdir():
            if p.is_file() and p.suffix in {'.json','.jsonl','.log','.txt'}:shutil.copy2(p,archive/p.name)
        shutil.copytree(workspace/'project',archive/'project',ignore=shutil.ignore_patterns('Binaries','Intermediate','Saved','DerivedDataCache','.git'))
        event_paths=[root/'agent-events.jsonl']+[x for x in base.glob('*/agent-events.jsonl')]
        session=None
        for path in event_paths:
            session=latest_session(read_events(path)) or session
        gateway=Path(tempfile.mkdtemp(prefix='l3-recovery-'))
        name=env['container'].split('-recovery-')[0]+'-recovery-'+out.name+'-'+str(os.getpid())
        cmd=relocated_command(env,engine,gpu,gateway,name)
        server=None;started=False;start=time.time()
        trial.update(status='recovering_generation',recovery_directory=str(out),recovery_started_unix=start,model=env['model'])
        write(root/'trial.json',trial)
        try:
            (root/'model-stage.txt').write_text('generation_recovery')
            with (root/'gateway.log').open('a') as log:
                server=subprocess.Popen([sys.executable,str(ROOT/'tools/l3_model_bridge.py'),'serve','--socket',str(gateway/'api.sock'),
                    '--provider',str(ROOT.parent/'.config/3dbench/provider.json'),'--ledger',str(root/'model-requests.jsonl'),
                    '--stage-file',str(root/'model-stage.txt')],stdout=log,stderr=log,start_new_session=True,
                    env={**os.environ,'L3_EXPECTED_MODEL':env['model']})
            for _ in range(100):
                if server.poll() is not None:raise RuntimeError('Gateway exited')
                if (gateway/'api.sock').exists():break
                time.sleep(.1)
            else:raise RuntimeError('Gateway socket missing')
            cid=subprocess.check_output(cmd,text=True).strip();started=True
            env.update(container=name,container_id=cid,docker_command=cmd,engine_copy=str(engine),gateway_directory=str(gateway),gateway_pid=server.pid)
            write(root/'environment.json',env)
            def bridge():
                subprocess.run(['docker','exec','-d',name,'python3','/opt/l3-public/l3_model_bridge.py','bridge','--socket','/model-gateway/api.sock'],check=True)
                time.sleep(1)
            bridge()
            def settle_unfinished(value):
                # Stop only this trial's container to terminate any orphan tool/UE
                # children before resuming. Source and evidence are bind mounted.
                subprocess.run(['docker','stop','--time','15',name],check=True,capture_output=True)
                if subprocess.check_output(['docker','inspect','-f','{{.State.Running}}',name],text=True).strip()!='false':
                    raise RuntimeError('Cannot establish that interrupted tools stopped')
                write(out/('tool-reconciliation-%d.json'%time.time_ns()),{'unfinished_tool_ids':value['unfinished_tool_ids'],'container_stopped':True,'workspace_preserved':True})
                subprocess.run(['docker','start',name],check=True,capture_output=True);bridge()
            args=['docker','exec','-i',name,'codex','exec']
            if session:args+=['resume']
            args+=['--dangerously-bypass-approvals-and-sandbox','--skip-git-repo-check','--json','--model',env['model'],'--output-last-message','/workspace/agent-final.txt']
            if session:args+=[session]
            args+=['-']
            prompt=(workspace/'PROMPT.md').read_text()+'\n\nContinue the original task in this preserved workspace. The user asks you to finish the complete scene and deliverables. The generic equipment fixture is not the requested scene. Inspect the existing source and genuine previews, preserve useful work, complete missing scene and interaction implementation, build, inspect final renders, and deliver all required files. There is no fixed deadline. Use fresh check directories and keep existing evidence. The prior process is stopped; inspect interrupted outputs before relying on them. Do not use hidden evaluation feedback.'
            (out/'prompt.txt').write_text(prompt)
            initial={k.removeprefix('project/'):v for k,v in frozen['input_and_material_hashes'].items() if k.startswith('project/')}
            timing=run_generation(args,prompt.encode(),out,None,completion_feedback=lambda t:delivery_feedback(workspace,t,initial_project=initial),reconcile_unfinished=settle_unfinished)
            subprocess.run(['docker','stop','--time','15',name],check=True,capture_output=True)
            files={str(p.relative_to(workspace/'project')):sha(p) for p in (workspace/'project').rglob('*') if p.is_file() and not set(p.relative_to(workspace/'project').parts)&{'Binaries','Intermediate','Saved','DerivedDataCache','.git'}}
            write(root/'submission-manifest.json',files)
            changed=sorted(k for k in set(files)|set(initial) if (k.startswith(('Source/','Content/','Config/')) or k.endswith('.uproject')) and files.get(k)!=initial.get(k))
            evidence=completion_evidence(workspace,timing)
            status='generated_awaiting_independent_verification' if evidence['delivery_complete'] and changed else 'generation_incomplete_candidate_frozen'
            if timing['generation_status']=='api_balance_exhausted':status='stopped_api_balance_exhausted'
            trial.update(status=status,generation_status=timing['generation_status'],return_code=timing['return_code'],
                elapsed_seconds=(trial.get('elapsed_seconds') or 0)+time.time()-start,finished_unix=time.time(),
                completion_evidence=evidence,scene_files_changed=changed,submission_manifest_sha256=sha(root/'submission-manifest.json'))
            trial.pop('error',None);write(root/'trial.json',trial)
            write(root/'generation-usage.json',summarize_requests(root/'model-requests.jsonl'))
            write(out/'result.json',trial)
            print(json.dumps({'status':status,'model':env['model'],'recovery':str(out)}),flush=True)
        except BaseException as e:
            trial.update(status='recovery_failed',error=type(e).__name__+': '+str(e))
            write(root/'trial.json',trial);raise
        finally:
            if started:subprocess.run(['docker','stop','--time','15',name],capture_output=True)
            if server:
                server.terminate()
                try:server.wait(timeout=15)
                except subprocess.TimeoutExpired:server.kill()
            (root/'model-stage.txt').write_text('post_generation')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--engine',required=True,type=Path);p.add_argument('--gpu',required=True,type=int);a=p.parse_args()
    recover(a.output.resolve(),a.engine.resolve(),a.gpu)
