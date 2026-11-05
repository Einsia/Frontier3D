"""Finite Astra evaluation batch: collection, visual judging, algorithms and complete aggregation."""
import concurrent.futures,os,time,traceback
from .policy import ROOT,OUT,MODEL,POLICY,task_paths,read,write
from harness.L3.MinecraftVillage.algorithm_scores import blend
from .measure import observations,geometry
from .visual import rubric,references
def evaluator_sources():
 from pathlib import Path
 return [*Path(__file__).parent.glob('*.py'),*(ROOT/'harness/L3/MinecraftVillage').glob('*.py'),*(ROOT/'src/evaluator').glob('*.py')]
def summarize(folder):
 physical=read(folder/'geometry.json');inter=read(folder/'interaction-observations.json');visual=read(folder/'rubric-summary.json')
 task=task_paths()[folder.name];image=(task/'environment/input/references').exists();mode='image' if image else 'text'
 layout=blend({'support':physical['support']['score'],'penetration':physical['penetration']['score'],'navigation':inter['navigation'],
  'semantic':visual['axes']['layout_semantics']},POLICY['layout_weights'])
 interaction=blend({'local':inter['local']['score'],'motion':physical['motion_score']['score'],'state_and_workflow':inter['state_and_workflow']},POLICY['interaction_weights'])
 rub=blend(visual['axes'],POLICY[mode+'_rubric_weights'])
 axes={'layout':layout,'interaction':interaction,'rubric':rub}
 if image:
  ref=read(folder/'reference-summary.json')
  axes.update(environment={'score':ref['environment_score'],'method':ref['method']},objects={'score':ref['objects_score'],'method':ref['method']})
 total=blend({k:v['score'] for k,v in axes.items()},POLICY[mode+'_weights'])
 write(folder/'scoring-policy.json',POLICY)
 result={'task_key':folder.name,'model':MODEL,'protocol':POLICY['version'],'mode':mode,'weights':POLICY[mode+'_weights'],
  'score_100':None if total['score'] is None else total['score']*100,'axes':axes,'missing_axes':total['missing'],
  'status':'measured' if total['score'] is not None else 'incomplete','source':read(folder/'source.json'),
  'scoring_policy_sha256':__import__('hashlib').sha256((folder/'scoring-policy.json').read_bytes()).hexdigest(),
  'counts':{'required_entities':len(read(folder/'contract.json')['entities']),'workflow_predicates':len(inter['goals']),
   'workflow_passed_predicates':sum(x['passed'] for x in inter['goals']),'navigation_segments':len(inter['walks'])},
  'evidence_files':['scoring-policy.json','geometry-exclusions.json','geometry.json','static-geometry.json','support-geometry.json','interaction-observations.json','rubric-summary.json']+(['reference-summary.json'] if image else []),
  'completed_unix':time.time(),'evaluator_files':{str(p.relative_to(ROOT)):__import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in evaluator_sources()}}
 if (folder/'geometry-supplement/result.json').exists():
  result['geometry_supplement']=read(folder/'geometry-supplement/result.json')
  result['evidence_files'].append('geometry-supplement/result.json')
 for name in ['reviewed-ground.json','crash-probes.json']:
  if (folder/name).exists():result['evidence_files'].append(name)
 if (folder/'crash-probes.json').exists():
  from .crash_recovery import checked_crashes
  crashes=checked_crashes(folder)
  result['candidate_failures']=[{'probe':name,**row['step'],'status':row['status'],'evidence':row['log']} for name,row in crashes.items()]
  result['evidence_files']+=list(dict.fromkeys(row['log'] for row in crashes.values()))
 result['collection_record_sha256']=__import__('hashlib').sha256((folder/'run.json').read_bytes()).hexdigest()
 write(folder/'summary.json',result);return result
def physical_worker(folder):
 import subprocess,sys
 env=os.environ.copy();env['PYTHONFAULTHANDLER']='1'
 for key in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS']:env[key]='1'
 # TBB respects process affinity at initialization; limit exact-solid workers too.
 allowed=sorted(os.sched_getaffinity(0));offset=(sorted(task_paths()).index(folder.name)*8)%len(allowed);cpus=(allowed+allowed)[offset:offset+min(8,len(allowed))]
 code="import os,runpy,sys;os.sched_setaffinity(0,"+repr(cpus)+");sys.argv=['measure',sys.argv[1]];runpy.run_module('harness.L3.Suite.measure',run_name='__main__')"
 with (folder/'physical-worker.log').open('a') as log:
  p=subprocess.Popen([sys.executable,'-u','-c',code,folder.name],cwd=ROOT,env=env,stdout=log,stderr=log)
  write(folder/'physical-worker.json',{'pid':p.pid,'started_unix':time.time(),'cpu_limit':8})
  result=p.wait()
  record=read(folder/'physical-worker.json')
  record.update(return_code=result,finished_unix=time.time())
  write(folder/'physical-worker.json',record)
 if result:raise RuntimeError('Physical worker exited '+str(result)+'; see '+str(folder/'physical-worker.log'))
def visual_worker(folder):
 if not (folder/'rubric-summary.json').exists():rubric(folder)
 if not (folder/'reference-summary.json').exists():references(folder)
def batch():
 keys=sorted(task_paths());jobs={};done=set();errors={}
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
  while len(done)<len(keys):
   for key in keys:
    folder=OUT/key
    if key in done:continue
    if (folder/'summary.json').exists() and read(folder/'summary.json')['status']=='measured':done.add(key);errors.pop(key,None);continue
    state=read(folder/'run.json') if (folder/'run.json').exists() else {}
    if state.get('status')=='failed':errors[key]={'phase':'collection','error':state.get('error')};continue
    if (folder/'workspace/episodes/views/completed.json').exists() and (key,'visual') not in jobs:
     jobs[(key,'visual')]=pool.submit(visual_worker,folder)
    if state.get('status')=='collected' and (key,'physical') not in jobs:
     jobs[(key,'physical')]=pool.submit(physical_worker,folder)
    pair=[jobs.get((key,phase)) for phase in ['visual','physical']]
    for phase in ['visual','physical']:
     future=jobs.get((key,phase))
     if future and future.done() and future.exception():
      errors[key]={'phase':phase,'error':type(future.exception()).__name__+': '+str(future.exception())[:500]}
      write(folder/(phase+'-failure.json'),errors[key])
    if all(f is not None and f.done() and f.exception() is None for f in pair):
     try:
      result=summarize(folder)
      if result['status']=='measured':done.add(key);errors.pop(key,None);print(key,result['score_100'],flush=True)
      else:errors[key]={'phase':'aggregation','missing_axes':result['missing_axes']}
     except Exception as e:errors[key]={'phase':'aggregation','error':type(e).__name__+': '+str(e)[:500]}
   write(OUT/'evaluation-progress.json',{'completed':sorted(done),'total':len(keys),'errors':errors,'updated_unix':time.time(),
    'jobs':{key+'/'+phase:('failed' if f.done() and f.exception() else 'finished' if f.done() else ('running' if f.running() else 'queued')) for (key,phase),f in jobs.items()}})
   if len(done)==len(keys):break
   if errors and all(key in done or key in errors for key in keys):break
   time.sleep(5)
if __name__=='__main__':batch()

