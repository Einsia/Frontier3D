"""Validate and publish one complete, source-bound 45-result evaluation batch."""
import copy,datetime,fcntl,json,os,signal,subprocess,time,urllib.request
from pathlib import Path
from tools.publish_l3_multimodel_scores import merge_result
from tools.publish_l3_suite_scores import CAT,read,write,sha,published_asset,ROOT
from tools.l3_publication_metadata import score_csv
from harness.L3.Suite.reference_review import OUT

def publish():
    snapshot=read(OUT/'input-catalogue.json');results={}
    for task in snapshot['tasks']:
        if task.get('level')!=3:continue
        for run in task['generation_runs']:
            key,model=task['key'],run['model'];folder=OUT/key/model
            result=read(folder/'summary.json')
            assert result['status']=='measured' and not result['missing_axes'] and result['protocol']=='l3-evidence-aligned-v2'
            assert result['model']==model and 0<=result['score_100']<=100
            assert abs(sum(result['weights'].values())-1)<1e-9
            assert abs(sum(result['axes'][a]['score']*w*100 for a,w in result['weights'].items())-result['score_100'])<1e-8
            assert result['source']['source_sha256']==run['images'][0]['submission_sha256']
            assert result['implementation_sha256']['aggregate_v2.py']==sha(ROOT/'harness/L3/Suite/aggregate_v2.py')
            assert result['evidence_sha256']=={name:sha(folder/name) for name in result['evidence_files']}
            if task['input_mode']=='image':assert result['axes']['objects']['method']=='l3-reference-core-features-v3'
            results[key,model]=result
    assert len(results)==45
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    with (CAT/'publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=read(CAT/'snapshot.json');downloads=read(CAT/'downloads.json');assets=read(CAT/'assets.json');manifest=read(CAT/'manifest.json')
        untouched=[copy.deepcopy(t) for t in data['tasks'] if t.get('level')!=3]
        for (key,model),result in results.items():
            task=next(t for t in data['tasks'] if t['key']==key);slug=model.removeprefix('gpt-6-');folder=OUT/key/model;links={}
            live=next(r for r in task['generation_runs'] if r['model']==model)
            assert live['images'][0]['submission_sha256']==result['source']['source_sha256']
            for name in ['summary.json',*result['evidence_files']]:
                assetkey=key+'-'+slug+'-evaluation-'+name.replace('/','-')
                downloads[assetkey]=published_asset(folder/name);links[name]='/downloads/'+assetkey
            merge_result(task,result,links)
            row=next(x for x in task['model_results'] if x['model_id']==model)
            row['report']['case_pass']=bool(result['playability']['continuous_workflow']) if result.get('playability') else None
            if task.get('result',{}).get('model_id')==model:task['result']=copy.deepcopy(row)
            task['evaluation_method']='独立运行时几何与交互检查；匿名多视图参考特征和 0–4 级主观量表。'
        for model in ['gpt-6-astra','gpt-6-luna','gpt-6-sol']:
            rows=[r for (k,m),r in sorted(results.items()) if m==model]
            report={'model':model,'evaluated_tasks':15,'total_tasks':15,'mean_score_100':sum(r['score_100'] for r in rows)/15,'tasks':rows,'generated_utc':now}
            path=OUT/(model+'-report.json');write(path,report)
            name='l3-'+model.removeprefix('gpt-6-')+'-suite-results.json';downloads[name]=published_asset(path)
            data['l3_publication']['model_reports'][model]='/downloads/'+name
        protocol={'title':'L3 评测方法','protocol':'l3-evidence-aligned-v2','tasks':15,'results':45,
          'judge':{'model':'gpt-6-astra','effort':'medium','scale':[0,1,2,3,4],'identity':'候选评审输入不包含生成模型名称、已有分数或目标排序'},
          'weights':{mode:next(r['weights'] for r in results.values() if r.get('mode')==mode) for mode in ['image','text']},
          'layout':'渲染资产到地面的接触链；相交体积占资产体积的比例，按表面积汇总；实际角色行走；布局语义量表。',
          'interaction':'规定对象的局部操作、非法操作约束、实测运动碰撞、物品几何与独立库存终态、连续流程。合法注册对象的扩展动作可执行，成功由独立物理条件判定。',
          'reference':'仅根据题面和参考图建立跨视图去重的语义目标；按主结构、配景和细部确定权重；逐特征评审候选全部视图。功能条件、不可见要求及不属于该对象组的证据不计入截图一致性。',
          'rubric':'需求吻合度、美学、风格一致性，按有锚点的 0–4 级量表评分。',
          'scope':['支撑以渲染网格资产为单位，不是承重或应力分析。','运动碰撞检查独立记录的离散姿态，不证明帧间连续轨迹。','视觉一致性使用匿名 VLM 特征判断；像素匹配作为诊断，不能等同语义一致性。'],
          'aggregation':'按公开适用权重加权为百分制；所有模型使用同一题目清单与评分规则。','source_root':str(OUT)}
        write(OUT/'evaluation-method.json',protocol);downloads['l3-evaluation-method.json']=published_asset(OUT/'evaluation-method.json')
        assert untouched==[t for t in data['tasks'] if t.get('level')!=3]
        previous=Path(downloads['catalog_scores.csv']['path']);assert sha(previous)==downloads['catalog_scores.csv']['sha256']
        csv=OUT/'catalog_scores.csv';csv.write_text(score_csv(previous.read_text(),data['tasks']));downloads['catalog_scores.csv']=published_asset(csv)
        data['generated_utc']=now;data['l3_publication'].update(evaluated_runs=45,evaluated_count=15,evaluation_protocol='l3-evidence-aligned-v2')
        backup=CAT/'backups'/('evidence-scores-'+str(time.time_ns()));backup.mkdir()
        for name,value in [('snapshot.json',data),('downloads.json',downloads),('assets.json',assets)]:
            (backup/name).write_bytes((CAT/name).read_bytes());write(CAT/(name+'.next'),value);os.replace(CAT/(name+'.next'),CAT/name)
        (backup/'manifest.json').write_bytes((CAT/'manifest.json').read_bytes())
        manifest.update(generated_utc=now,l3_publication=data['l3_publication']);manifest['files']={n:sha(CAT/n) for n in ['snapshot.json','assets.json','downloads.json']}
        write(CAT/'manifest.json.next',manifest);os.replace(CAT/'manifest.json.next',CAT/'manifest.json')
        runtime=read(CAT/'server-runtime.json');proc=Path('/proc',str(runtime['pid']))
        args=[x.decode() for x in (proc/'cmdline').read_bytes().split(b'\0') if x]
        env=dict(x.decode().split('=',1) for x in (proc/'environ').read_bytes().split(b'\0') if x)
        assert env.get('PORT')=='5224' and str(ROOT/'website/l3-catalog/server.mjs') in args
        os.kill(runtime['pid'],signal.SIGTERM)
        for _ in range(50):
            if not proc.exists() or ') Z ' in (proc/'stat').read_text():break
            time.sleep(.1)
        with (CAT/'server-evidence-scores.log').open('ab') as log:child=subprocess.Popen(args,cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
        runtime.update(pid=child.pid,published_utc=now);write(CAT/'server-runtime.json',runtime)
        for _ in range(50):
            try:live=json.load(urllib.request.urlopen('http://127.0.0.1:5224/api/tasks',timeout=2));break
            except OSError:time.sleep(.2)
        else:raise RuntimeError('Catalogue restart failed')
        for task in live['tasks']:
            if task.get('level')!=3:continue
            for row in task['model_results']:
                if (task['key'],row['model_id']) in results:assert abs(row['report']['score']*100-results[task['key'],row['model_id']]['score_100'])<1e-8
        write(OUT/'publication.json',{'published_utc':now,'count':45,'backup':str(backup)})
        print('Published and verified 45 results')
if __name__=='__main__':publish()
