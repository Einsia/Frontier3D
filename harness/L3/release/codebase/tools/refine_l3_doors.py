"""Capture matched side-lane door tests after runtime pose measurement."""
import argparse,json,subprocess,time,sys,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harness.L3.MinecraftVillage.protocol import read_json,write_json,digest,tree_digest
from harness.L3.MinecraftVillage.geometry_routes import derive_bindings
from harness.L3.MinecraftVillage.algorithm_workflow import door_walk_plan,diagnose_doors

def refine(trial,run):
    o=trial/'evaluation-algorithm-v1/runtime-geometry-v2';r=read_json(o/'run.json');base=read_json(run/'run.json')
    if r['status']!='measured':raise ValueError('Runtime collection must be complete')
    if r['source_sha256']!=tree_digest(trial/'workspace/project'):raise ValueError('Candidate changed')
    b=read_json(o/'bindings.json');ex=read_json(trial/'evaluation-algorithm-v1/geometry/physical-scene.json')
    derived,_=derive_bindings(ex,b,read_json(run/'workspace/episodes/views/initial.json'))
    for k,v in derived['entities'].items():
        if 'test_lane_offset_cm' in v:b['entities'][k]['test_lane_offset_cm']=v['test_lane_offset_cm']
    p,m=door_walk_plan(b);sub=run/'workspace/runtime-geometry-v2';key='door_walk_lanes'
    if (sub/key).exists():raise ValueError('Refinement evidence already exists')
    archive=o/'door-lane-revision';archive.mkdir(exist_ok=False)
    for n in ['run.json','door-walk.json','door-meta.json']:shutil.copy2(o/n,archive/n)
    write_json(sub/(key+'-plan.json'),p);write_json(o/'door-lane-meta.json',m)
    engines=[x.split('src=',1)[1].split(',dst=',1)[0] for x in base['command'] if x.startswith('type=bind,src=') and '/engines/' in x]
    for cid in subprocess.check_output(['docker','ps','-q'],text=True).split():
        i=json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]
        if any(x['Source'] in engines for x in i['Mounts']):raise ValueError('Engine busy')
    name=base['container'];started=time.monotonic();r['status']='episode_door_walk_lanes';write_json(o/'run.json',r)
    try:
        subprocess.run(['docker','start',name],check=True,stdout=subprocess.DEVNULL)
        cmd=['docker','exec',name,'python3','/opt/l3-public/ue.py','preview','/workspace/project','--output','/workspace/runtime-geometry-v2/'+key,'--plan','/workspace/runtime-geometry-v2/'+key+'-plan.json','--timeout','1200']
        with (o/(key+'.log')).open('x') as f:rc=subprocess.run(cmd,stdout=f,stderr=f,timeout=1300).returncode
        if rc or not read_json(sub/key/'completed.json').get('completed'):raise ValueError('Door lane capture failed')
        write_json(o/'door-walk.json',diagnose_doors(sub/key,m))
        if tree_digest(trial/'workspace/project')!=r['source_sha256'] or tree_digest(run/'workspace/project')!=r['verification_source_sha256']:raise ValueError('Source changed')
        r['episodes'][key]={'completed':True,'seconds':time.monotonic()-started}
        r['elapsed_seconds']+=time.monotonic()-started
        r.update(status='measured',evidence_sha256={str(p.relative_to(run)):digest(p) for p in sub.rglob('*') if p.is_file() and p.suffix in {'.json','.png'}},diagnostics_sha256={p.name:digest(p) for p in o.glob('*.json') if p.name!='run.json'})
        write_json(o/'run.json',r)
    except Exception as e:r.update(status='failed',error=str(e));write_json(o/'run.json',r);raise
    finally:subprocess.run(['docker','stop','--time','10',name],capture_output=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--trial',type=Path,required=True);p.add_argument('--run',type=Path,required=True);a=p.parse_args();refine(a.trial.resolve(),a.run.resolve())
