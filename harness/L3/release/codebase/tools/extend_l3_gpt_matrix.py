"""Append GPT-6 Luna/Sol effort configurations while retaining existing trials."""
import copy,fcntl,json,time,tomllib
from pathlib import Path
from tools.l3_leaderboard_batch import B,R,read,write,sha,variant
from harness.L3.Suite.submission_binding import validate_submission

def extend():
 with (B/'manifest.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  manifest=read(B/'manifest.json');original=copy.deepcopy(manifest['rows'])
  catalog=read(R/'data/website_catalog/l3-release-20261023/snapshot.json')
  tasks={r['task_key']:r for r in original};assert len(tasks)==15
  existing={r['id'] for r in original};added=[];checked=[]
  for model in ['gpt-6-luna','gpt-6-sol']:
   for effort in ['medium','high','xhigh','max']:
    for key,template in sorted(tasks.items()):
     rid=key+'--'+variant(model,effort)
     if rid in existing:continue
     reuse=None;result=None;files=None
     if effort=='high':
      task=next(t for t in catalog['tasks'] if t['key']==key)
      result=next(x for x in task['evaluation_results'] if x['model_id']==model)
      assert result['status']=='measured' and not result['missing_axes']
      assert result['model']==model and result['protocol']=='l3-evidence-aligned-v2'
      reuse=Path(result['source']['trial'])
      env=read(reuse/'environment.json');assert env['model']==model and env['reasoning_effort']==effort
      config=tomllib.loads((reuse/'workspace/.codex/config.toml').read_text())
      assert config['model']==model and config['model_reasoning_effort']==effort
      trial=read(reuse/'trial.json');assert trial.get('reasoning_effort',effort)==effort
      files=validate_submission(reuse,key,model,effort if trial.get('reasoning_effort') else None)
      checked.append({'model':model,'task':key,'files':len(files),'trial':str(reuse),'score_100':result['score_100']})
     row={'id':rid,'task_key':key,'task_path':template['task_path'],'task_manifest_sha256':template['task_manifest_sha256'],
       'model':model,'harness':'codex','group':'openai','effort':effort,'variant':variant(model,effort),
       'status':'reused' if reuse else 'queued','reuse_source':str(reuse) if reuse else None,
       'reuse_environment_sha256':sha(reuse/'environment.json') if reuse else None,
       'reuse_prompt_sha256':sha(reuse/'workspace/PROMPT.md') if reuse else None,
       'output':str(B/'runs'/key/variant(model,effort))}
     assert sha(Path(row['task_path'])/'package-manifest.json')==row['task_manifest_sha256']
     if reuse:
      row.update(reuse_submission_manifest_sha256=sha(reuse/'submission-manifest.json'),
        reuse_evaluation_source_sha256=result['source']['source_sha256'],reuse_score_100=result['score_100'],
        reuse_catalog_model_id=model,reuse_codex_config_sha256=sha(reuse/'workspace/.codex/config.toml'))
     added.append(row)
  if not added:return {'added':0,'total':len(original)}
  assert len(added)==120 and len(checked)==30
  backup=B/'manifest-history'/('before-luna-sol-'+str(time.time_ns())+'.json');write(backup,manifest)
  manifest['rows']=original+added
  assert len({r['id'] for r in manifest['rows']})==360
  manifest.update(scope='Core matrix: GPT-6 Astra/Luna/Sol, Opus5.5, GLM5.3Flash, KimiK3, DeepSeekV4.1Flash, Qwen3.8Max; Gemini excluded',
    updated_unix=time.time())
  write(B/'manifest.json',manifest)
  record={'added':120,'new_generation':90,'reused':30,'total':360,'total_new_generation':315,'total_reused':45,'backup':str(backup),'validated_reuse':checked}
  write(B/'matrix-expansion-luna-sol.json',record)
  return record

if __name__=='__main__':
 result=extend()
 print(json.dumps({k:v for k,v in result.items() if k!='validated_reuse'}))
