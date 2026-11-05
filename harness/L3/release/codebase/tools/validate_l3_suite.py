"""Validate frozen generation packages and their offline dependencies without model calls."""
import argparse, hashlib, json, os
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def read(p):return json.loads(p.read_text())
def check_hashes(root, files):
 for name,digest in files.items():
  p=(root/name).resolve()
  if not p.is_relative_to(root.resolve()):raise ValueError('Path outside package: '+name)
  if not p.is_file() or sha(p)!=digest:raise ValueError('Missing or changed file: '+str(p))
def validate_minecraft(task,manifest,meta):
 inp=task/'environment/input';refs=read(inp/'references.json');runtime=read(task/'runtime.json')
 assert meta['key']==manifest['task_key']=='l3-g01' and meta['domain']=='game'
 assert meta['input_mode']==refs['input_mode']=='image' and len(refs['images'])==1
 for ref in refs['images']:
  check_hashes(inp,{ref['path']:ref['sha256']})
  with Image.open(inp/ref['path']) as im:
   im.load();assert im.size==(ref['width'],ref['height']) and min(im.size)>=400
  original=read(task/'attribution/references.json')
  assert next(r for r in original['images'] if r['path']==ref['path'])['provenance']['source'].startswith('https://')
 prompt=(task/'PROMPT.md').read_text();en=(task/'instruction.md').read_text()
 assert prompt.startswith(en.rstrip()) and 'entire open-world Minecraft environment' in prompt
 assert 'within 3600 seconds' not in prompt
 assert not any('\u4e00'<=c<='\u9fff' for c in prompt)
 assert len((task/'instruction.zh.md').read_text())>200
 for name in ['REQUIREMENTS.md','INTEGRATION.md','ASSETS.md','BenchEntity.h','BenchInventory.h']:
  assert (inp/name).is_file()
 source=read(task/'input-provenance.json');check_hashes(task/'environment',source['input_hashes'])
 assert source['candidate_files_included'] is False
 assert runtime['time_limit_seconds'] is None and runtime['completion_policy']=='complete_delivery'
 assert runtime['reasoning_effort']=='high' and runtime['models']==['gpt-6-luna','gpt-6-sol','gpt-6-astra']
 assert meta['execution_status']=='generation_ready' and abs(sum(meta['weights'].values())-1)<1e-8
 return {'task_key':'l3-g01','domain':'game','input_mode':'image','references':1,'entities':None,
         'files':len(manifest['files']),'manifest_sha256':sha(task/'package-manifest.json')}

def validate_task(task):
 manifest=read(task/'package-manifest.json');check_hashes(task,manifest['files'])
 actual={str(p.relative_to(task)) for p in task.rglob('*') if p.is_file() and p.name!='package-manifest.json'}
 if actual!=set(manifest['files']):raise ValueError('Unmanifested task files: '+str(actual-set(manifest['files'])))
 meta=read(task/'task.json')
 if meta.get('package_format')=='minecraft-openworld-v1':return validate_minecraft(task,manifest,meta)
 inp=task/'environment/input';refs=read(inp/'references.json');contract=read(inp/'interaction-contract.json');runtime=read(task/'runtime.json')
 assert meta['key']==manifest['task_key']==contract['task_key']
 assert refs['input_mode']==meta['input_mode']
 assert bool(refs['images'])==(meta['input_mode']=='image')
 for r in refs['images']:
  check_hashes(inp,{r['path']:r['sha256']})
  with Image.open(inp/r['path']) as im:
   im.load();assert im.size==(r['width'],r['height']) and min(im.size)>=400
  original=read(task/'attribution/references.json')
  assert next(image for image in original['images'] if image['path']==r['path'])['provenance']['source'].startswith('https://')
 en=(task/'instruction.md').read_text();zh=(task/'instruction.zh.md').read_text();prompt=(task/'PROMPT.md').read_text()
 assert len(en)>800 and len(zh)>200 and prompt.startswith(en)
 assert not any('\u4e00'<=c<='\u9fff' for c in prompt)
 assert (inp/'REQUIREMENTS.md').read_text()==en
 assert len({e['id'] for e in contract['entities']})==len(contract['entities'])
 assert all(e['actions'] and e['initial'] and len(set(e['actions']))==len(e['actions']) for e in contract['entities'])
 assert len(contract['zones'])>=4
 assert runtime['models']==['gpt-6-luna','gpt-6-astra']
 assert runtime['time_limit_seconds'] is None and runtime['target_generation_seconds']==3600
 assert meta['execution_status']=='generation_ready'
 assert abs(sum(meta['weights'].values())-1)<1e-8
 assert not any('provider.json' in p or p.startswith(('tests/','verifier/')) for p in manifest['files'])
 return {'task_key':meta['key'],'domain':{'real_world':'real'}.get(meta['domain'],meta['domain']),'input_mode':meta['input_mode'],'references':len(refs['images']),'entities':len(contract['entities']),'files':len(manifest['files']),'manifest_sha256':sha(task/'package-manifest.json')}
def library_path(value):
 if not value.startswith('@assets/'):
  raise ValueError('Expected an @assets/ library binding')
 root = Path(os.environ['L3_ASSET_ROOT']).expanduser().resolve()
 path = root / value.removeprefix('@assets/')
 if not path.resolve().is_relative_to(root):raise ValueError('Library outside L3_ASSET_ROOT')
 return path

def validate(repo, batch_path, libraries=True):
 idx=read(repo/'tasks/L3/task-index.json');batch=read(batch_path);rows=[validate_task(repo/t['path']) for t in idx['tasks']]
 assert len(rows)==14 and len({r['task_key'] for r in rows})==14
 assert sum(bool(r['references']) for r in rows)==9
 counts={d:{m:sum(r['domain']==d and r['input_mode']==m for r in rows) for m in ['image','text']} for d in ['game','embodied','real']}
 counts['game']['image']+=1
 assert counts==idx['distribution']
 total=len(batch['runs']);assert total==batch['total_runs']
 assert len({r['id'] for r in batch['runs']})==total and len({r['output'] for r in batch['runs']})==total
 known={r['task_key']:r for r in rows};paths={t['key']:t['path'] for t in idx['tasks']}
 models={r['model'] for r in batch['runs'] if r['task_key'] in known}
 assert {'gpt-6-luna','gpt-6-astra'}<=models<={'gpt-6-luna','gpt-6-sol','gpt-6-astra'}
 for task in rows:
  runs=[r for r in batch['runs'] if r['task_key']==task['task_key']]
  assert {r['model'] for r in runs}==models and len(runs)==len(models)
 additional=[]
 for run in batch['runs']:
  key=run['task_key']
  if key not in known:
   assert key=='l3-g01'
   checked=validate_task(repo/run['task_path']);assert checked['task_key']==key
   known[key]=checked;paths[key]=run['task_path'];additional.append(checked)
  assert run['task_path']==paths[key]
  assert run['model'] in {'gpt-6-luna','gpt-6-sol','gpt-6-astra'}
  assert run['package_manifest_sha256']==known[key]['manifest_sha256']
  assert run.get('reasoning_effort','high')=='high'
 assert len({(r['task_key'],r['model']) for r in batch['runs']})==total
 library_results={}
 if libraries:
  first=repo/idx['tasks'][0]['path'];runtime=read(first/'runtime.json')
  modelpath=library_path(runtime['model_manifest']);models=read(modelpath);allfiles={f['path']:f['sha256'] for p in models['packs'] for f in p['files']}
  check_hashes(modelpath.parent,allfiles)
  materialpath=library_path(runtime['material_manifest']);materials=read(materialpath)
  check_hashes(materialpath.parent,{f['path']:f['sha256'] for f in materials['files']})
  for entry in idx['tasks']:
   task=repo/entry['path'];pack=read(task/'package-manifest.json');selection=read(task/'environment/input/asset-selection.json')
   assert pack['libraries']==selection['catalog_sha256']=={'models':sha(modelpath),'materials':sha(materialpath)}
   assert set(selection['material_ids'])<={a['id'] for a in materials['assets']}
   assert set(selection['model_packs'])<={p['id'] for p in models['packs']}
  library_results={'model_files_verified':len(allfiles),'material_files_verified':len(materials['files']),'model_manifest_sha256':sha(modelpath),'material_manifest_sha256':sha(materialpath)}
 return {'passed':True,'tasks':rows,'distribution_including_minecraft':counts,'planned_runs':total,'additional_tasks':additional,'libraries':library_results,'paid_model_requests':0}
def main():
 p=argparse.ArgumentParser();p.add_argument('--batch',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--skip-library-hashes',action='store_true');a=p.parse_args()
 try:result=validate(ROOT,a.batch,not a.skip_library_hashes)
 except Exception as exc:
  a.output.write_text(json.dumps({'passed':False,'error':type(exc).__name__+': '+str(exc)},indent=2)+'\n');raise
 a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='tasks'},ensure_ascii=False))
if __name__=='__main__':main()
