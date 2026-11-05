"""Supplement unsupported runtime geometry without changing the frozen candidate."""
import json,os,shutil,subprocess,sys,time
from pathlib import Path
import numpy as np
from .policy import ROOT,OUT,read,write
from harness.L3.MinecraftVillage.protocol import digest,tree_digest

def collect(key):
 folder=OUT/key;out=folder/'geometry-supplement';out.mkdir(exist_ok=True)
 work=out/'workspace';project=work/'project';source=read(folder/'source.json')
 original=Path(source['trial'])/'workspace/project'
 for rel,sha in read(Path(source['trial'])/'submission-manifest.json').items():
  if digest(original/rel)!=sha:raise RuntimeError('Frozen source changed')
 if not project.exists():
  shutil.copytree(original,project,ignore=shutil.ignore_patterns('Binaries','Intermediate','Saved','DerivedDataCache'))
  plugin=project/'Plugins/BenchRuntime';shutil.rmtree(plugin);shutil.copytree(ROOT/'ue5/BenchRuntime',plugin)
  p=plugin/'Source/BenchRuntime/Private/BenchObserver.cpp';p.write_text(p.read_text().replace('TickIndex%2==0','TickIndex%12==0'))
  (work/'.home').mkdir(parents=True)
  cache=work/'.cache/ue';cache.parent.mkdir(exist_ok=True)
  shutil.copytree(ROOT/'data/l3/preparation/l3-suite-20261023/equipment-smoke/workspace/.cache/ue',cache)
 plan=read(folder/'workspace/plans/views.json');plan['steps']=plan['steps'][:5];write(work/'plan.json',plan)
 record={'status':'preparing','source':source,'observer_sha256':tree_digest(project/'Plugins/BenchRuntime'),
         'verification_source_sha256':tree_digest(project),'started_unix':time.time()}
 write(out/'run.json',record)
 command=read(folder/'run.json')['command'];name='l3-suite-extra-'+key
 command=[name if x=='l3-suite-eval-'+key else x.replace('src='+str(folder/'workspace')+',','src='+str(work)+',') for x in command]
 try:
  check=subprocess.run(['docker','inspect',name],capture_output=True)
  start=subprocess.run(['docker','start',name] if check.returncode==0 else command,capture_output=True,text=True)
  (out/'container-start.log').write_text(start.stdout+start.stderr)
  if start.returncode:raise RuntimeError('Supplement container startup failed')
  for stage,args in [
   ('build',['build','/workspace/project','--output','/workspace/build','--jobs','12','--blueprints']),
   ('capture',['preview','/workspace/project','--output','/workspace/episode','--plan','/workspace/plan.json','--timeout','1800'])]:
   record['status']=stage;write(out/'run.json',record)
   with (out/(stage+'.log')).open('a') as log:
    subprocess.run(['docker','exec',name,'python3','/opt/l3-public/ue.py',*args],stdout=log,stderr=log,check=True,timeout=3600)
  old=read(folder/'workspace/episodes/views/scene_geometry.json');geometry=work/'episode/scene_geometry.json';new=read(geometry)
  identify=lambda i:(i['actor'],i['component'],i.get('instance',0))
  a={identify(i):i for i in old['instances']};b={identify(i):i for i in new['instances']}
  if not set(a)<=set(b):raise RuntimeError('Supplement lost original instances')
  delta=max(float(np.max(np.abs(np.array(a[k][field])-np.array(b[k][field])))) for k in a for field in ['origin_cm','axis_x','axis_y','axis_z'])
  if delta>.01:raise RuntimeError('Supplement original transforms differ: '+str(delta))
  assert tree_digest(project)==record['verification_source_sha256'],'Supplement verifier project modified'
  result={'status':'collected','geometry':str(geometry),'sha256':digest(geometry),'source_sha256':source['source_sha256'],
          'observer_sha256':record['observer_sha256'],'original_instances':len(a),'complete_instances':len(b),
          'maximum_original_transform_delta_cm':delta,'geometry_protocol':'ue5-full-mesh-v1'}
  write(out/'result.json',result);record.update(status='collected',result=result,finished_unix=time.time());write(out/'run.json',record)
  print(json.dumps(result),flush=True)
 except Exception as e:
  record.update(status='failed',error=str(e));write(out/'run.json',record);raise
 finally:subprocess.run(['docker','stop','--time','10',name],capture_output=True)
if __name__=='__main__':collect(sys.argv[1])
