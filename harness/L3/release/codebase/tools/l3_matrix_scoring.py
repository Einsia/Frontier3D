"""Score matrix submissions with the published evidence-aligned protocol."""
import argparse,concurrent.futures,fcntl,json,os,subprocess,sys,time,math,shutil
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R))
from tools.l3_leaderboard_batch import B,read,write,process_matches
from tools.l3_delivery import terminal_complete

def scoring_protocol():
 return read(B/'settings.json',{}).get('scoring_protocol','l3-evidence-aligned-v2')

def review_root():
 protocol=scoring_protocol()
 if protocol not in {'l3-evidence-aligned-v2','l3-perceptual-quality-v5'}:raise ValueError('Unknown scoring protocol')
 return B/'evaluations'/('review-v5' if protocol=='l3-perceptual-quality-v5' else 'review')

def final_measured(folder):
 d=read(Path(folder)/'summary.json',{})
 return d.get('status')=='measured' and d.get('protocol')==scoring_protocol()

def reuse_measurements(row,target):
 """Reuse hash-verified independent measurements, never a legacy visual judgment."""
 from harness.L3.Suite.quality_v5 import digest
 old=B/'evaluations/review'/row['variant']/row['task_key']/row['model']
 base=read(old/'summary.json',{})
 if base.get('status')!='measured' or base.get('protocol')!='l3-evidence-aligned-v2':return None
 runtime=B/'evaluations/runtime'/row['variant']/row['task_key']
 source=read(runtime/'source.json')
 if base['source']['source_sha256']!=source['source_sha256']:raise ValueError('Measurement source changed')
 if source['manifest_sha256']!=digest(Path(row['output'])/'submission-manifest.json'):raise ValueError('Manifest changed')
 for name,sha in base['evidence_sha256'].items():
  src=old/name
  if digest(src)!=sha:raise ValueError('Baseline measurement changed: '+name)
  dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True)
  if not dest.exists():dest.symlink_to(src)
  elif digest(dest)!=sha:raise ValueError('Copied measurement changed: '+name)
 write(target/'baseline-summary.json',base)
 return base

def worker(row):
 from harness.L3.Suite.policy import OUT,POLICY
 from harness.L3.Suite.batch import physical_worker
 from harness.L3.Suite.visual import rubric
 from harness.L3.Suite.reference_review import OUT as REVIEW,CAT
 from harness.L3.Suite.feature_review_v3 import review
 from harness.L3.Suite.physical_v2 import measure,VERSION
 from harness.L3.Suite.aggregate_v2 import summarize
 from harness.L3.MinecraftVillage.algorithm_scores import blend
 from harness.L3.MinecraftVillage.protocol import digest
 from PIL import Image,ImageDraw
 key=row['task_key'];folder=OUT/key;target=REVIEW/key/row['model'];target.mkdir(parents=True,exist_ok=True)
 with (target/'score.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if read(folder/'run.json')['status']!='collected':raise ValueError('Independent collection incomplete')
  state={'pid':os.getpid(),'model':row['model'],'effort':row['effort'],'started_unix':time.time()}
  write(target/'worker.json',{**state,'stage':'measurements'})
  if scoring_protocol()=='l3-perceptual-quality-v5':
   from harness.L3.Suite.quality_v5 import apply
   baseline=reuse_measurements(row,target)
   if baseline:
    write(target/'worker.json',{**state,'stage':'perceptual_quality'})
    result=apply(row,folder,target,baseline)
    if result['status']!='measured':raise ValueError('Quality evidence incomplete')
    write(target/'worker.json',{**state,'stage':'measured','score_100':result['score_100'],'finished_unix':time.time()})
    return
  data=read(CAT/'snapshot.json');task=next(t for t in data['tasks'] if t['key']==key)
  mode=task['input_mode'];weights=POLICY[mode+'_weights']
  image_rows=None
  if key=='l3-g01':
   from tools.l3_matrix_mc import prepare_base
   image_rows=prepare_base(row,folder,target)
  else:
   recovery=read(folder/'rubric-dependency-recovery.json',{})
   while process_matches(recovery.get('pid'),'from harness.L3.Suite.visual import rubric') and not (folder/'rubric-summary.json').exists():
    time.sleep(5)
   with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    quality_future=None
    if scoring_protocol()=='l3-perceptual-quality-v5':
     from harness.L3.Suite.quality_v5 import review as review_quality
     quality_future=pool.submit(review_quality,row,folder,target)
    physics=pool.submit(physical_worker,folder) if not (folder/'geometry.json').exists() or not (folder/'interaction-observations.json').exists() else None
    visual=pool.submit(rubric,folder) if not (folder/'rubric-summary.json').exists() else None
    if physics:physics.result()
    contract=read(folder/'contract.json');roles={e['id']:e['role'] for e in contract['entities']}
    if not (target/'physical/physical-summary.json').exists():
     measure(folder/'physical-scene.json',target/'physical',roles,folder/'motion-episodes',read(folder/'geometry.json'))
    if visual:visual.result()
    if quality_future:quality_future.result()
   physical=read(folder/'geometry.json');inter=read(folder/'interaction-observations.json');vis=read(folder/'rubric-summary.json')
   axes={'layout':blend({'support':physical['support']['score'],'penetration':physical['penetration']['score'],
          'navigation':inter['navigation'],'semantic':vis['axes']['layout_semantics']},POLICY['layout_weights']),
         'interaction':blend({'local':inter['local']['score'],'motion':physical['motion_score']['score'],
          'state_and_workflow':inter['state_and_workflow']},POLICY['interaction_weights']),
         'rubric':blend(vis['axes'],POLICY[mode+'_rubric_weights'])}
   if mode=='image':axes.update(environment={'score':None},objects={'score':None})
   # This is an input record for the final aggregator, never a published score.
   write(folder/'summary.json',{'task_key':key,'model':row['model'],'reasoning_effort':row['effort'],'axes':axes,'weights':weights,
        'mode':mode,'source':read(folder/'source.json'),'score_100':None,'status':'awaiting_final_aggregation','missing_axes':list(weights)})
  run={'model':row['model'],'images':[{'submission_sha256':read(folder/'source.json')['source_sha256']}]}
  if mode=='image' and scoring_protocol()=='l3-evidence-aligned-v2':
   write(target/'worker.json',{**state,'stage':'reference_features'})
   frozen=R/'data/l3/evaluations/review-v2-20261027/feature-v3-references'/key
   ref=REVIEW/'feature-v3-references'/key;ref.parent.mkdir(parents=True,exist_ok=True)
   if not ref.exists():ref.symlink_to(frozen,target_is_directory=True)
   checklist=read(ref/'checklist.json');eligibility=read(ref/'eligibility.json')
   if eligibility['checklist_sha256']!=digest(ref/'checklist.json'):raise ValueError('Reference checklist changed')
   packet=target/'all-view-packet';packet.mkdir(exist_ok=True)
   if image_rows is None:
    metadata=read(folder/'views-metadata.json')
    image_rows=[{'path':str(folder/'workspace/episodes/views'/(name+'.png')),'label':m['label']}
                for name,m in metadata.items() if m['kind']=='view']
   selected=[(Path(m['path']),m) for m in image_rows]
   if not selected:raise ValueError('No independent views')
   for offset in range(0,len(selected),4):
    group=selected[offset:offset+4];sheet=Image.new('RGB',(1600,474*math.ceil(len(group)/2)),(35,35,35));draw=ImageDraw.Draw(sheet)
    for j,(name,m) in enumerate(group):
     p=name;im=Image.open(p).convert('RGB');im.thumbnail((800,450),Image.Resampling.LANCZOS)
     x=j%2*800;y=j//2*474;sheet.paste(im,(x+(800-im.width)//2,y+24+(450-im.height)//2))
     draw.text((x+8,y+5),f'View {offset+j+1}: '+m['label'],fill='white')
    sheet.save(packet/f'candidate-{offset//4:02}.jpg',quality=95)
   write(target/'reference-review.json',{'packet':str(packet),'source_sha256':run['images'][0]['submission_sha256'],'kind':'deterministic_all_view_packet'})
   review(task,run,read(CAT/'assets.json'),checklist)
  result=summarize(task,run,include_reference=scoring_protocol()=='l3-evidence-aligned-v2')
  if scoring_protocol()=='l3-perceptual-quality-v5':
   from harness.L3.Suite.quality_v5 import apply
   write(target/'baseline-summary.json',result)
   write(target/'worker.json',{**state,'stage':'perceptual_quality'})
   result=apply(row,folder,target,result)
  result.update(reasoning_effort=row['effort'],harness=row['harness'],matrix_id=row['id'])
  write(target/'summary.json',result)
  if result['status']!='measured':raise ValueError('Final metrics incomplete: '+str(result['missing_axes']))
  write(target/'worker.json',{**state,'stage':'measured','score_100':result['score_100'],'finished_unix':time.time()})

def active_scores(control_root):
 active={}
 for launchfile in control_root.glob('*/*/*/launch.json'):
  launch=read(launchfile,{})
  if process_matches(launch.get('pid'),'l3_matrix_scoring.py worker'):
   active[launch['id']]={**launch,'launchfile':str(launchfile)}
 return active

def score_worker_limit():
 settings=read(B/'settings.json',{})
 if settings.get('defer_new_evaluations',False):return 0
 return max(1,int(settings.get('scoring_workers',2)))

def controller():
 control=B/'evaluation-control';control.mkdir(exist_ok=True)
 with (control/'scoring.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  children={};control_review=review_root()
  while True:
   # Adopt live score workers after controller recovery before allocating capacity.
   if control_review!=review_root():raise RuntimeError('Scoring protocol changed; restart controller under new version')
   active=active_scores(control_review);publish=False;max_workers=score_worker_limit()
   for launchfile in control_review.glob('*/*/*/launch.json'):
    old=read(launchfile,{})
    if old.get('id') in active or old.get('finished_unix'):continue
    proc=children.pop(old.get('id'),None)
    rc=proc.poll() if proc else None
    measured=final_measured(launchfile.parent)
    old.update(return_code=rc,finished_unix=time.time())
    if measured:old['evidence_status']='measured';publish=True
    else:old['failed_unix']=time.time()
    write(launchfile,old)
   if publish:
    with (B/'matrix-publication.log').open('a') as publication:
     subprocess.run([sys.executable,str(R/'tools/publish_l3_matrix_scores.py')],cwd=R,stdout=publication,stderr=publication)
   for row in read(B/'manifest.json')['rows']:
    if len(active)>=max_workers:break
    if row['status']=='reused' or not row.get('enabled',True) or row['id'] in active:continue
    if not terminal_complete(read(Path(row['output'])/'generation-timing.json',{})):continue
    runtime=B/'evaluations/runtime'/row['variant'];folder=runtime/row['task_key']
    if read(folder/'run.json',{}).get('status')!='collected':continue
    review=control_review/row['variant'];target=review/row['task_key']/row['model'];target.mkdir(parents=True,exist_ok=True)
    if final_measured(target):continue
    old=read(target/'launch.json',{})
    if time.time()-old.get('failed_unix',0)<1800:continue
    env={**os.environ,'L3_EVAL_MODEL':row['model'],'L3_EVAL_EFFORT':row['effort'],'L3_EVAL_TRIAL':row['output'],
      'L3_EVAL_OUT':str(runtime),'L3_REVIEW_OUT':str(review),'L3_EXPERIMENT_BATCH':str(B),'L3_MODEL_GROUP':'openai',
      'L3_MATRIX_JUDGE_PROVIDER':os.environ.get('L3_MATRIX_JUDGE_PROVIDER',str(R.parent/'.config/3dbench/providers/openai.json')),
      'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','PYTHONUNBUFFERED':'1'}
    logfile=target/('scoring-'+str(time.time_ns())+'.log')
    with logfile.open('a') as log:
     p=subprocess.Popen([sys.executable,str(Path(__file__)),'worker','--id',row['id']],cwd=R,env=env,stdout=log,stderr=log,start_new_session=True)
    launch={'pid':p.pid,'id':row['id'],'started_unix':time.time(),'log':str(logfile)}
    write(target/'launch.json',launch);children[row['id']]=p;active[row['id']]=launch
   write(control/'scoring.json',{'pid':os.getpid(),'stage':'scoring' if active else 'waiting','active':active,'max_workers':max_workers,'updated_unix':time.time()})
   time.sleep(15)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['controller','worker']);p.add_argument('--id');a=p.parse_args()
 if a.mode=='controller':controller()
 else:
  allowed=sorted(os.sched_getaffinity(0))
  # Give CPU measurement workers different affinity windows; the old shared
  # first-eight-core mask serialized otherwise independent geometry jobs.
  width=min(8,len(allowed));start=(os.getpid()*width)%len(allowed)
  os.sched_setaffinity(0,[allowed[(start+i)%len(allowed)] for i in range(width)])
  worker(next(r for r in read(B/'manifest.json')['rows'] if r['id']==a.id))
