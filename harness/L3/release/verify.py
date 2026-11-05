"""Host verifier for provisioned Harbor UE trials. No cached score import."""
import argparse,hashlib,json,os,shutil,subprocess,sys,math
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE/'codebase'
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
def validate_collected(runtime,trial):
 from harness.L3.MinecraftVillage.protocol import tree_digest
 source=json.loads((runtime/'source.json').read_text());record=json.loads((runtime/'run.json').read_text())
 if (record.get('status')!='collected' or source.get('trial')!=str(trial)
     or source.get('manifest_sha256')!=hashlib.sha256((trial/'submission-manifest.json').read_bytes()).hexdigest()
     or source.get('source_sha256')!=tree_digest(trial/'workspace/project')):
  raise ValueError('Collected source identity changed; use a fresh verifier output')
 if 'verification_record' in record:
  native=runtime/'verification/run.json';measurement=json.loads(native.read_text())
  if measurement.get('status') not in {'collected','measured'}:raise ValueError('Minecraft collection incomplete')
  evidence={runtime/'verification'/n:sha for n,sha in measurement.get('evidence_sha256',{}).items()}
  evidence[runtime/'algorithms/runtime-geometry-v2/run.json']=record['runtime_record_sha256']
 else:
  if tree_digest(runtime/'workspace/project')!=source.get('verification_source_sha256'):
   raise ValueError('Verifier project changed')
  evidence={runtime/n:sha for n,sha in record.get('evidence_sha256',{}).items()}
 if not evidence:raise ValueError('Collected evidence inventory missing')
 for path,sha in evidence.items():
  if not path.resolve().is_relative_to(runtime.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
   raise ValueError('Collected evidence changed: '+str(path))
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--task',required=True);p.add_argument('--trial',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True);p.add_argument('--engine',type=Path,required=True)
 p.add_argument('--gpu',type=int,default=0);p.add_argument('--model',required=True);p.add_argument('--effort',required=True)
 p.add_argument('--provider',type=Path,required=True);p.add_argument('--reward',type=Path,default=Path('/logs/verifier/reward.txt'))
 p.add_argument('--resume',action='store_true',help='Reuse hash-verified completed collection while retrying scoring')
 a=p.parse_args();trial=a.trial.resolve();out=a.output.resolve()
 from check_resources import verify_resources
 verify_resources()
 if out.exists() and not a.resume:raise ValueError('Verifier output must be fresh, or explicitly use --resume')
 if a.resume and not (out/'row.json').is_file():raise ValueError('No bound collected trial to resume')
 if a.reward.exists():raise ValueError('Reward already exists')
 if not (trial/'submission-manifest.json').is_file():raise ValueError('Native preparation/generation must freeze this trial first')
 if not a.provider.is_file():raise ValueError('Host judge provider required')
 if not (a.engine/'Engine/Binaries/Linux/UnrealEditor-Cmd').is_file():raise ValueError('Dedicated licensed UE engine required')
 sys.path.insert(0,str(ROOT))
 os.environ.update(L3_EVAL_MODEL=a.model,L3_EVAL_EFFORT=a.effort,L3_EVAL_TRIAL=str(trial))
 from harness.L3.Suite.submission_binding import validate_submission
 task_path=next(p.parent for p in (ROOT/'tasks/L3').glob('*/task.json')
                if json.loads(p.read_text()).get('key')==a.task
                and json.loads(p.read_text()).get('execution_status')=='generation_ready')
 validate_submission(trial,a.task,a.model,a.effort)
 out.mkdir(parents=True,exist_ok=a.resume);batch=out/'batch'
 specs=batch/'evaluations/quality-v5-specs'
 if a.resume:
  for original in (HERE/'scoring-specs').rglob('*'):
   if original.is_file() and (specs/original.relative_to(HERE/'scoring-specs')).read_bytes()!=original.read_bytes():
    raise ValueError('Frozen scoring specs changed')
 else:
  shutil.copytree(HERE/'scoring-specs',specs)
  write(batch/'settings.json',{'scoring_protocol':'l3-perceptual-quality-v5','api_concurrency':{'openai':4}})
 runtime=out/'runtime';review=out/'review-v5'
 env={**os.environ,'L3_EXPERIMENT_BATCH':str(batch),'L3_EVAL_OUT':str(runtime),'L3_REVIEW_OUT':str(review),
      'L3_MATRIX_JUDGE_PROVIDER':str(a.provider.resolve()),'L3_MODEL_GROUP':'openai'}
 (ROOT/'data/l3/locks').mkdir(parents=True,exist_ok=True)
 frozen=json.loads((trial/'submission-manifest.json').read_text())
 row={'id':a.task+'--'+a.model+'--'+a.effort,'task_key':a.task,'variant':a.model+'--'+a.effort,
      'model':a.model,'effort':a.effort,'harness':frozen.get('harness','harbor'),'evaluation_harness':'harbor-host-verifier','output':str(trial),'task_path':str(task_path)}
 if a.resume:
  if json.loads((out/'row.json').read_text())!=row:raise ValueError('Verifier trial identity changed')
  validate_collected(runtime/a.task,trial)
 else:
  with (out/'collection.log').open('w') as log:
   subprocess.run([sys.executable,str(ROOT/'tools/evaluate_l3_submission.py'),'--collect-only','--key',a.task,
     '--engine',str(a.engine.resolve()),'--gpu',str(a.gpu)],cwd=ROOT,env=env,stdout=log,stderr=log,check=True)
  write(out/'row.json',row)
 with (out/'scoring.log').open('a' if a.resume else 'w') as log:
  subprocess.run([sys.executable,str(HERE/'score_one.py'),str(out/'row.json')],cwd=ROOT,env=env,stdout=log,stderr=log,check=True)
 report=review/a.task/a.model/'summary.json';r=json.loads(report.read_text())
 if r.get('protocol')!='l3-perceptual-quality-v5' or r.get('status')!='measured' or r.get('missing_axes'):raise ValueError('Scoring incomplete')
 score=r['score_100']
 if not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=100:raise ValueError('Invalid score')
 validate_submission(trial,a.task,a.model,a.effort)
 a.reward.parent.mkdir(parents=True,exist_ok=True);a.reward.write_text(str(score/100)+'\n')
 write(out/'verifier-result.json',{'task':a.task,'score_100':score,'report':str(report),'report_sha256':hashlib.sha256(report.read_bytes()).hexdigest(),'status':'measured'})
if __name__=='__main__':main()
