#!/usr/bin/env python3
"""Publish completed L3 suite renders and measured run metadata; never synthesize scores."""
import argparse, copy, datetime, hashlib, json, os, pathlib, shutil
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
BATCH = ROOT / 'data/l3/suite-20261023'
LABELS = {'layout':'布局正确性','interaction':'交互正确性','environment':'整体环境一致性','objects':'关键物体／建筑一致性','rubric':'需求、美学与风格'}
MISSING = {
 'layout':'需逐题配置静态穿透、支撑、可达性与运动扫掠检查；MC 几何库可复用。',
 'interaction':'已有公开交互契约；缺独立状态断言、空间观测与连续任务测试。',
 'environment':'缺参考视图标定与独立采样配置；需对齐视角后计算一致性。',
 'objects':'缺关键物体标注、定位和多角度匹配配置。',
 'rubric':'缺逐题 VLM 量表与证据清单；裁判沿用 gpt-6-astra / medium。'
}
def read(p): return json.loads(p.read_text())
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def alive(worker):
 try:
  cmd=pathlib.Path('/proc',str(worker['pid']),'cmdline').read_bytes().decode().replace('\x00',' ')
  return 'l3' in cmd and ('preflight' in cmd or 'trial' in cmd)
 except (OSError,KeyError): return False

def publish(catalog,out):
 out.mkdir(parents=True,exist_ok=True)
 snapshot=read(catalog/'snapshot.json'); original=copy.deepcopy(snapshot)
 assets=read(catalog/'assets.json'); downloads=read(catalog/'downloads.json')
 checkpoint=read(BATCH/'batch-control/queue-checkpoint.json')
 workers={w['run_id']:w for w in checkpoint.get('active_workers',{}).values()}
 now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 audit={'as_of_utc':now,'batch_path':str(BATCH),'tasks':[],'complete_score_available':False,
        'reusable_evaluator':'harness/L3/MinecraftVillage','judge_model':'gpt-6-astra','judge_effort':'medium'}
 changed=[];images_total=0
 for t in snapshot['tasks']:
  trial_dir=BATCH/t['key']/'astra'
  if not (trial_dir/'submission-manifest.json').exists():continue
  tr=read(trial_dir/'trial.json');manifest=read(trial_dir/'submission-manifest.json')
  assert tr.get('model')=='gpt-6-astra' and tr.get('completion_evidence',{}).get('delivery_complete'), t['key']
  workspace=trial_dir/'workspace';project=workspace/'project'
  evidence_hashes={digest(workspace/f) for f in tr['completion_evidence']['scene_previews']}
  previews=[(k,h) for k,h in manifest.items() if k.split('/')[0].lower()=='previews' and pathlib.Path(k).suffix.lower() in ('.png','.jpg','.jpeg') and h in evidence_hashes]
  previews.sort(key=lambda x:(pathlib.Path(x[0]).stem!='overview',pathlib.Path(x[0]).stem!='interior',x[0]))
  imgs=[]
  for name,h in previews:
   p=project/name
   assert digest(p)==h, str(p)
   # Restrict display to submitted images also present in the runner's scene capture evidence.
   dst=out/'generation-assets'/t['key']/pathlib.Path(name).name
   dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
   with Image.open(dst) as im: width,height=im.size
   key=t['key']+'-astra-'+h[:20]
   assets[key]={'path':str(dst),'sha256':h}
   imgs.append({'url':'/media/'+key,'label':pathlib.Path(name).stem.replace('_',' '),'width':width,'height':height,
                'source':str(p),'source_sha256':h,'kind':'generated','capture_mtime':p.stat().st_mtime})
  assert imgs, t['key']
  usage=read(trial_dir/'generation-usage.json')
  for filename in ('generation-usage.json','submission-manifest.json'):
   dst=out/'generation-metadata'/t['key']/filename;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(trial_dir/filename,dst)
   downloads[t['key']+'-astra-'+filename]={'path':str(dst),'sha256':digest(dst)}
  luna_dir=BATCH/t['key']/'luna';lt=read(luna_dir/'trial.json') if (luna_dir/'trial.json').exists() else {}
  w=workers.get(t['key']+'-luna',{});live=alive(w)
  luna_status='连接重试中' if live and lt.get('status')=='retrying_model_connection' else ('运行中' if live else '排队中')
  runs=[{'model':'gpt-6-astra','effort':'high','status':'completed','status_label':'已生成','completed':True,
         'seconds':tr.get('elapsed_seconds'),'finished_unix':tr.get('finished_unix'),'usage':usage,'images':imgs,
         'trial_path':str(trial_dir),'score':None,'usage_url':'/downloads/'+t['key']+'-astra-generation-usage.json',
         'manifest_url':'/downloads/'+t['key']+'-astra-submission-manifest.json'},
        {'model':'gpt-6-luna','effort':'high','status':lt.get('status','queued') if live else 'queued','status_label':luna_status,
         'completed':False,'seconds':None,'usage':{},'images':[],'trial_path':str(luna_dir),'score':None}]
  axes=[]
  for key in LABELS:
   applicable=t['input_mode']=='image' or key not in ('environment','objects')
   axes.append({'key':key,'name':LABELS[key],'weight':t['weights'].get(key,0) if applicable else None,'score':None,
                'status':'待评测' if applicable else '不适用','implementation':'待接入逐题评测' if applicable else '不适用',
                'requirements':MISSING[key] if applicable else '文字生成题无参考图，不计参考一致性分。'})
  readiness={'task_key':t['key'],'title':t['title'],'input_mode':t['input_mode'],'complete_score_available':False,
             'score':None,'axes':axes,'as_of_utc':now}
  t.update(generation_runs=runs,generation_status='astra_completed_luna_pending',generation_as_of_utc=now,
           evaluation_audit=readiness,evaluation_status='pending',score=None,
           execution_status='astra_completed_luna_pending',status='generation_ready')
  t['evaluation']['aggregation']='已生成，待评测，暂无成绩。公开交互契约和生成自检不能代替独立评测。'
  t['model_results']=[{'model_id':r['model'],'label':r['model'],'status':'generated' if r['completed'] else 'running' if live else 'queued',
                       'scheduled':True,'report':{'score':None,'score_valid':None},'usage':r['usage']} for r in runs]
  t['result']={**t['model_results'][0],'kind':'l3_design'}
  audit['tasks'].append(readiness);changed.append(t['key']);images_total+=len(imgs)
 assert len(changed)==14,len(changed)
 for old,new in zip(original['tasks'],snapshot['tasks']):
  if old['key'] not in changed: assert old==new,old['key']
 if not any(m['id']=='gpt-6-luna' for m in snapshot['models']):
  snapshot['models'].append({'id':'gpt-6-luna','label':'6 Luna'})
 snapshot['generated_utc']=now
 snapshot['l3_publication'].update(generation_tasks=15,generation_runs=16,note='14 道新增题的 Astra 生成结果已发布；6 Luna 排队或连接重试中。MC 已有两份评测结果，其余 14 题待评测，暂无成绩。',publication_utc=now)
 snapshot['counts']['results']=sum(len(t['model_results']) for t in snapshot['tasks'])
 snapshot['counts'].update(l3_generated_tasks=15,l3_generated_runs=16,l3_pending_evaluation_tasks=14)
 audit.update(generated_runs=14,published_images=images_total,task_count=14)
 write(out/'evaluation-readiness.json',audit)
 downloads['l3-suite-evaluation-readiness.json']={'path':str(out/'evaluation-readiness.json'),'sha256':digest(out/'evaluation-readiness.json')}
 for name,value in [('snapshot.json',snapshot),('assets.json',assets),('downloads.json',downloads)]:write(out/name,value)
 manifest=read(catalog/'manifest.json');manifest.update(generated_utc=now,l3_publication=snapshot['l3_publication'])
 manifest['files']={n:digest(out/n) for n in ('snapshot.json','assets.json','downloads.json')}
 write(out/'manifest.json',manifest)
 write(out/'publication-check.json',{'as_of_utc':now,'tasks':changed,'published_images':images_total,'unchanged_other_tasks':len(snapshot['tasks'])-14,'scores_published':0})
 print(json.dumps({'tasks':len(changed),'images':images_total,'output':str(out),'scores':0}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--catalog',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True)
 a=p.parse_args();publish(a.catalog,a.output)

