"""Finite worker pool for independent replay of all frozen physical evidence."""
import os,sys,time,subprocess,concurrent.futures,traceback
from pathlib import Path
from .policy import ROOT,read,write
from .reference_review import OUT,CAT
from .physical_v2 import VERSION,measure

def inputs(key,model):
    old=Path(os.environ['L3_EVAL_OUT'])/key if os.environ.get('L3_EVAL_OUT') else ROOT/'data/l3/evaluations'/('suite-'+model+'-v1')/key
    summary=read(old/'summary.json')
    if key=='l3-g01':
        from harness.L3.MinecraftVillage.protocol import DOORS,CHESTS,CROPS,BLOCKS,FURNACES
        report_path=Path(summary['source']['original_report']) if model=='astra' and not os.environ.get('L3_EVAL_OUT') else old/'algorithms/report.json'
        report=read(report_path);geometry=report_path.parent/'geometry'
        roles={k:role for group,role in [(DOORS,'door'),(CHESTS,'container'),(CROPS,'crop'),(BLOCKS,'editable_block'),(FURNACES,'furnace')] for k in group}
        episodes=Path(report['verification'])/'workspace/episodes'
    else:
        geometry=old;episodes=old/'motion-episodes';roles={e['id']:e['role'] for e in read(old/'contract.json')['entities']}
    return geometry,roles,episodes,summary

def worker(key,model):
    target=OUT/key/('gpt-6-'+model)/'physical';target.mkdir(exist_ok=True,parents=True)
    existing=target/'physical-summary.json'
    # Join an already running worker instead of duplicating expensive geometry.
    record=target/'worker.json'
    if record.exists():
        proc=Path('/proc',str(read(record)['pid']))
        while proc.exists() and not existing.exists():
            try:
                args=(proc/'cmdline').read_bytes()
                if b'harness.L3.Suite.physical_batch_v2' not in args or key.encode() not in args:break
                if ') Z ' in (proc/'stat').read_text():break
            except FileNotFoundError:break
            time.sleep(5)
    if existing.exists():
        if read(existing).get('version')==VERSION:return
        existing.rename(target/('physical-summary-'+str(time.time_ns())+'.json'))
    env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    with (target/'worker.log').open('ab') as log:
        p=subprocess.Popen([sys.executable,'-u','-m','harness.L3.Suite.physical_batch_v2','one',key,model],cwd=ROOT,env=env,stdout=log,stderr=log)
        write(target/'worker.json',{'pid':p.pid,'started_unix':time.time()})
        if p.wait():raise RuntimeError('Physical measurement failed: '+str(target/'worker.log'))

def main():
    data=read(OUT/'input-catalogue.json');jobs={};done=[];errors={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for t in data['tasks']:
            if t.get('level')!=3:continue
            for r in t['generation_runs']:
                slug=r['model'].removeprefix('gpt-6-');jobs[pool.submit(worker,t['key'],slug)]=t['key']+'/'+slug
        for future in concurrent.futures.as_completed(jobs):
            key=jobs[future]
            try:future.result();done.append(key);print('physical complete',key,flush=True)
            except Exception as exc:errors[key]=str(exc);traceback.print_exc()
            write(OUT/'physical-progress.json',{'completed':done,'errors':errors,'total':len(jobs),'updated_unix':time.time()})
    if errors:raise RuntimeError('Physical measurement failures')

if __name__=='__main__':
    if len(sys.argv)>1:
        key,model=sys.argv[2:];g,roles,episodes,summary=inputs(key,model)
        allowed=sorted(os.sched_getaffinity(0));offset=(sum(map(ord,key+model))*8)%len(allowed);os.sched_setaffinity(0,(allowed+allowed)[offset:offset+min(8,len(allowed))])
        output=OUT/key/('gpt-6-'+model)/'physical'
        measure(g/'physical-scene.json',output,roles,episodes,read(g/'geometry.json'))
    else:main()
