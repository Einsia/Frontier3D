"""Minecraft-specific collection and measurement behind the common matrix ledger."""
import os,subprocess,sys,time
from pathlib import Path
R=Path(__file__).resolve().parents[1]
from tools.l3_leaderboard_batch import read,write
from harness.L3.MinecraftVillage.protocol import digest,tree_digest

def execute(label,args,folder):
 with (folder/(label+'.log')).open('a') as log:
  p=subprocess.run([sys.executable,*args],cwd=R,stdout=log,stderr=log)
 if p.returncode:raise RuntimeError(label+' failed; see '+str(folder/(label+'.log')))

def collect_runtime(trial,folder):
 """Run every UE replay before releasing the exclusively held evaluator engine."""
 run=folder/'verification';out=folder/'algorithms';out.mkdir(exist_ok=True)
 if read(run/'run.json')['status'] not in {'collected','measured'}:raise ValueError('MC base collection incomplete')
 if not (out/'geometry/geometry.json').exists():
  if (out/'geometry').exists():(out/'geometry').rename(out/('geometry-failed-'+str(time.time_ns())))
  execute('geometry',['-m','harness.L3.MinecraftVillage.algorithm_geometry','--run',str(run),'--trial',str(trial),'--output',str(out/'geometry')],folder)
 capture=out/'capture'
 captured=read(capture/'capture.json',{})
 if captured.get('status')!='measured' or any(x.get('status')!='measured' for x in captured.get('episodes',{}).values()):
  stamp=str(time.time_ns());archived=[]
  for partial in [capture,run/'workspace/algorithm-v1']:
   destination=partial.with_name(partial.name+'-failed-'+stamp)
   if partial.exists():partial.rename(destination)
   archived.append(destination)
  retry_args=['--retry-capture',str(archived[0]),'--retry-episodes',str(archived[1])] if all(p.exists() for p in archived) and (archived[0]/'capture.json').exists() else []
  execute('capture',[str(R/'tools/capture_l3_algorithms.py'),'--run',str(run),'--trial',str(trial),'--output',str(out/'capture')]+retry_args,folder)
 captured=read(capture/'capture.json',{})
 if captured.get('status')!='measured' or any(x.get('status')!='measured' for x in captured.get('episodes',{}).values()):
  raise RuntimeError('MC supplemental capture incomplete; retain evidence and retry')
 runtime=out/'runtime-geometry-v2'
 if read(runtime/'run.json',{}).get('status')!='measured':
  resume=(runtime/'run.json').exists()
  if not resume:
   stamp=str(time.time_ns())
   for partial in [runtime,run/'workspace/runtime-geometry-v2']:
    if partial.exists():partial.rename(partial.with_name(partial.name+'-failed-'+stamp))
  execute('runtime',[str(R/'tools/repair_l3_runtime.py'),'--run',str(run),'--trial',str(trial),'--output',str(runtime),
       '--geometry',str(out/'geometry/physical-scene.json')]+(['--resume'] if resume else []),folder)
 record=read(run/'run.json')
 if record['source_sha256']!=tree_digest(trial/'workspace/project'):raise ValueError('MC source changed')
 from tools.l3_content_protection import audit_content
 materialization=audit_content(run,run/'workspace/project',record['source_sha256'],'all_collection_complete')
 write(folder/'source.json',{'trial':str(trial),'model':read(trial/'trial.json')['model'],
       'reasoning_effort':read(trial/'trial.json')['reasoning_effort'],'source_sha256':record['source_sha256'],
       'manifest_sha256':digest(trial/'submission-manifest.json'),'verification_source_sha256':record['verification_source_sha256'],
       **({'runtime_materialization':materialization} if materialization else {})})
 write(folder/'run.json',{'status':'collected','verification_record':str(run/'run.json'),
       'runtime_record':str(runtime/'run.json'),'runtime_record_sha256':digest(runtime/'run.json'),
       **({'runtime_materialization':materialization} if materialization else {})})

def prepare_base(row,folder,target):
 from harness.L3.MinecraftVillage.algorithm_judge import judge
 from harness.L3.MinecraftVillage.algorithm_scores import POLICY
 from harness.L3.Suite.physical_v2 import measure
 from harness.L3.Suite.physical_batch_v2 import inputs
 trial=Path(row['output']);run=folder/'verification';out=folder/'algorithms'
 materialization=read(folder/'source.json').get('runtime_materialization')
 if materialization:
  from tools.l3_content_protection import verify_audit
  verify_audit(run,run/'workspace/project',read(folder/'source.json')['source_sha256'],materialization)
 runtime=out/'runtime-geometry-v2/run.json'
 if read(runtime)['status']!='measured' or read(folder/'run.json')['runtime_record_sha256']!=digest(runtime):
  raise ValueError('Independent MC runtime not ready or changed')
 from tools.l3_leaderboard_batch import process_matches
 while process_matches(read(folder/'visual-prefetch.json',{}).get('pid'),'tools/l3_matrix_mc_visual_prefetch.py'):
  time.sleep(2)
 visual=out/'visual'
 if read(visual/'summary.json',{}).get('status')!='measured':
  if visual.exists():visual.rename(out/('visual-failed-'+str(time.time_ns())))
  judge(run,trial,visual,Path(os.environ['L3_MATRIX_JUDGE_PROVIDER']))
 execute('report',[str(R/'tools/report_l3_algorithms.py'),'--run',str(run),'--trial',str(trial),'--output',str(out)],folder)
 report=read(out/'report.json')
 write(folder/'summary.json',{'task_key':'l3-g01','model':row['model'],'reasoning_effort':row['effort'],'mode':'image',
       'axes':report['axes'],'weights':POLICY['image_weights'],'score_100':None,'status':'awaiting_final_aggregation',
       'missing_axes':report['missing_axes'],'source':{**read(folder/'source.json'),'original_report':str(out/'report.json')}})
 geometry,roles,episodes,_=inputs('l3-g01',row['model'].removeprefix('gpt-6-'))
 if not (target/'physical/physical-summary.json').exists():
  measure(geometry/'physical-scene.json',target/'physical',roles,episodes,read(geometry/'geometry.json'))
 original=read(visual/'summary.json')['original_images'];images=[]
 for filename,sha in original.items():
  path=Path(filename)
  if not path.is_relative_to(run) or not ('/episodes/views/' in filename or filename.endswith('/episodes/reference/reference_rgb.png')):continue
  if digest(path)!=sha:raise ValueError('MC independent image changed')
  images.append({'path':str(path),'label':path.stem,'sha256':sha})
 if not images:raise ValueError('MC has no independently verified images')
 write(folder/'image-manifest.json',{'source_sha256':report['source_sha256'],'images':images})
 return images
