"""Publish an L3 review view without changing frozen submissions or scores."""
import datetime,fcntl,json,os,signal,subprocess,time,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT))
from tools.publish_l3_suite_scores import CAT,read,write,sha,published_asset
from tools.l3_publication_metadata import independent_images

def restart():
    runtime=read(CAT/'server-runtime.json');proc=Path('/proc',str(runtime['pid']))
    args=[x.decode() for x in (proc/'cmdline').read_bytes().split(b'\0') if x]
    env=dict(x.decode().split('=',1) for x in (proc/'environ').read_bytes().split(b'\0') if x)
    assert env.get('PORT')=='5224' and str(ROOT/'website/l3-catalog/server.mjs') in args
    os.kill(runtime['pid'],signal.SIGTERM)
    for _ in range(50):
        if not proc.exists() or ') Z ' in (proc/'stat').read_text():break
        time.sleep(.1)
    with (CAT/'server-review.log').open('ab') as log:
        child=subprocess.Popen(args,cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
    runtime.update(pid=child.pid,published_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    write(CAT/'server-runtime.json',runtime)
    for _ in range(50):
        try:return json.load(urllib.request.urlopen('http://127.0.0.1:5224/api/tasks',timeout=2))
        except OSError:time.sleep(.2)
    raise RuntimeError('Catalogue restart failed')

def prepare():
    out=ROOT/'data/l3/review/20261027';out.mkdir(parents=True,exist_ok=True)
    with (CAT/'publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=read(CAT/'snapshot.json');assets=read(CAT/'assets.json');downloads=read(CAT/'downloads.json')
        preserved=[t for t in data['tasks'] if t.get('level')!=3]
        score_before={t['key']:t.get('evaluation_results',[]) for t in data['tasks'] if t.get('level')==3}
        task_paths={x['key']:ROOT/x['path'] for x in read(ROOT/'tasks/L3/task-index.json')['tasks']}
        task_paths['l3-g01']=ROOT/'tasks/L3/MinecraftVillageOpenWorld'
        summary=[]
        bundle=out/'l3-review-packages.zip'
        with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as full:
            readme='# L3 同事审阅资料\n\n15 题：游戏 6、具身 6、现实 3；10 道截图题、5 道文字题。\n\n每题含英文实际 Prompt、中文题面、公开输入与素材索引、三个模型的逐项成绩。大型素材库通过题包内清单定位。网站提供冻结工程的独立多视图渲染。\n\n建议逐题核对：场景范围与参考图、公开交互与连续任务、模型外观、评分与扣分证据。\n\n评测模型：gpt-6-astra / medium。总分按报告中的适用权重汇总；图像一致性不用于文字题。\n\n此包用于题目和结果审阅，非 Harbor 执行镜像。\n'
            full.writestr('README.md',readme)
            for t in (t for t in data['tasks'] if t.get('level')==3):
                key=t['key'];case=out/key;case.mkdir(exist_ok=True)
                for result in t['evaluation_results']:
                    if result['status']!='measured' or result['score_100'] is None or result['missing_axes']:
                        raise ValueError('Incomplete result '+key)
                    model=result.get('model_id',result['model'])
                    run=next(x for x in t['generation_runs'] if x['model']==model)
                    views=independent_images(key,result,assets)
                    if 'submitted_images' not in run:run['submitted_images']=run.get('images',[])
                    run['images']=views;run['image_source']='independent_verifier'
                    row=next(x for x in t['model_results'] if x['model_id']==model)
                    row['model_images']=[{**v,'kind':'model_main' if i==0 else 'model_alternate'} for i,v in enumerate(views)]
                    row['reasoning_effort']=run.get('effort','high')
                    if t.get('result',{}).get('model_id')==model:t['result']=dict(row)
                    # English and Chinese review input is separate from evaluator-only evidence.
                    write(case/(model+'-scores.json'),result)
                package=out/(key+'-review.zip');source=task_paths[key]
                with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
                    for name in ['instruction.md','instruction.zh.md','PROMPT.md']:
                        p=source/name
                        if p.exists():z.write(p,key+'/'+name)
                    for p in sorted((source/'environment/input').rglob('*')):
                        if p.is_file():z.write(p,key+'/environment/input/'+str(p.relative_to(source/'environment/input')))
                    for p in sorted(case.glob('*-scores.json')):z.write(p,key+'/scores/'+p.name)
                    z.writestr(key+'/README.md','# '+t['title']+'\n\n实际模型输入：PROMPT.md。中文对照：instruction.zh.md。公开资源：environment/input/。模型成绩：scores/。\n')
                with zipfile.ZipFile(package) as z:
                    for name in z.namelist():full.writestr(name,z.read(name))
                download=key+'-review.zip';downloads[download]=published_asset(package)
                t['review_package']={'zip':'/downloads/'+download,'purpose':'task_and_result_review'}
                summary.append({'key':key,'title':t['title'],'mode':t['input_mode'],'package':t['review_package']['zip'],
                    'models':[{'model':r['model'],'views':len(r['images']),'score':r['score'],'image_source':r['image_source']} for r in t['generation_runs']]})
            full.writestr('review-index.json',json.dumps(summary,ensure_ascii=False,indent=2))
        write(out/'review-index.json',{'tasks':summary,'task_count':len(summary),'result_count':sum(len(t['models']) for t in summary)})
        downloads['l3-review-packages.zip']=published_asset(bundle)
        downloads['l3-review-index.json']=published_asset(out/'review-index.json')
        assert len(summary)==15 and all(len(t['models'])==3 and all(r['views'] for r in t['models']) for t in summary)
        assert preserved==[t for t in data['tasks'] if t.get('level')!=3]
        assert score_before=={t['key']:t.get('evaluation_results',[]) for t in data['tasks'] if t.get('level')==3}
        backup=CAT/'backups'/('review-'+str(time.time_ns()));backup.mkdir()
        for name,obj in [('snapshot.json',data),('assets.json',assets),('downloads.json',downloads)]:
            (backup/name).write_bytes((CAT/name).read_bytes());write(CAT/(name+'.next'),obj);os.replace(CAT/(name+'.next'),CAT/name)
        manifest=read(CAT/'manifest.json');(backup/'manifest.json').write_bytes((CAT/'manifest.json').read_bytes())
        manifest['files']={n:sha(CAT/n) for n in ['snapshot.json','assets.json','downloads.json']}
        write(CAT/'manifest.json.next',manifest);os.replace(CAT/'manifest.json.next',CAT/'manifest.json')
        live=restart()
        l3=[t for t in live['tasks'] if t['level']==3]
        assert len(l3)==15 and all(len(t['evaluation_results'])==3 for t in l3)
        assert all(r['images'] for t in l3 for r in t['generation_runs'])
        write(out/'publication.json',{'status':'verified','tasks':15,'results':45,'unchanged_scores':True,'other_levels_preserved':True,
            'images':sum(len(r['images']) for t in l3 for r in t['generation_runs']),'backup':str(backup),
            'package_sha256':sha(bundle)})
        print(json.dumps(read(out/'publication.json')),flush=True)
if __name__=='__main__':prepare()
