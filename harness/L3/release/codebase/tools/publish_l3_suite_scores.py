#!/usr/bin/env python3
"""Publish only complete independently measured suite scores to the existing server catalogue."""
import argparse,datetime,hashlib,json,os,pathlib,shutil,signal,subprocess,time,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'data/l3/evaluations/suite-astra-v1'
CAT=ROOT/'data/website_catalog/l3-release-20261023'
def read(p):return json.loads(p.read_text())
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def published_asset(source):
 digest=sha(source);directory=CAT/'evaluation-results';directory.mkdir(exist_ok=True)
 dest=directory/(digest+source.suffix)
 if not dest.exists():
  temp=dest.with_name(dest.name+'.next-'+str(os.getpid()));shutil.copy2(source,temp)
  if sha(temp)!=digest:raise RuntimeError('Source changed while publishing '+str(source))
  os.replace(temp,dest)
 return {'path':str(dest),'sha256':digest}
def publish(partial=False):
 results={p.parent.name:read(p) for p in OUT.glob('*/summary.json') if read(p).get('status')=='measured'}
 if not results or (not partial and len(results)!=14):raise RuntimeError('Complete scores required for all fourteen tasks')
 for v in results.values():
  assert v['score_100'] is not None and not v['missing_axes']
  assert abs(sum(v['weights'].values())-1)<1e-9
 data=read(CAT/'snapshot.json');original=read(CAT/'snapshot.json');downloads=read(CAT/'downloads.json')
 now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 bundle={'schema':'l3-suite-results-v1','model':'gpt-6-astra','evaluated_tasks':len(results),'total_tasks':14,
         'mean_score_100':sum(v['score_100'] for v in results.values())/len(results),
         'tasks':[results[k] for k in sorted(results)],'generated_utc':now}
 write(OUT/'report.json',bundle)
 downloads['l3-astra-suite-results.json']=published_asset(OUT/'report.json')
 data['l3_publication']['report_download']='/downloads/l3-astra-suite-results.json'
 for t in data['tasks']:
  if t['key'] not in results:continue
  result=results[t['key']];folder=OUT/t['key']
  links={}
  for name in ['summary.json',*result['evidence_files']]:
   p=folder/name;key=t['key']+'-astra-evaluation-'+name
   downloads[key]=published_asset(p);links[name]='/downloads/'+key
  t.update(evaluation_results=[{'model_id':'gpt-6-astra',**result,'evidence_links':links}],evaluation_status='measured',
           evaluation_protocol=result['protocol'],score=result['score_100'],formal_score_eligible=True)
  for run in t['generation_runs']:
   if run['model']=='gpt-6-astra':run.update(score=result['score_100'],evaluation_result={'score_100':result['score_100'],'axes':result['axes']})
  for row in t['model_results']:
   if row['model_id']=='gpt-6-astra':row.update(status='scored',kind='l3_suite_evaluated',report={'score':result['score_100']/100,'score_valid':True,'case_pass':True,'axes':result['axes']})
  t['result']=next(row for row in t['model_results'] if row['model_id']=='gpt-6-astra').copy()
  t['profile']=result['protocol'];t['case_policy_sha256']=result['scoring_policy_sha256']
  methods={
   'layout':'全场景支撑连接、封闭实体相交、开放表面交叉、实际行走与 0–4 级布局语义量表。',
   'interaction':'规定对象逐一执行局部操作、远距离及非法动作测试；5 Hz 动作姿态碰撞、实际物品位置、独立库存和连续任务断言。',
   'environment':'固定参考视角及左右 12° 候选视角；按目标框匹配选视角，L2 图像算法计算全图和场景区域外观一致性。',
   'objects':'参考图固定目标清单；VLM 定位候选实例框，算法计算位置、尺寸、结构和材质外观一致性，缺失目标为 0。',
   'rubric':'gpt-6-astra / medium，一次评完整多视图量表；11 项主观指标采用 0–4 级锚点，另评布局语义。'}
  t['evaluation'].update(aggregation='适用板块按固定权重加权；所有分数以 100 分展示。',
   dimensions=[{'name':name,'scope':'仅截图题' if key in ['environment','objects'] else '全部题目','method':methods[key],'evidence':'独立采集的引擎观测、渲染图与逐项报告。'} for key,name in [('layout','布局正确性'),('interaction','交互正确性'),('environment','整体环境一致性'),('objects','关键物体／建筑一致性'),('rubric','需求、美学与风格')]],
   sampling='按规定对象的角色组汇总；场景相机全量进入视觉证据，截图题固定参考目标保留在分母。')
  t['evaluation'].pop('calibration',None);t['evaluation'].pop('optional_rubrics',None)
  rp=t['evaluation']['rubric_policy']
  rp.update(status='已评测',sampling='一次完整多视图判断；11 项主观指标和 1 项布局语义指标，0–4 五级。',
            comparability='采用 L1/L2 的 0–4 五级锚点与 gpt-6-astra / medium 裁判。',
            calibration='',dimensions=[{'name':'主观量表','checks':['构图、光照、完成度、细节','范围、功能区域、室内配置、环境上下文','形体、材质、跨视图风格一致性']}])
  t['evaluation_audit']['as_of_utc']=now
  t['evaluation_audit']['complete_score_available']=True;t['evaluation_audit']['score']=result['score_100']
  for row in t['evaluation_audit']['axes']:
   if row['key'] in result['axes']:row.update(status='已评测',implementation='已实现并运行',requirements=methods[row['key']],score=result['axes'][row['key']]['score'])
 for old,new in zip(original['tasks'],data['tasks']):
  if old['key'] not in results:assert old==new,old['key']
 data['generated_utc']=now
 data['l3_publication'].update(evaluated_count=1+len(results),evaluated_runs=2+len(results),note=f'MC 与 {len(results)} 道新增题已有评测成绩；新增题为 gpt-6-astra，6 Luna 状态见各题。')
 data['counts'].update(l3_scored_tasks=1+len(results),l3_evaluated_tasks=1+len(results),l3_evaluated_runs=2+len(results),l3_pending_evaluation_tasks=14-len(results))
 backup=CAT/'backups'/('suite-scores-'+str(time.time_ns()));backup.mkdir()
 manifest=read(CAT/'manifest.json');manifest.update(generated_utc=now,l3_publication=data['l3_publication'])
 for name,x in [('snapshot.json',data),('downloads.json',downloads)]:
  shutil.copy2(CAT/name,backup/name);write(CAT/(name+'.next'),x);os.replace(CAT/(name+'.next'),CAT/name)
 shutil.copy2(CAT/'manifest.json',backup/'manifest.json')
 manifest['files']={n:sha(CAT/n) for n in ['snapshot.json','assets.json','downloads.json']}
 write(CAT/'manifest.json.next',manifest);os.replace(CAT/'manifest.json.next',CAT/'manifest.json')
 runtime=read(CAT/'server-runtime.json');proc=pathlib.Path('/proc',str(runtime['pid']))
 args=[x.decode() for x in (proc/'cmdline').read_bytes().split(b'\0') if x]
 env=dict(x.decode().split('=',1) for x in (proc/'environ').read_bytes().split(b'\0') if x)
 assert env.get('PORT')=='5224' and str(ROOT/'website/l3-catalog/server.mjs') in args
 os.kill(runtime['pid'],signal.SIGTERM)
 for i in range(50):
  if not proc.exists():break
  time.sleep(.1)
 with (CAT/'server-suite-scores.log').open('ab') as log:
  p=subprocess.Popen(args,cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
 runtime.update(pid=p.pid,published_utc=now);write(CAT/'server-runtime.json',runtime)
 for i in range(50):
  try:live=json.load(urllib.request.urlopen('http://127.0.0.1:5224/api/tasks',timeout=2));break
  except OSError:time.sleep(.2)
 else:raise RuntimeError('Published catalogue failed to start; backup '+str(backup))
 for t in live['tasks']:
  if t['key'] in results:assert t['evaluation_results'][0]['score_100']==results[t['key']]['score_100']
 report={'published_utc':now,'tasks':{k:v['score_100'] for k,v in results.items()},'catalogue':str(CAT),'backup':str(backup)}
 write(OUT/'publication.json',report);print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--partial',action='store_true');a=p.parse_args();publish(a.partial)

