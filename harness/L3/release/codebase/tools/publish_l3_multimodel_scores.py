"""Merge completed model scores into the server catalogue without replacing other models."""
import argparse,copy,datetime,fcntl,json,os,signal,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT))
from tools.publish_l3_suite_scores import CAT,read,write,sha,published_asset
def merge_result(task,result,links):
    model=result['model']
    task['evaluation_results']=[x for x in task.get('evaluation_results',[]) if x.get('model_id',x.get('model'))!=model]+[{'model_id':model,**result,'evidence_links':links}]
    rows=task.setdefault('model_results',[])
    row=next((x for x in rows if x['model_id']==model),None)
    if row is None:
        row={'model_id':model,'label':model,'scheduled':True,'usage':{}};rows.append(row)
    row.update(status='scored',kind='l3_suite_evaluated',report={'score':result['score_100']/100,'score_valid':True,'case_pass':True,'axes':result['axes']})
    runs=task.setdefault('generation_runs',[])
    run=next((x for x in runs if x['model']==model),None)
    if run is None:
        legacy=next((x for x in task.get('generation_results',[]) if x.get('model')==model),{})
        run={**copy.deepcopy(legacy),'model':model,'effort':'high','images':copy.deepcopy(legacy.get('images',[]))};runs.append(run)
    run.update(status='completed',status_label='已生成',completed=True,score=result['score_100'],
        evaluation_result={'score_100':result['score_100'],'axes':result['axes']},trial_path=result['source']['trial'])
    current_models=['gpt-6-astra','gpt-6-luna','gpt-6-sol']
    legacy=[x for x in task['evaluation_results'] if x.get('model_id',x.get('model')) not in current_models]
    if legacy:
        saved=task.setdefault('archived_evaluation_results',[])
        for item in legacy:
            if item not in saved:saved.append(item)
    task['evaluation_results']=[x for x in task['evaluation_results'] if x.get('model_id',x.get('model')) in current_models]
    task['evaluation_results'].sort(key=lambda x:current_models.index(x.get('model_id',x.get('model'))))
    task['generation_runs'].sort(key=lambda x:current_models.index(x['model']) if x['model'] in current_models else len(current_models))
    task['evaluation_status']='measured'
    task['formal_score_eligible']=True
    if task.get('key')=='l3-g01':
        task['reference_score_status']='measured'
        task['reference_status']='reference_scored'
        task['oracle_status']='independent_measurements_available'
        evaluation=task.setdefault('evaluation',{})
        evaluation['aggregation']='适用板块按固定权重加权；所有分数以 100 分展示。'
        evaluation.pop('calibration',None)
        rubric=evaluation.setdefault('rubric_policy',{})
        rubric.update(status='已评测',sampling='一次完整多视图判断；11 项主观指标和布局语义，0–4 五级。')
        rubric.pop('calibration',None)
    task['evaluation_protocol']=result.get('protocol',task.get('evaluation_protocol'))
    task['status']='evaluated'
    if task.get('result',{}).get('model_id')==model or (not task.get('result',{}).get('model_id') and model=='gpt-6-astra'):task['result']=copy.deepcopy(row);task['score']=result['score_100']
def publish(model):
    slug=model.removeprefix('gpt-6-');out=ROOT/'data/l3/evaluations'/('suite-'+slug+'-v1')
    results={p.parent.name:read(p) for p in out.glob('*/summary.json') if read(p).get('status')=='measured'}
    if not results:return
    with (CAT/'publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=read(CAT/'snapshot.json');downloads=read(CAT/'downloads.json');manifest=read(CAT/'manifest.json');assets=read(CAT/'assets.json')
        if not any(x['id']==model for x in data['models']):
            data['models'].append({'id':model,'label':'6 '+slug.title()})
        now=datetime.datetime.now(datetime.timezone.utc).isoformat()
        for key,result in results.items():
            if result['model']!=model or result['score_100'] is None or result['missing_axes']:raise ValueError('Incomplete or mismatched score')
            task=next(t for t in data['tasks'] if t['key']==key);folder=out/key;links={}
            for name in ['summary.json',*result['evidence_files']]:
                assetkey=key+'-'+slug+'-evaluation-'+name.replace('/','-')
                downloads[assetkey]=published_asset(folder/name);links[name]='/downloads/'+assetkey
            merge_result(task,result,links)
            from tools.l3_publication_metadata import populate_generation
            populate_generation(task,result,assets,downloads)
            task['generation_as_of_utc']=now
        report={'model':model,'evaluated_tasks':len(results),'total_tasks':15,'mean_score_100':sum(x['score_100'] for x in results.values())/len(results),
                'tasks':[results[k] for k in sorted(results)],'generated_utc':now}
        write(out/'report.json',report)
        downloads['l3-'+slug+'-suite-results.json']=published_asset(out/'report.json')
        data.setdefault('l3_publication',{}).setdefault('model_reports',{})[model]='/downloads/l3-'+slug+'-suite-results.json'
        l3=[t for t in data['tasks'] if t['key'].startswith('l3-')]
        count=sum(sum(x.get('report',{}).get('score') is not None for x in t.get('model_results',[])) for t in l3)
        scored=sum(any(x.get('report',{}).get('score') is not None for x in t.get('model_results',[])) for t in l3)
        data['l3_publication'].update(evaluated_runs=count,evaluated_count=scored,note='按模型展示已完成评测的逐项分数与报告。')
        data['counts'].update(l3_evaluated_runs=count,l3_scored_tasks=scored,l3_evaluated_tasks=scored,l3_pending_evaluation_tasks=len(l3)-scored)
        generated=sum(sum(r.get('completed',False) for r in t.get('generation_runs',[]) if r.get('model') in {'gpt-6-astra','gpt-6-luna','gpt-6-sol'}) for t in l3)
        data['counts'].update(l3_generated_runs=generated,l3_generated_tasks=len(l3))
        data['l3_publication'].update(generation_runs=generated,generation_tasks=len(l3))
        from tools.l3_publication_metadata import score_csv
        previous_csv=Path(downloads['catalog_scores.csv']['path'])
        if sha(previous_csv)!=downloads['catalog_scores.csv']['sha256']:raise ValueError('Score CSV provenance mismatch')
        csv_path=out/'catalog_scores.csv'
        csv_path.write_text(score_csv(previous_csv.read_text(),data['tasks']))
        downloads['catalog_scores.csv']=published_asset(csv_path)
        data['generated_utc']=now
        backup=CAT/'backups'/('model-scores-'+slug+'-'+str(time.time_ns()));backup.mkdir()
        for name,value in [('snapshot.json',data),('downloads.json',downloads),('assets.json',assets)]:
            (backup/name).write_bytes((CAT/name).read_bytes());write(CAT/(name+'.next'),value);os.replace(CAT/(name+'.next'),CAT/name)
        (backup/'manifest.json').write_bytes((CAT/'manifest.json').read_bytes())
        manifest.update(generated_utc=now,l3_publication=data['l3_publication'])
        manifest['files']={n:sha(CAT/n) for n in ['snapshot.json','assets.json','downloads.json']}
        write(CAT/'manifest.json.next',manifest);os.replace(CAT/'manifest.json.next',CAT/'manifest.json')
        runtime=read(CAT/'server-runtime.json');proc=Path('/proc',str(runtime['pid']))
        args=[x.decode() for x in (proc/'cmdline').read_bytes().split(b'\0') if x]
        env=dict(x.decode().split('=',1) for x in (proc/'environ').read_bytes().split(b'\0') if x)
        assert env.get('PORT')=='5224' and str(ROOT/'website/l3-catalog/server.mjs') in args
        os.kill(runtime['pid'],signal.SIGTERM)
        for _ in range(50):
            if not proc.exists() or ') Z ' in (proc/'stat').read_text():break
            time.sleep(.1)
        with (CAT/'server-multimodel-scores.log').open('ab') as log:
            child=subprocess.Popen(args,cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
        runtime.update(pid=child.pid,published_utc=now);write(CAT/'server-runtime.json',runtime)
        for _ in range(50):
            try:live=json.load(urllib.request.urlopen('http://127.0.0.1:5224/api/tasks',timeout=2));break
            except OSError:time.sleep(.2)
        else:raise RuntimeError('Catalogue restart failed')
        for task in live['tasks']:
            if task['key'] in results:
                row=next(x for x in task['model_results'] if x['model_id']==model)
                assert abs(row['report']['score']*100-results[task['key']]['score_100'])<1e-8
        write(out/'publication.json',{'model':model,'published_utc':now,'count':len(results),'backup':str(backup)})
        print(json.dumps({'model':model,'published':len(results)}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model',required=True,choices=['gpt-6-astra','gpt-6-luna','gpt-6-sol']);a=p.parse_args();publish(a.model)
