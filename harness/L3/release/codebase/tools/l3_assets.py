"""Offline search and UE import entry point. No network requests."""
import argparse,json,os,subprocess
from pathlib import Path

def catalog(kind):
 if kind=='model':
  m=json.loads(Path('/assets/models/manifest.json').read_text())
  return [{'id':p['id']+'/'+Path(f).stem,'path':f,'pack':p['id'],'license':p['license']} for p in m['packs'] for f in p['models'] if f.lower().endswith('.fbx')]
 m=json.loads(Path('/assets/polyhaven/manifest.json').read_text())
 return [{k:a[k] for k in ['id','name','tags','categories','source','license']} for a in m['assets']]
def search(kind,query,limit):
 rows=catalog(kind);words=query.lower().split()
 ranked=[(sum(w in json.dumps(r).lower() for w in words),r) for r in rows]
 return [r for n,r in sorted(ranked,key=lambda x:(-x[0],x[1]['id'])) if n or not words][:limit]
def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True);q=s.add_parser('search');q.add_argument('query');q.add_argument('--type',choices=['model','material'],default='model');q.add_argument('--limit',type=int,default=15)
 for kind in ['models','materials']:
  q=s.add_parser('import-'+kind);q.add_argument('--project',type=Path,default=Path('/workspace/project'));q.add_argument('--output',type=Path,required=True);q.add_argument('ids',nargs='+')
 a=p.parse_args()
 if a.cmd=='search':print(json.dumps(search(a.type,a.query,a.limit),indent=2));return
 a.output.mkdir(parents=True,exist_ok=False);project=next(a.project.glob('*.uproject'));cfg=a.output/'import.json';report=a.output/'report.json';env=dict(os.environ)
 if a.cmd=='import-models':
  rows={r['id']:r for r in catalog('model')};paths=[rows[x]['path'] if x in rows else x for x in a.ids]
  cfg.write_text(json.dumps({'library':'/assets/models','paths':paths,'report':str(report)}));env['L3_MODEL_IMPORT']=str(cfg);script=Path(__file__).with_name('ue_import_l3_models.py')
 else:
  cfg.write_text(json.dumps({'manifest':'/assets/polyhaven/manifest.json','ids':a.ids,'report':str(report)}));env['L3_MATERIAL_IMPORT']=str(cfg);script=Path(__file__).with_name('ue_import_l3_materials.py')
 cmd=[str(Path(os.environ['UE5_ROOT'])/'Engine/Binaries/Linux/UnrealEditor-Cmd'),str(project),'-run=pythonscript','-script='+str(script),'-unattended','-NullRHI','-nosplash','-nosound','-nop4','-DDC=NoZenLocalFallback','-corelimit=16']
 with (a.output/'import.log').open('w') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,env=env)
 if r.returncode or not report.exists():raise SystemExit('Import failed; see '+str(a.output/'import.log'))
 print(report.read_text())
if __name__=='__main__':main()
