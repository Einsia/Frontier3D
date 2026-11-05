"""Persistent native-harness L3 experiment queue, with provider-separated recovery."""
import argparse,concurrent.futures,fcntl,hashlib,json,os,shutil,signal,subprocess,sys,tempfile,time,traceback
from pathlib import Path
R=Path(__file__).resolve().parents[1]
B=Path(os.environ.get('L3_EXPERIMENT_BATCH',str(R/'runs/l3')))
P=Path(os.environ.get('L3_PROVIDER_DIR',str(R.parent/'.config/3dbench/providers')))
CLI=Path(os.environ.get('L3_NATIVE_CLI',str(R/'third_party/experiment-cli/node_modules')))
IMAGE=os.environ.get('L3_UE_IMAGE','3dbench-l3-agent:ue5.8.3-codex0.163.0')
_CONTRACT=json.loads((Path(__file__).resolve().parents[5]/'configs/release/model-harness-contract.json').read_text())
_NATIVE={'codex':'codex','claude-code':'claude','zcode':'zcode','kimi-codecli':'kimi','deepseek-harness':'dsh','gemini-cli':'gemini'}
VARIANTS=[(row['model'],_NATIVE[row['harness_id']],'openai',row['effort']) for row in _CONTRACT['models'] if row['in_final_145_score_group']]
sys.path.insert(0,str(R))
def read(p,default=None):
    try:return json.loads(Path(p).read_text())
    except (FileNotFoundError,ValueError):return default

def write(p,d):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+f'.{os.getpid()}.tmp');t.write_text(json.dumps(d,indent=2)+'\n');t.replace(p)

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def engine_slot_count():return sum(read(B/'settings.json',{'group_workers':{'openai':8,'claude':8,'china':4}})['group_workers'].values())
def variant(m,e):return m+'--'+e

def row_enabled(row):return row.get('enabled',True)

def probe_ready(state):return state.get('status')=='passed' and state.get('reference_image_count',0)>0 and state.get('image_observed_in_model_request') is True

def initialize():
    if (B/'manifest.json').exists():return
    tasks=[]
    for p in sorted((R/'tasks/L3').glob('*/task.json')):
        d=read(p)
        if d.get('execution_status')=='generation_ready':tasks.append((d['key'],p.parent))
    assert len(tasks)==15,len(tasks)
    settings=read(B/'settings.json',{})
    configured=settings.get('variants')
    variants=[(r['model'],r['harness'],r['group'],r['effort']) for r in configured] if configured else VARIANTS
    selected=set(settings.get('tasks',[]))
    rows=[]
    for m,h,g,e in variants:
        for key,task in sorted(tasks):
            if selected and key not in selected:continue
            rows.append({'id':key+'--'+variant(m,e),'task_key':key,'task_path':str(task),
                'task_manifest_sha256':sha(task/'package-manifest.json'),'model':m,'harness':h,
                'group':g,'effort':e,'variant':variant(m,e),'status':'queued','enabled':True,
                'reuse_source':None,'output':str(B/'runs'/key/variant(m,e))})
    if selected-set(k for k,_ in tasks):raise ValueError('Unknown selected tasks')
    if not rows:raise ValueError('Empty campaign')
    commit=subprocess.run(['git','rev-parse','HEAD'],cwd=R,text=True,capture_output=True)
    write(B/'manifest.json',{'created_unix':time.time(),'source_commit':commit.stdout.strip() if commit.returncode==0 else None,
        'scope':'Fresh generation; no historical candidate reuse','rows':rows})
    print('manifest',len(rows),'reused',0,flush=True)

def next_attempt(output):
    numbers=[]
    for p in [*output.glob('attempt-*.json'),*output.glob('agent-events-*.jsonl'),*(output/'workspace').glob('native-result-*.json')]:
        tail=p.stem.rsplit('-',1)[-1]
        if tail.isdigit():numbers.append(int(tail))
    return max(numbers,default=0)+1

def gateway_env(group,model,effort):return dict(os.environ,PYTHONPATH=str(R),L3_EXPERIMENT_BATCH=str(B),L3_MODEL_GROUP=group,L3_MULTIMODEL_GATEWAY='1',L3_EXPECTED_MODEL=model,L3_EXPECTED_EFFORT=effort)

def native_command(row,prompt,result,refs):
    cmd=['python3','/opt/l3-public/l3_native_agent.py','--harness',row['harness'],'--model',row['model'],'--effort',row['effort'],'--prompt',prompt,'--result',result]
    for ref in refs:cmd+=['--image',ref]
    # Docker already isolates the task. Native DSH workspace-write would block
    # UE's dedicated engine, cache and /dev/shm paths outside the project cwd.
    if row['harness']=='dsh':cmd=['env','DSH_PERMISSION_MODE=danger-full-access',*cmd]
    return cmd

def probe(row):
    from tools.prepare_l3_trial import codex_config
    out=B/'probes'/row['variant'];out.mkdir(parents=True,exist_ok=True)
    with (out/'probe.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        prior=read(out/'status.json',{})
        if probe_ready(prior) and (row['harness']!='dsh' or prior.get('ue_write_permission') is True):return
        n=len(list(out.glob('attempt-*')))+1;trial=out/f'attempt-{n:03}';w=trial/'workspace';(w/'project').mkdir(parents=True);(w/'.home').mkdir();(w/'.codex').mkdir()
        (w/'.codex/config.toml').write_text(codex_config(row['model'],row['effort']))
        public=trial/'public';public.mkdir()
        shutil.copy2(Path(__file__).resolve().parents[5]/'configs/release/model-harness-contract.json',public/'model-harness-contract.json')
        for name in ['l3_native_agent.py','l3_model_bridge.py','l3_usage.py','l3_api_control.py']:shutil.copy2(R/'tools'/name,public/name)
        task=Path(row['task_path']);shutil.copytree(task/'environment/input',w/'input')
        refs=['/workspace/input/'+x['path'] for x in read(w/'input/references.json')['images']]
        (w/'probe.txt').write_text('Connection and tool preflight only. Inspect the supplied reference image with your image-reading tool. Use a file-writing or shell tool to create /workspace/project/probe-ok.txt containing one sentence describing the scene you saw. Do not build or author a scene. Then briefly confirm completion.')
        if row['harness']=='dsh':
            (trial/'engine-canary').mkdir()
            with (w/'probe.txt').open('a') as f:f.write('\nAlso use your Bash tool to write a file named l3-write-canary.txt containing OK in each of /workspace/.cache/ue, /workspace/checks, /engine-canary and /dev/shm. Create directories if needed. These are environment capability checks only. Do not change any scene files.')
        sock=Path(tempfile.mkdtemp(prefix='l3-batch-probe-'))/'api.sock';env=gateway_env(row['group'],row['model'],row['effort'])
        (trial/'model-stage.txt').write_text('native_preflight')
        log=(trial/'gateway.log').open('w');server=subprocess.Popen([sys.executable,str(R/'tools/l3_model_bridge.py'),'serve','--socket',str(sock),'--provider',str(P/(row['group']+'.json')),'--ledger',str(trial/'model-requests.jsonl'),'--stage-file',str(trial/'model-stage.txt')],env=env,stdout=log,stderr=log,start_new_session=True)
        name='l3-matrix-probe-'+hashlib.sha256(str(trial).encode()).hexdigest()[:12]
        status={'status':'running','pid':os.getpid(),'container':name,'attempt':str(trial),'reference_image_count':len(refs),'started_unix':time.time()};write(out/'status.json',status)
        try:
            cmd=['docker','run','-d','--name',name,'--network','none','--cap-drop','ALL','--security-opt','no-new-privileges','--cpus','2','--memory','4g','--user',f'{os.getuid()}:{os.getgid()}','-w','/workspace/project','-e','HOME=/workspace/.home','-e','CODEX_HOME=/workspace/.codex','-e','L3_MODEL_API_KEY=local-bridge-no-secret']
            for source,target in [(w,'/workspace'),(sock.parent,'/model-gateway'),(public,'/opt/l3-public'),(CLI,'/opt/cli/node_modules')]:cmd+=['--mount',f'type=bind,src={source},dst={target}'+('' if source==w else ',readonly')]
            if row['harness']=='dsh':cmd+=['--mount',f'type=bind,src={trial}/engine-canary,dst=/engine-canary']
            subprocess.run(cmd+[IMAGE],check=True,stdout=subprocess.DEVNULL,timeout=180)
            subprocess.run(['docker','exec','-d',name,'python3','/opt/l3-public/l3_model_bridge.py','bridge','--socket','/model-gateway/api.sock'],check=True)
            with (trial/'native-events.jsonl').open('w') as f:
                result=subprocess.run(['docker','exec','-i',name,*native_command(row,'/workspace/probe.txt','/workspace/native-result.json',refs)],stdout=f,stderr=subprocess.STDOUT,timeout=900)
            native=read(w/'native-result.json',{})
            evidence=[]
            if (trial/'model-requests.jsonl').exists():
                for line in (trial/'model-requests.jsonl').read_text().splitlines():
                    try:evidence.append(json.loads(line))
                    except ValueError:pass
            image_received=any(v.get('image_count',0)>0 and v.get('event')=='request_started' for v in evidence)
            ok=result.returncode==0 and native.get('completed') and (w/'project/probe-ok.txt').is_file() and image_received
            status['image_observed_in_model_request']=image_received
            if row['harness']=='dsh':
                disk_ok=all(p.is_file() for p in [w/'.cache/ue/l3-write-canary.txt',w/'checks/l3-write-canary.txt',trial/'engine-canary/l3-write-canary.txt'])
                shm=subprocess.run(['docker','exec',name,'test','-f','/dev/shm/l3-write-canary.txt'],capture_output=True,timeout=10)
                status['ue_write_permission']=disk_ok and shm.returncode==0
                ok=ok and status['ue_write_permission']
            status.update(status='passed' if ok else 'failed',return_code=result.returncode,native=native,finished_unix=time.time())
        except Exception as ex:status.update(status='failed',error=str(ex),finished_unix=time.time())
        finally:
            server.terminate();log.close();write(out/'status.json',status)
            try:subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=20)
            except subprocess.TimeoutExpired:pass
        print(row['variant'],status['status'],flush=True)

def native_configuration_failure(log):
    """Only native terminal/startup errors can disable automatic retries."""
    markers=('invalid api key','unsupported model','unsupported effort','invalid reasoning','unknown option','command not found')
    messages=[]
    for line in log.splitlines():
        try:event=json.loads(line)
        except ValueError:
            # Candidate shell output is not a launcher configuration error.
            if line.lstrip().lower().startswith(('error:', 'codex:', 'claude:', 'kimi:', 'dsh:', 'zcode:')):
                messages.append(line)
            continue
        if not isinstance(event,dict):continue
        if event.get('type')=='result' and event.get('is_error'):
            messages.append(str(event.get('result',''))+' '+str(event.get('errors','')))
        elif event.get('type') in {'error','turn.failed'}:
            messages.append(str(event.get('message',''))+' '+str(event.get('error','')))
    return any(word in message.lower() for message in messages for word in markers)

def ensure_trial_container_running(environment):
    from tools.prepare_l3_trial import docker_running_snapshot
    container=environment['container']
    snapshot=docker_running_snapshot()
    engine=environment.get('engine_copy')
    if snapshot is not None and engine:
        for info in snapshot:
            if '/'+container in info.get('Names',[]):continue
            if any(Path(m['Source']).resolve()==Path(engine).resolve() for m in info['Mounts']):
                raise RuntimeError('Dedicated resume engine is occupied by '+str(info.get('Names',info.get('Id'))))
    if snapshot is not None and any('/'+container in info.get('Names',[]) for info in snapshot):
        return 'already_running'
    inspection=subprocess.run(['docker','inspect',container],capture_output=True,timeout=20)
    if inspection.returncode:
        subprocess.run(environment['docker_command'],check=True,stdout=subprocess.DEVNULL,timeout=180)
        return 'created'
    subprocess.run(['docker','start',container],stdout=subprocess.DEVNULL,check=True,timeout=180)
    return 'started'


def worker(row,slot):
    from tools.prepare_l3_trial import prepare
    from tools.run_l3_trial import run as preflight
    from tools.l3_delivery import delivery_feedback
    from tools.l3_usage import summarize_requests
    out=Path(row['output']);out.mkdir(parents=True,exist_ok=True)
    with (out/'worker.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        os.environ.update(gateway_env(row['group'],row['model'],row['effort']))
        status=read(out/'state.json',{})
        if status.get('error'):status['last_failure']={'error':status.pop('error'),'failed_unix':status.get('failed_unix')}
        status.update(python_executable=sys.executable,status='preparing',pid=os.getpid(),slot=slot,started_unix=status.get('started_unix',time.time()));write(out/'state.json',status)
        engine=(B/'engines'/f'slot-{slot:02}').resolve();gpu=read(B/'settings.json',{}).get('gpu_ids',[0])[slot%len(read(B/'settings.json',{}).get('gpu_ids',[0]))];container=None;gateway=None
        try:
            if not (out/'environment.json').exists():
                prepare(R,out,engine,gpu,row['model'],Path(row['task_path']),row['effort'],P/(row['group']+'.json'),native_cli=CLI,cpus=8)
            environment=read(out/'environment.json');container=environment['container'];gateway=environment['gateway_pid']
            # Recover only this trial's own container and host gateway.
            ensure_trial_container_running(environment)
            socket=Path(environment['gateway_directory'])/'api.sock'
            if not process_matches(gateway,'l3_model_bridge.py'):
                socket.unlink(missing_ok=True);f=(out/'gateway-recovery.log').open('a')
                gp=subprocess.Popen([sys.executable,str(R/'tools/l3_model_bridge.py'),'serve','--socket',str(socket),'--provider',str(P/(row['group']+'.json')),'--ledger',str(out/'model-requests.jsonl'),'--stage-file',str(out/'model-stage.txt')],stdout=f,stderr=f,start_new_session=True)
                gateway=gp.pid;environment['gateway_pid']=gateway;write(out/'environment.json',environment)
            bridge_check='import socket,subprocess; s=socket.socket(); s.settimeout(2); active=s.connect_ex(("127.0.0.1",8765))==0; s.close(); subprocess.Popen(["python3","/opt/l3-public/l3_model_bridge.py","bridge","--socket","/model-gateway/api.sock"],stdout=open("/workspace/bridge.log","a"),stderr=subprocess.STDOUT,start_new_session=True) if not active else None'
            subprocess.run(['docker','exec',container,'python3','-c',bridge_check],check=True,timeout=180)
            if not (out/'equipment-ready.json').exists():
                preflight(out,equipment_only=True)
                check=read(out/'trial.json',{})
                if check.get('equipment_status')!='ready':raise RuntimeError('Equipment preflight did not complete')
                write(out/'equipment-ready.json',{'ready':True,'time':time.time()})
            w=out/'workspace';initial={k.removeprefix('project/'):v for k,v in read(out/'preflight-complete.json')['input_and_material_hashes'].items() if k.startswith('project/')}
            status.update(status='generating',generation_started_unix=status.get('generation_started_unix',time.time()));write(out/'state.json',status)
            (out/'model-stage.txt').write_text('generation');feedback=None
            while True:
                if (B/'control'/row['group']/'balance-exhausted.json').exists():raise RuntimeError('Provider balance exhausted')
                # A native tool may terminate the container loopback bridge; repair it before retry.
                subprocess.run(['docker','exec',container,'python3','-c',bridge_check],check=True,timeout=180)
                n=next_attempt(out)
                prompt=(w/'PROMPT.md').read_text()
                if n>1:prompt+='\n\nContinue the existing project in /workspace/project. Inspect its source, build logs and previews; preserve useful work and finish all public requirements. The previous CLI invocation ended before delivery was confirmed.'
                environment_note=out/'continuation-environment-note.txt'
                if n>1 and environment_note.exists():prompt+='\n'+environment_note.read_text()
                if feedback:prompt+='\n'+feedback
                (w/'active-prompt.md').write_text(prompt)
                result_path=w/f'native-result-{n:04}.json';started=time.time()
                with (out/f'agent-events-{n:04}.jsonl').open('w') as log:
                    proc=subprocess.Popen(['docker','exec','-i',container,*native_command(row,'/workspace/active-prompt.md','/workspace/'+result_path.name,environment['reference_images'])],stdout=log,stderr=subprocess.STDOUT)
                    status.update(status="generating",attempt=n,agent_pid=proc.pid,last_attempt_started_unix=started);write(out/'state.json',status);rc=proc.wait()
                native=read(result_path,{})
                timing={'generation_status':'completed' if rc==0 and native.get('completed') else 'process_error','terminal_event':'turn.completed' if rc==0 and native.get('completed') else None,'elapsed_seconds':time.time()-status['generation_started_unix'],'return_code':rc}
                write(out/f'attempt-{n:04}.json',{'native':native,'timing':timing});write(out/'generation-timing.json',timing)
                write(out/'usage.json',summarize_requests(out/'model-requests.jsonl'))
                feedback=delivery_feedback(w,timing,True,initial)
                if not feedback:
                    frozen={str(p.relative_to(w/'project')):sha(p) for p in (w/'project').rglob('*') if p.is_file() and not set(p.relative_to(w/'project').parts)&{'Intermediate','Saved','DerivedDataCache','.git'}}
                    write(out/'submission-manifest.json',{'files':frozen,'model':row['model'],'effort':row['effort'],'harness':row['harness'],'task_manifest_sha256':row['task_manifest_sha256'],'generation_interventions':read(out/'user-interventions.json',[]),'native_user_intervention':native.get('user_intervention')})
                    status.update(status='generated',finished_unix=time.time(),evaluation_status='pending');write(out/'trial.json',{'status':'generated_awaiting_independent_verification','model':row['model'],'reasoning_effort':row['effort'],'harness':row['harness'],'benchmark_score':None});break
                status.update(last_feedback=feedback,last_return_code=rc,status='retry_wait' if rc else 'delivery_continuation');write(out/'state.json',status)
                # Configuration failures require an explicit repair, not an endless billed retry.
                tail=(out/f'agent-events-{n:04}.jsonl').read_text(errors='replace')[-12000:].lower()
                if rc and native_configuration_failure(tail):raise RuntimeError('Native configuration failure; see preserved attempt log')
                time.sleep(min(300,15*2**min(n,4)) if rc else 2)
        except Exception as ex:
            status.update(status='failed',error=str(ex),failed_unix=time.time());(out/'failure-trace.txt').write_text(traceback.format_exc())
        finally:
            cleanup=read(out/'environment.json',{})
            container=container or cleanup.get('container');gateway=gateway or cleanup.get('gateway_pid')
            if container:
                try:subprocess.run(['docker','stop','--time','20',container],capture_output=True,timeout=30)
                except subprocess.TimeoutExpired:pass
            if gateway and process_matches(gateway,'l3_model_bridge.py'):
                try:os.kill(gateway,signal.SIGTERM)
                except ProcessLookupError:pass
            write(out/'state.json',status)

def process_matches(pid,part):
    try:return part.encode() in Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ')
    except (FileNotFoundError,TypeError):return False


def trial_agent_live(row,state):
    """A recycled PID is live only if it still runs this trial's native agent."""
    container=read(Path(row['output'])/'environment.json',{}).get('container')
    if not container:return False
    try:
        argv=Path(f"/proc/{int(state.get('agent_pid'))}/cmdline").read_bytes().split(b'\0')
    except (OSError,TypeError,ValueError):return False
    return (len(argv)>5 and Path(os.fsdecode(argv[0])).name=='docker'
            and argv[1:4]==[b'exec',b'-i',container.encode()]
            and b'/opt/l3-public/l3_native_agent.py' in argv[4:])


def pending_engine_reservations(rows):
    reserved={}
    for row in rows:
        if not row_enabled(row) or row.get('status')=='reused':continue
        out=Path(row['output'])
        if read(out/'state.json',{}).get('status')=='generated':continue
        engine=read(out/'environment.json',{}).get('engine_copy')
        if not engine:continue
        slot=int(Path(engine).name.removeprefix('slot-'))
        reserved.setdefault(slot,set()).add(row['id'])
    return reserved


def controller():
    B.mkdir(parents=True,exist_ok=True)
    with (B/'controller.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:print('Controller already running');return
        manifest=read(B/'manifest.json');rows=[r for r in manifest['rows'] if r['status']!='reused' and row_enabled(r)]
        active={};started=time.time()
        while True:
            recover_incomplete_deliveries()
            manifest=read(B/'manifest.json');rows=[r for r in manifest['rows'] if r['status']!='reused' and row_enabled(r)]
            # Rediscover live workers after controller replacement. Never duplicate a live worker.
            for row in rows:
                s=read(Path(row['output'])/'state.json',{})
                if (process_matches(s.get('pid'),'worker --id '+row['id']) or trial_agent_live(row,s)) and s.get('slot') is not None:active[s['slot']]=row['id']
            for slot,rid in list(active.items()):
                row=next(r for r in rows if r['id']==rid);s=read(Path(row['output'])/'state.json',{})
                if not process_matches(s.get('pid'),'worker --id '+row['id']) and not trial_agent_live(row,s):active.pop(slot)
            counts={};groups={g:0 for g in ['openai','claude','china']}
            for rid in active.values():groups[next(r for r in rows if r['id']==rid)['group']]+=1
            caps=read(B/'settings.json',{'group_workers':{'openai':8,'claude':8,'china':4}})['group_workers']
            ready_slots=[i for i in range(engine_slot_count()) if (B/'engines'/f'slot-{i:02}.ready').exists() and i not in active]
            # Round-robin across efforts/models: one task of every supported variant first.
            ordered=sorted(rows,key=lambda r:(r['task_key'],r['variant']))
            reservations=pending_engine_reservations(rows)
            for row in ordered:
                s=read(Path(row['output'])/'state.json',{});state=s.get('status','queued');counts[state]=counts.get(state,0)+1
                if state=='generated' or row['id'] in active.values() or not ready_slots:continue
                if groups[row['group']]>=caps[row['group']]:continue
                probe_state=read(B/'probes'/row['variant']/'status.json',{})
                if not probe_ready(probe_state):continue
                if row['harness']=='dsh' and probe_state.get('ue_write_permission') is not True:continue
                if (B/'control'/row['group']/'balance-exhausted.json').exists():continue
                runtime_repaired=state=='failed' and 'No module named \'numpy\'' in s.get('error','') and s.get('python_executable')!=sys.executable
                if state=='failed' and not runtime_repaired and (time.time()-s.get('failed_unix',0)<1800 or 'configuration failure' in s.get('error','')):continue
                if shutil.disk_usage(B).free<150*1024**3:continue
                out=Path(row['output']);existing=read(out/'environment.json',{})
                if existing:
                    slot=int(Path(existing['engine_copy']).name.removeprefix('slot-'))
                    if slot not in ready_slots:continue
                    ready_slots.remove(slot)
                else:
                    unreserved=[slot for slot in ready_slots if slot not in reservations]
                    if not unreserved:continue
                    slot=unreserved[0];ready_slots.remove(slot)
                out.mkdir(parents=True,exist_ok=True)
                log=(out/'worker.log').open('a');proc=subprocess.Popen([sys.executable,str(Path(__file__)),'worker','--id',row['id'],'--slot',str(slot)],stdout=log,stderr=log,start_new_session=True,cwd=R)
                write(out/'state.json',{**s,'status':'starting','pid':proc.pid,'slot':slot,'launched_unix':time.time()});active[slot]=row['id'];groups[row['group']]+=1
            write(B/'controller.json',{'pid':os.getpid(),'started_unix':started,'updated_unix':time.time(),'active':active,'active_by_provider':groups,'counts':counts,'reused':sum(r['status']=='reused' for r in manifest['rows'] if row_enabled(r)),'paused':sum(not row_enabled(r) for r in manifest['rows']),'active_total':sum(row_enabled(r) for r in manifest['rows']),'new_total':len(rows)})
            if counts.get('generated',0)==len(rows):break
            time.sleep(20)

def _provision():
    seed=B/'engines/seed'
    while process_matches(950730,'rsync'):time.sleep(10)
    if (B/'engine-seed-copy.log').read_text().strip():raise RuntimeError('Seed copy emitted errors')
    if not (seed/'Engine/Binaries/Linux/UnrealEditor-Cmd').is_file():raise RuntimeError('Incomplete engine seed')
    def copy(i):
        dest=B/'engines'/f'slot-{i:02}';ready=dest.with_suffix('.ready')
        if ready.exists():return
        dest.mkdir(exist_ok=True)
        with (B/'engines'/f'copy-{i:02}.log').open('a') as f:subprocess.run(['rsync','-a',str(seed)+'/',str(dest)+'/'],stdout=f,stderr=f,check=True)
        ready.write_text(str(time.time()));print('engine ready',i,flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(copy,range(engine_slot_count())))

def provision():
    with (B/'provision.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        _provision()

def recover_misclassified_native_errors():
    repaired=[]
    for row in read(B/'manifest.json',{}).get('rows',[]):
        if not row_enabled(row) or row.get('status')=='reused':continue
        out=Path(row['output']);state=read(out/'state.json',{})
        if state.get('status')!='failed' or state.get('error')!='Native configuration failure; see preserved attempt log':continue
        if process_matches(state.get('pid'),'worker --id '+row['id']) or trial_agent_live(row,state):continue
        n=state.get('attempt',0);log=out/f'agent-events-{n:04}.jsonl'
        native=read(out/'workspace'/f'native-result-{n:04}.json',{})
        if not log.exists() or not native or native.get('completed') or native.get('return_code')==0:continue
        if native_configuration_failure(log.read_text(errors='replace')[-12000:]):continue
        write(out/'infrastructure-attempts'/('misclassified-native-'+str(time.time_ns())+'.json'),state)
        state.update(error='Native invocation interrupted; automatic retry allowed',failed_unix=0,
                     recovery_reason='Candidate tool-output text is not a native configuration error',
                     recovery_eligible_unix=time.time())
        write(out/'state.json',state);repaired.append(row['id'])
    return repaired


def recover_incomplete_deliveries():
    """Keep authored files, but require a successful native finish before evaluation."""
    from tools.l3_delivery import terminal_complete
    repaired=[]
    for row in read(B/'manifest.json',{}).get('rows',[]):
        if not row_enabled(row) or row.get('status')=='reused':continue
        out=Path(row['output']);state=read(out/'state.json',{})
        if state.get('status')!='generated' or terminal_complete(read(out/'generation-timing.json',{})):continue
        if process_matches(state.get('pid'),'worker --id '+row['id']+' ') or trial_agent_live(row,state):continue
        archive=out/'infrastructure-attempts'/('incomplete-terminal-'+str(time.time_ns()))
        archive.mkdir(parents=True)
        for name in ['state.json','trial.json','generation-timing.json','submission-manifest.json']:
            if (out/name).exists():shutil.copy2(out/name,archive/name)
        write(out/'state.json',{**state,'status':'failed','failed_unix':0,'evaluation_status':'generation_incomplete',
              'error':'Native invocation ended without successful terminal event; resume existing workspace',
              'recovery_evidence':str(archive)})
        trial=read(out/'trial.json',{});trial.update(status='generation_interrupted',benchmark_score=None);write(out/'trial.json',trial)
        repaired.append(row['id'])
    return repaired


def recover():
    """Idempotent heartbeat entry; inspect before spawning and keep evidence."""
    launch=read(B/'launch.json',{});result={'checked_unix':time.time(),'launched':{},'repaired_native_failures':recover_misclassified_native_errors(),'incomplete_deliveries':recover_incomplete_deliveries()}
    for mode in ['controller','provision']:
        if mode=='provision' and all((B/'engines'/f'slot-{i:02}.ready').exists() for i in range(engine_slot_count())):continue
        if process_matches(launch.get(mode),'l3_leaderboard_batch.py '+mode):continue
        f=(B/(mode+'.log')).open('a');proc=subprocess.Popen([sys.executable,str(Path(__file__)),mode],stdout=f,stderr=f,start_new_session=True,cwd=R)
        launch[mode]=proc.pid;result['launched'][mode]=proc.pid
    # Check actual create admission, not only Docker info/ping.
    name='l3-matrix-recovery-health-'+str(os.getpid())
    try:
        check=subprocess.run(['docker','create','--name',name,'--network','none',IMAGE,'true'],capture_output=True,text=True,timeout=30)
        result['docker_create_ready']=check.returncode==0;result['docker_create_return_code']=check.returncode
    except subprocess.TimeoutExpired:result['docker_create_ready']=False;result['docker_error']='create timed out'
    finally:
        try:subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=10)
        except subprocess.TimeoutExpired:pass
    if result['docker_create_ready']:
        names=set(read(B/'orphaned-containers.json',{}).get('containers',[]))
        for p in (B/'probes').glob('*/status.json'):
            d=read(p,{})
            if d.get('status')=='failed' and d.get('container'):names.add(d['container'])
        def cleanup(name):
            if not name.startswith('l3-matrix-'):return {'name':name,'skipped':True}
            try:
                done=subprocess.run(['docker','rm','-f',name],capture_output=True,text=True,timeout=10)
                return {'name':name,'return_code':done.returncode}
            except subprocess.TimeoutExpired:return {'name':name,'timed_out':True}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:result['cleanup']=list(pool.map(cleanup,sorted(names)))
    if result['docker_create_ready'] and not process_matches(launch.get('probes'),'l3_leaderboard_batch.py probes'):
        f=(B/'probes.log').open('a');proc=subprocess.Popen([sys.executable,str(Path(__file__)),'probes'],stdout=f,stderr=f,start_new_session=True,cwd=R)
        launch['probes']=proc.pid;result['launched']['probes']=proc.pid
    if not process_matches(launch.get('collection'),'l3_matrix_collection.py'):
        f=(B/'matrix-collection.log').open('a')
        proc=subprocess.Popen([sys.executable,str(R/'tools/l3_matrix_collection.py')],stdout=f,stderr=f,start_new_session=True,cwd=R)
        launch['collection']=proc.pid;result['launched']['collection']=proc.pid
    if not process_matches(launch.get('scoring'),'l3_matrix_scoring.py controller'):
        f=(B/'matrix-scoring.log').open('a')
        proc=subprocess.Popen([sys.executable,str(R/'tools/l3_matrix_scoring.py'),'controller'],stdout=f,stderr=f,start_new_session=True,cwd=R)
        launch['scoring']=proc.pid;result['launched']['scoring']=proc.pid
    if not process_matches(launch.get('publication'),'publish_l3_matrix_scores.py'):
        f=(B/'matrix-publication.log').open('a')
        proc=subprocess.Popen([sys.executable,str(R/'tools/publish_l3_matrix_scores.py')],stdout=f,stderr=f,start_new_session=True,cwd=R)
        launch['publication']=proc.pid;result['launched']['publication']=proc.pid
    write(B/'launch.json',launch);write(B/'recovery-latest.json',result)
    print(json.dumps(result),flush=True)

if __name__=='__main__':
    runtime=R/'.venv/bin/python'
    if runtime.exists() and Path(sys.prefix).resolve()!=(R/'.venv').resolve():os.execv(str(runtime),[str(runtime),str(Path(__file__)),*sys.argv[1:]])
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['init','probes','probe','controller','worker','provision','status','recover']);p.add_argument('--id');p.add_argument('--slot',type=int);a=p.parse_args()
    if a.mode=='init':initialize()
    elif a.mode=='recover':recover()
    elif a.mode=='provision':provision()
    elif a.mode=='status':print(json.dumps(read(B/'controller.json'),indent=2))
    elif a.mode=='controller':controller()
    elif a.mode in {'worker','probe'}:
        row=next(r for r in read(B/'manifest.json')['rows'] if r['id']==a.id)
        worker(row,a.slot) if a.mode=='worker' else probe(row)
    else:
        rows={}
        for r in read(B/'manifest.json')['rows']:
            if r['status']!='reused' and row_enabled(r) and read(Path(r['task_path'])/'task.json')['input_mode']=='image':rows.setdefault(r['variant'],r)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(probe,rows.values()))
