"""Publish scored matrix variants without changing existing high results."""
import copy,datetime,fcntl,json,os,signal,subprocess,sys,time,urllib.request
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R))
from tools.l3_leaderboard_batch import B,read,write
from tools.publish_l3_suite_scores import CAT,sha,published_asset
from tools.l3_publication_metadata import score_csv,generation_accounting
from PIL import Image
from harness.L3.Suite.independent_views import selected_views

def isolate_protocol(data, rows, protocol):
 """Keep historical reports reachable without mixing them into current means."""
 changed=[];enabled={(r['task_key'],r['variant']) for r in rows if r.get('enabled')}
 for task in data['tasks']:
  if task.get('level')!=3:continue
  stale=[e for e in task.get('evaluation_results',[]) if (task['key'],e.get('model_id')) in enabled and e.get('protocol')!=protocol]
  for e in stale:
   identity=(e.get('model_id'),e.get('matrix_summary_sha256'))
   history=task.setdefault('evaluation_history',[])
   if not any((h.get('model_id'),h.get('matrix_summary_sha256'))==identity for h in history):history.append(e)
   task['evaluation_results'].remove(e)
   for result in task.get('model_results',[]):
    if result['model_id']==e['model_id']:
     result.setdefault('historical_reports',[]).append({'protocol':e.get('protocol'),'report':copy.deepcopy(result.get('report',{})),'evidence_links':e.get('evidence_links',{})})
     result.update(status='pending',report={},scoring_protocol=protocol,scoring_status='awaiting_versioned_rescore')
   for run in task.get('generation_runs',[]):
    if run['model']==e['model_id']:
     run.pop('score',None);run.pop('evaluation_result',None)
   changed.append({'task':task['key'],'variant':e['model_id'],'archived_protocol':e.get('protocol')})
 data.setdefault('l3_publication',{})['active_matrix_protocol']=protocol
 return changed

def schedule_variants(data,rows):
 scheduled=[]
 variants={r['variant']:r for r in rows if r['status']!='reused'}
 for variant,row in variants.items():
  label=row['model']+' · '+row['effort']
  if not any(m['id']==variant for m in data['models']):
   data['models'].append({'id':variant,'label':label,'base_model':row['model'],'reasoning_effort':row['effort']})
  changed=False
  for task in data['tasks']:
   if task.get('level')!=3:continue
   if not any(x['model_id']==variant for x in task.get('model_results',[])):
    task.setdefault('model_results',[]).append({'model_id':variant,'label':label,'scheduled':True,
     'status':'pending' if row.get('enabled',True) else 'paused','reasoning_effort':row['effort'],'base_model':row['model'],
     'batch_id':'l3-leaderboard-20261028','report':{},'usage':{}})
    changed=True
   else:
    result=next(x for x in task['model_results'] if x['model_id']==variant)
    desired='pending' if row.get('enabled',True) else 'paused'
    if result.get('status') in {'pending','paused'} and result['status']!=desired:
     result['status']=desired;changed=True
  if changed:scheduled.append(variant)
 return scheduled

def retire_pending_variants(data, retired_models, retired_variants=()):
 retired=set(retired_models)
 variants={m['id'] for m in data['models'] if m.get('base_model') in retired and '--' in m['id']} | set(retired_variants)
 removed=[]
 for task in data['tasks']:
  if task.get('level')!=3:continue
  kept=[]
  for result in task.get('model_results',[]):
   if result['model_id'] in variants and result.get('status') in {'pending','paused'}:
    removed.append((task['key'],result['model_id']))
   else:kept.append(result)
  task['model_results']=kept
 used={r['model_id'] for t in data['tasks'] for r in t.get('model_results',[])}
 data['models']=[m for m in data['models'] if m['id'] not in variants or m['id'] in used]
 return removed

def publish():
 output=B/'evaluations/publication';output.mkdir(parents=True,exist_ok=True)
 with (output/'publication.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  from tools.l3_matrix_scoring import review_root,scoring_protocol
  protocol=scoring_protocol();available=[]
  for row in read(B/'manifest.json')['rows']:
   if row['status']=='reused':continue
   if protocol!='l3-evidence-aligned-v2' and not row.get('enabled'):continue
   folder=review_root()/row['variant']/row['task_key']/row['model']
   result=read(folder/'summary.json',{})
   if result.get('status')=='measured' and result.get('protocol')==protocol:available.append((row,folder,result))
  with (CAT/'publication.lock').open('a') as shared:
   fcntl.flock(shared,fcntl.LOCK_EX)
   data=read(CAT/'snapshot.json');assets=read(CAT/'assets.json');downloads=read(CAT/'downloads.json');manifest=read(CAT/'manifest.json')
   old_models={'gpt-6-astra','gpt-6-luna','gpt-6-sol'}
   preserved={t['key']:copy.deepcopy([x for x in t.get('model_results',[]) if x['model_id'] in old_models]) for t in data['tasks'] if t.get('level')==3}
   other=copy.deepcopy([t for t in data['tasks'] if t.get('level')!=3]);changed=[]
   batch_manifest=read(B/'manifest.json')
   archived=isolate_protocol(data,batch_manifest['rows'],protocol) if protocol!='l3-evidence-aligned-v2' else []
   if protocol!='l3-evidence-aligned-v2':
    initial=read(output/'quality-v5-history-backup.json',{})
    if initial:
     old_downloads=read(Path(initial['backup'])/'downloads.json')
     for key in initial['restore_keys']:
      if key in old_downloads:downloads[key]=old_downloads[key]
   retired=retire_pending_variants(data,batch_manifest.get('retired_models',[]),batch_manifest.get('retired_variants',[]))
   scheduled=schedule_variants(data,batch_manifest['rows'])
   for row,folder,result in available:
    key=row['task_key'];variant=row['variant'];task=next(t for t in data['tasks'] if t['key']==key)
    existing=next((x for x in task.get('evaluation_results',[]) if x.get('model_id')==variant),{})
    if existing.get('matrix_summary_sha256')==sha(folder/'summary.json') and (protocol=='l3-evidence-aligned-v2' or protocol in existing.get('evidence_links',{}).get('summary.json','')):continue
    assert result['model']==row['model'] and result['reasoning_effort']==row['effort'] and not result['missing_axes']
    assert result['protocol']==protocol and 0<=result['score_100']<=100
    assert abs(sum(result['weights'].values())-1)<1e-8
    assert abs(sum(result['axes'][k]['score']*v*100 for k,v in result['weights'].items())-result['score_100'])<1e-7
    assert result['evidence_sha256']=={name:sha(folder/name) for name in result['evidence_files']}
    runtime=B/'evaluations/runtime'/variant/key;source=read(runtime/'source.json')
    assert source['source_sha256']==result['source']['source_sha256'] and source['trial']==row['output']
    assert source['manifest_sha256']==sha(Path(row['output'])/'submission-manifest.json')
    from harness.L3.Suite.submission_binding import validate_submission
    validate_submission(Path(row['output']),key,row['model'],row['effort'])
    label=row['model']+' · '+row['effort']
    if not any(m['id']==variant for m in data['models']):data['models'].append({'id':variant,'label':label,'base_model':row['model'],'reasoning_effort':row['effort']})
    # Declare the fixed 15-task denominator for this variant.
    for t in data['tasks']:
     if t.get('level')!=3:continue
     if not any(x['model_id']==variant for x in t.get('model_results',[])):
      t.setdefault('model_results',[]).append({'model_id':variant,'label':label,'scheduled':True,'status':'pending','reasoning_effort':row['effort'],'batch_id':'l3-leaderboard-20261028','report':{},'usage':{}})
    links={}
    for name in ['summary.json',*result['evidence_files']]:
     assetkey=key+'-'+variant+'-evaluation-'+('' if protocol=='l3-evidence-aligned-v2' else protocol+'-')+name.replace('/','-');downloads[assetkey]=published_asset(folder/name);links[name]='/downloads/'+assetkey
    images=[];record=read(runtime/'run.json')
    if (runtime/'image-manifest.json').exists():
     image_manifest=read(runtime/'image-manifest.json')
     assert image_manifest['source_sha256']==source['source_sha256']
     image_rows=image_manifest['images']
    else:
     image_rows=[{'path':str(runtime/'workspace/episodes/views'/(name+'.png')),'label':meta['label'],
       'sha256':record['evidence_sha256']['workspace/episodes/views/'+name+'.png']}
       for name,meta in selected_views(runtime)]
    for meta in image_rows:
     p=Path(meta['path'])
     assert p.resolve().is_relative_to(runtime.resolve()) and meta['sha256']==sha(p)
     assetkey=key+'-'+variant+'-verified-'+sha(p)[:20];assets[assetkey]=published_asset(p)
     with Image.open(p) as im:width,height=im.size
     images.append({'url':'/media/'+assetkey,'label':meta['label'],'width':width,'height':height,'source':str(p),'source_sha256':sha(p),
                    'submission_sha256':source['source_sha256'],'kind':'independent_render'})
    assert images
    trial=Path(row['output']);timing=read(trial/'generation-timing.json');usage=read(trial/'usage.json',{})
    score=result['score_100'];row_result=next(x for x in task['model_results'] if x['model_id']==variant)
    row_result.update(status='scored',kind='l3_suite_evaluated',base_model=row['model'],
      scoring_protocol=protocol,scoring_status='measured',
      report={'score':score/100,'score_valid':True,'case_pass':(bool(result['playability']['continuous_workflow']) if result.get('playability',{}).get('continuous_workflow') is not None else None),'axes':result['axes']},
      usage=generation_accounting(usage,row['model'],timing['elapsed_seconds']))
    run={'model':variant,'base_model':row['model'],'label':label,'effort':row['effort'],'harness':row['harness'],'status':'completed',
      'status_label':'已生成','completed':True,'score':score,'seconds':timing['elapsed_seconds'],'images':images,'image_source':'independent_verifier',
      'trial_path':str(trial),'usage':usage,'evaluation_result':{'score_100':score,'axes':result['axes']}}
    task['generation_runs']=[x for x in task.get('generation_runs',[]) if x['model']!=variant]+[run]
    evaluation={**result,'model_id':variant,'evidence_links':links,'matrix_summary_sha256':sha(folder/'summary.json')}
    task['evaluation_results']=[x for x in task.get('evaluation_results',[]) if x.get('model_id')!=variant]+[evaluation]
    changed.append({'id':row['id'],'variant':variant,'task':key,'score_100':score,'image':images[0]['url']})
   if not changed and not scheduled and not retired and not archived:return
   assert other==[t for t in data['tasks'] if t.get('level')!=3]
   for t in data['tasks']:
    if t.get('level')==3:assert preserved[t['key']]==[x for x in t['model_results'] if x['model_id'] in old_models]
   now=datetime.datetime.now(datetime.timezone.utc).isoformat();data['generated_utc']=now
   count=sum(x.get('status')=='measured' for t in data['tasks'] if t.get('level')==3 for x in t.get('evaluation_results',[]))
   data.setdefault('l3_publication',{}).update(evaluated_runs=count);data['counts']['l3_evaluated_runs']=count
   csv=output/'catalog_scores.csv';prior=Path(downloads['catalog_scores.csv']['path']);assert sha(prior)==downloads['catalog_scores.csv']['sha256']
   csv.write_text(score_csv(prior.read_text(),data['tasks']));downloads['catalog_scores.csv']=published_asset(csv)
   backup=output/('backup-'+str(time.time_ns()));backup.mkdir()
   for name,value in [('snapshot.json',data),('assets.json',assets),('downloads.json',downloads)]:
    (backup/name).write_bytes((CAT/name).read_bytes());write(CAT/(name+'.next'),value);os.replace(CAT/(name+'.next'),CAT/name)
   (backup/'manifest.json').write_bytes((CAT/'manifest.json').read_bytes())
   manifest.update(generated_utc=now,l3_publication=data['l3_publication']);manifest['files']={n:sha(CAT/n) for n in ['snapshot.json','assets.json','downloads.json']}
   write(CAT/'manifest.json.next',manifest);os.replace(CAT/'manifest.json.next',CAT/'manifest.json')
   runtime=read(CAT/'server-runtime.json');proc=Path('/proc',str(runtime['pid']))
   args=[x.decode() for x in (proc/'cmdline').read_bytes().split(b'\0') if x]
   env=dict(x.decode().split('=',1) for x in (proc/'environ').read_bytes().split(b'\0') if x)
   assert env.get('PORT')=='5224' and str(R/'website/l3-catalog/server.mjs') in args
   os.kill(runtime['pid'],signal.SIGTERM)
   for _ in range(50):
    if not proc.exists() or ') Z ' in (proc/'stat').read_text():break
    time.sleep(.1)
   with (output/'server.log').open('ab') as log:p=subprocess.Popen(args,cwd=R,env=env,stdout=log,stderr=log,start_new_session=True)
   runtime.update(pid=p.pid,published_utc=now);write(CAT/'server-runtime.json',runtime)
   for _ in range(50):
    try:live=json.load(urllib.request.urlopen('http://127.0.0.1:5224/api/tasks',timeout=3));break
    except OSError:time.sleep(.2)
   else:raise RuntimeError('Catalogue restart failed')
   for c in changed:
    t=next(t for t in live['tasks'] if t['key']==c['task']);score=next(x for x in t['model_results'] if x['model_id']==c['variant'])['report']['score']
    assert abs(score*100-c['score_100'])<1e-7
    with urllib.request.urlopen('http://127.0.0.1:5224'+c['image'],timeout=15) as response:assert response.status==200
   write(output/'latest.json',{'published_utc':now,'protocol':protocol,'archived_previous_protocol':archived,'changed':changed,'backup':str(backup),'preserved_high_results':45,'scheduled_variants':scheduled})
   print(json.dumps({'published':changed,'scheduled_variants':scheduled}),flush=True)
if __name__=='__main__':publish()
