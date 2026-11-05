from pathlib import Path
"""Isolated collection for the fourteen suite submissions; no generation writes."""
import argparse,concurrent.futures,json,os,pathlib,shutil,subprocess,time,traceback
from .policy import ROOT,BATCH,OUT,MODEL,MODEL_SLUG,task_paths,read,write,POLICY,submission_trial
from .plans import view_plan,workflow_plan,local_plan
from tools.capture_l3_algorithms import replay_timeout
from harness.L3.MinecraftVillage.protocol import digest,tree_digest
IMAGE=os.environ.get('L3_UE_IMAGE','3dbench-l3-agent:ue5.8.3-codex0.163.0')
ENGINE=Path(os.environ.get('L3_UE_ROOT',str(ROOT.parent/'engines/UE_5.8.3_source/UnrealEngine-release')))
def prepare(key):
 trial=submission_trial(key);folder=OUT/key;folder.mkdir(parents=True,exist_ok=True)
 project=folder/'workspace/project';task=task_paths()[key]
 generation=read(trial/'trial.json')
 if generation.get('status')!='generated_awaiting_independent_verification' or generation.get('model')!=MODEL:
  raise ValueError('Submission is not completed for requested model: '+key+'/'+MODEL)
 from .submission_binding import validate_submission
 validate_submission(trial,key,MODEL,os.environ.get('L3_EVAL_EFFORT'))
 plugin=project/'Plugins/BenchRuntime'
 if (folder/'source.json').exists():return folder
 cache_record=read(folder/'trusted-cache-seed.json') if (folder/'trusted-cache-seed.json').exists() else None
 if not project.exists():
  shutil.copytree(trial/'workspace/project',project,ignore=shutil.ignore_patterns('Binaries','Intermediate','Saved','DerivedDataCache'))
  plugin=project/'Plugins/BenchRuntime'
  shutil.rmtree(plugin)
  shutil.copytree(ROOT/'ue5/BenchRuntime',plugin)
  # Same observer measurements, fixed 5 Hz sampling to bound evidence volume.
  cpp=plugin/'Source/BenchRuntime/Private/BenchObserver.cpp'
  s=cpp.read_text();s=s.replace('TickIndex%2==0','TickIndex%12==0');cpp.write_text(s)
  public=folder/'public';public.mkdir()
  shutil.copy2(ROOT/'ue5/agent_environment/ue.py',public/'ue.py')
  (folder/'workspace/.home').mkdir();(folder/'workspace/.cache/ue').mkdir(parents=True)
  from tools.l3_eval_cache import seed_evaluation_cache
  cache_record=seed_evaluation_cache(folder/'workspace/.cache/ue')
  if cache_record:write(folder/'trusted-cache-seed.json',cache_record)
 if cache_record is None:
  from tools.l3_eval_cache import seed_prepared_evaluation_cache
  cache_record=seed_prepared_evaluation_cache(folder)
 bindings=read(project/'bindings.json');contract=read(task/'environment/input/interaction-contract.json')
 from .route_translation import executable_bindings
 # Keep route translation's original prompt/cache identity unchanged.
 bindings=executable_bindings(bindings,contract,task,folder)
 from .binding_hints import normalize_bindings
 bindings,hint_audit=normalize_bindings(bindings)
 hint_audit['submitted_bindings_sha256']=digest(project/'bindings.json')
 write(folder/'binding-hints-audit.json',hint_audit)
 write(folder/'contract.json',contract);write(folder/'policy.json',POLICY)
 for kind,maker in [('views',view_plan),('workflow',workflow_plan),('local',local_plan)]:
  plan,meta=maker(bindings) if kind=='views' else maker(bindings,contract)
  write(folder/'workspace/plans'/f'{kind}.json',plan);write(folder/f'{kind}-metadata.json',meta)
 write(folder/'source.json',{'trial':str(trial),'model':MODEL,'task':str(task),'manifest_sha256':digest(trial/'submission-manifest.json'),
      'source_sha256':tree_digest(trial/'workspace/project'),'reasoning_effort':generation.get('reasoning_effort','high'),'verification_source_sha256':tree_digest(project),
      'observer_sha256':tree_digest(plugin),'policy_sha256':digest(folder/'policy.json'),'trusted_cache':cache_record})
 return folder
def collect(key,engine,gpu):
 folder=prepare(key);workspace=folder/'workspace';project=workspace/'project';record=read(folder/'source.json')
 record.update(status='starting',task_key=key,started_unix=time.time(),episodes={})
 state=folder/'run.json'
 if state.exists() and read(state).get('status')=='collected':return
 name='l3-suite-eval-'+key+'-'+MODEL_SLUG+'-'+__import__('hashlib').sha256(str(folder).encode()).hexdigest()[:8]
 command=['docker','run','-d','--name',name,'--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
  '--cpus','12','--memory','48g','--pids-limit','4096','--shm-size','2g','--gpus','device='+str(gpu),
  '--user',f'{os.getuid()}:{os.getgid()}','-e','HOME=/workspace/.home','-e','UE5_ROOT='+str(ENGINE),
  '-e','NVIDIA_DRIVER_CAPABILITIES=graphics,utility,compute','-e','UE_LocalDataCachePath=/workspace/.cache/ue']
 for host,dest,ro in [(workspace,'/workspace',False),(folder/'public','/opt/l3-public',True),(engine,str(ENGINE),False)]:
  command+=['--mount',f'type=bind,src={host},dst={dest}'+(',readonly' if ro else '')]
 command+=[IMAGE];record.update(container=name,command=command);write(state,record)
 def run(label,args,timeout=3600):
  record['status']=label;write(state,record)
  with (folder/(label+'.log')).open('a') as log:
   p=subprocess.run(['docker','exec',name,*args],stdout=log,stderr=log,timeout=timeout)
  if p.returncode:raise RuntimeError(label+' failed: '+str(p.returncode))
 try:
  check=subprocess.run(['docker','inspect',name],capture_output=True,timeout=20)
  exists=check.returncode==0
  if exists:
   info=json.loads(check.stdout)[0]
   mounts={m['Destination']:m['Source'] for m in info['Mounts']}
   if mounts.get('/workspace')!=str(workspace):raise RuntimeError('Container belongs to another workspace')
   if mounts.get(str(ENGINE))!=str(engine):
    if info['State']['Running']:raise RuntimeError('Cannot remount an active evaluator container')
    write(folder/('container-before-rebind-'+str(time.time_ns())+'.json'),info)
    subprocess.run(['docker','rm',name],check=True,capture_output=True,timeout=30);exists=False
  startup=subprocess.run(['docker','start',name] if exists else command,capture_output=True,text=True,timeout=180)
  (folder/'container-start.log').write_text(startup.stdout+startup.stderr)
  if startup.returncode:raise RuntimeError('Container startup failed')
  build=workspace/'build'
  if not (folder/'built.json').exists():
   if build.exists():shutil.move(build,workspace/('build-failed-'+str(time.time_ns())))
   run('build',['python3','/opt/l3-public/ue.py','build','/workspace/project','--output','/workspace/build','--jobs','12','--blueprints'])
   write(folder/'built.json',{'completed':True})
  for kind in ['views','workflow','local']:
   dest=workspace/'episodes'/kind
   if not (dest/'completed.json').exists():
    if dest.exists():shutil.move(dest,dest.with_name(kind+'-failed-'+str(time.time_ns())))
    from .replay_budget import retry_budget
    timeout,budget_evidence=retry_budget(read(workspace/'plans'/f'{kind}.json'),workspace/'episodes',kind,folder/(kind+'.log'))
    write(folder/(kind+'-walltime-budget.json'),{'timeout_seconds':timeout,'evidence':budget_evidence})
    args=['python3','/opt/l3-public/ue.py','preview','/workspace/project','--output','/workspace/episodes/'+kind,
              '--plan','/workspace/plans/'+kind+'.json','--timeout',str(timeout)]
    while True:
     try:
      run(kind,args,timeout+60);break
     except RuntimeError:
      if kind!='local':raise
      from .crash_recovery import crashing_invoke,checked_crashes
      plan_path=workspace/'plans/local.json';plan=read(plan_path)
      crashed=crashing_invoke(dest,plan)
      if crashed is None:raise
      probes=checked_crashes(folder)
      if crashed['name'] in probes:raise RuntimeError('Repeated already isolated crash')
      original=workspace/'plans/local-original.json'
      if not original.exists():shutil.copy2(plan_path,original)
      archive=dest.with_name('local-candidate-crash-'+str(time.time_ns()))
      shutil.move(dest,archive)
      log=archive/'candidate-crash.log'
      shutil.copyfile(archive/'editor.log',log)
      probes[crashed['name']]={'step':crashed,'status':'candidate_assertion_failure',
          'log':str(log.relative_to(folder)),'log_sha256':digest(log),
          'episode':str(archive.relative_to(folder))}
      write(folder/'crash-probes.json',{'source_sha256':record['source_sha256'],
          'original_plan_sha256':digest(original),'probes':probes})
      # The failure remains scored; only its crashing dispatch is omitted from
      # a fresh local-test process so unrelated checks can produce evidence.
      plan['steps']=[step for step in plan['steps'] if step.get('name')!=crashed['name']]
      write(plan_path,plan)
      record['isolated_candidate_crashes']=list(probes);write(state,record)
   record['episodes'][kind]={'completed':read(dest/'completed.json')['completed']};write(state,record)
  assert tree_digest(project)==record['verification_source_sha256'],'Verifier project modified'
  record.update(status='collected',finished_unix=time.time(),
   evidence_sha256={str(p.relative_to(folder)):digest(p) for p in (workspace/'episodes').rglob('*') if p.is_file() and p.suffix in ['.json','.png']})
  write(state,record)
 except Exception as error:
  record.update(status='failed',error=str(error));write(state,record);raise
 finally:
  try:
   stopped=subprocess.run(['docker','stop','--time','10',name],capture_output=True,text=True,timeout=30)
   write(folder/'container-stop.json',{'container':name,'return_code':stopped.returncode,'stderr':stopped.stderr})
  except subprocess.TimeoutExpired:
   write(folder/'container-stop.json',{'container':name,'timed_out':True,'timeout_seconds':30})
def batch():
 keys=sorted(task_paths())
 for key in keys:prepare(key)
 slots=read(OUT/'engine-copies.json')
 def worker(slot,assigned):
  pid=slot['pid']
  while pathlib.Path('/proc',str(pid)).exists():
   stat=pathlib.Path('/proc',str(pid),'stat').read_text()
   if ') Z ' in stat:break
   time.sleep(5)
  for key in assigned:
   try:collect(key,pathlib.Path(slot['engine']),slot['gpu'])
   except Exception:traceback.print_exc()
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  futures=[pool.submit(worker,s,keys[i::2]) for i,s in enumerate(slots)]
  for f in futures:f.result()
if __name__=='__main__':batch()

