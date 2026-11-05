"""Evaluate one frozen L3 submission with the shared policy."""
import argparse,concurrent.futures,fcntl,hashlib,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from harness.L3.Suite.policy import OUT,MODEL,MODEL_SLUG,read,write,submission_trial
from tools.prepare_l3_trial import assert_engine_available
def execute(label,args,folder):
    with (folder/(label+'.log')).open('a') as log:
        result=subprocess.run([sys.executable,*args],cwd=ROOT,stdout=log,stderr=log)
    if result.returncode:raise RuntimeError(label+' failed; see '+str(folder/(label+'.log')))
def minecraft(trial,folder,engine,gpu):
    run=folder/'verification';out=folder/'algorithms';out.mkdir(exist_ok=True)
    if not (run/'run.json').exists() or read(run/'run.json').get('status') not in {'collected','measured'}:
        args=[str(ROOT/'tools/verify_l3_submission.py'),'--project',str(trial/'workspace/project'),'--output',str(run),
              '--engine-copy',str(engine),'--gpu',str(gpu),'--trial',str(trial),'--collect-only',
              '--annotations',str(ROOT/'benchmarks/l3/reference/minecraft-visible-v1-provisional.json')]
        if (run/'run.json').exists():args+=['--resume']
        execute('collect',args,folder)
    def geometry():
        if not (out/'geometry/geometry.json').exists():
            if (out/'geometry').exists():(out/'geometry').rename(out/('geometry-failed-'+str(time.time_ns())))
            execute('geometry',['-m','harness.L3.MinecraftVillage.algorithm_geometry','--run',str(run),'--trial',str(trial),'--output',str(out/'geometry')],folder)
    def judge():
        if not (out/'visual/summary.json').exists() or read(out/'visual/summary.json').get('status')!='measured':
            if (out/'visual').exists():(out/'visual').rename(out/('visual-failed-'+str(time.time_ns())))
            execute('visual',['-m','harness.L3.MinecraftVillage.algorithm_judge','--run',str(run),'--trial',str(trial),'--output',str(out/'visual'),'--provider',str(ROOT.parent/'.config/3dbench/provider.json')],folder)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        g=pool.submit(geometry);v=pool.submit(judge)
        if not (out/'capture/capture.json').exists():
            execute('capture',[str(ROOT/'tools/capture_l3_algorithms.py'),'--run',str(run),'--trial',str(trial),'--output',str(out/'capture')],folder)
        g.result()  # Runtime pose planning requires the completed physical scene.
        if not (out/'runtime-geometry-v2/run.json').exists() or read(out/'runtime-geometry-v2/run.json').get('status')!='measured':
            stamp=str(time.time_ns())
            for partial in [out/'runtime-geometry-v2',run/'workspace/runtime-geometry-v2']:
                if partial.exists():partial.rename(partial.with_name(partial.name+'-failed-'+stamp))
            execute('runtime',[str(ROOT/'tools/repair_l3_runtime.py'),'--run',str(run),'--trial',str(trial),'--output',str(out/'runtime-geometry-v2'),
                '--geometry',str(out/'geometry/physical-scene.json')],folder)
        v.result()
    execute('report',[str(ROOT/'tools/report_l3_algorithms.py'),'--run',str(run),'--trial',str(trial),'--output',str(out)],folder)
    result=read(out/'report.json')
    write(folder/'summary.json',{'task_key':'l3-g01','model':MODEL,'score_100':result['pilot_score_100'],
        'axes':result['axes'],'weights':result['policy']['image_weights'],'missing_axes':result['missing_axes'],
        'status':'measured' if result['pilot_score_100'] is not None else 'incomplete','protocol':result['protocol'],
        'source':{'trial':str(trial),'source_sha256':result['source_sha256']},
        'evidence_files':['algorithms/report.json','algorithms/report.zh.md'],'completed_unix':time.time()})
def main():
    p=argparse.ArgumentParser();p.add_argument('--collect-only',action='store_true');p.add_argument('--key',required=True);p.add_argument('--engine',required=True,type=Path);p.add_argument('--gpu',required=True,type=int);a=p.parse_args()
    engine=a.engine.resolve();folder=OUT/a.key;folder.mkdir(parents=True,exist_ok=True)
    allowed=sorted(os.sched_getaffinity(0));width=min(8,len(allowed));start=(os.getpid()*width)%len(allowed);os.sched_setaffinity(0,[allowed[(start+i)%len(allowed)] for i in range(width)])
    lock=ROOT/'data/l3/locks'/('engine-'+hashlib.sha256(str(engine).encode()).hexdigest()[:16]+'.lock')
    with (folder/'evaluation.lock').open('a') as tasklock,lock.open('a') as enginelock:
        fcntl.flock(tasklock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(enginelock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert_engine_available(engine)
        trial=submission_trial(a.key)
        if os.environ.get('L3_EVAL_TRIAL'):
            from harness.L3.Suite.submission_binding import validate_submission
            validate_submission(trial,a.key,MODEL,os.environ.get('L3_EVAL_EFFORT'))
        if read(trial/'trial.json')['status']!='generated_awaiting_independent_verification':raise RuntimeError('Generation not complete')
        write(folder/'evaluation-worker.json',{'status':'running','pid':os.getpid(),'model':MODEL,'engine':str(engine),'started_unix':time.time()})
        if a.collect_only:
            if a.key=='l3-g01':
                run=folder/'verification'
                existing=read(run/'run.json') if (run/'run.json').exists() else {}
                if existing.get('status') not in {'collected','measured'}:
                    if existing.get('status')=='failed':
                        from harness.L3.MinecraftVillage.protocol import tree_digest
                        if tree_digest(run/'workspace/project/Plugins/BenchRuntime')!=tree_digest(ROOT/'ue5/BenchRuntime'):
                            from tools.refresh_l3_mask_observer import refresh
                            refresh(run,engine,a.gpu,lock_held=True)
                    args=[str(ROOT/'tools/verify_l3_submission.py'),'--project',str(trial/'workspace/project'),'--output',str(run),
                          '--engine-copy',str(engine),'--gpu',str(a.gpu),'--trial',str(trial),'--collect-only',
                          '--annotations',str(ROOT/'benchmarks/l3/reference/minecraft-visible-v1-provisional.json')]
                    if (run/'run.json').exists():args+=['--resume']
                    execute('collect',args,folder)
                record=read(run/'run.json')
                if record.get('status') not in {'collected','measured'}:raise RuntimeError('Minecraft collection incomplete')
                from tools.l3_matrix_mc import collect_runtime
                collect_runtime(trial,folder)
            else:
                from harness.L3.Suite.collect import collect
                collect(a.key,engine,a.gpu)
            write(folder/'evaluation-worker.json',{'status':'collected','pid':os.getpid(),'model':MODEL,'reasoning_effort':os.environ.get('L3_EVAL_EFFORT'),'finished_unix':time.time()})
            return
        if a.key=='l3-g01':minecraft(trial,folder,engine,a.gpu)
        else:
            from harness.L3.Suite.collect import collect
            from harness.L3.Suite.batch import physical_worker,visual_worker,summarize
            collect(a.key,engine,a.gpu)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                f=pool.submit(physical_worker,folder);v=pool.submit(visual_worker,folder)
                f.result();v.result()
            summarize(folder)
        result=read(folder/'summary.json')
        if result['status']!='measured':raise RuntimeError('Metrics incomplete: '+str(result['missing_axes']))
        write(folder/'evaluation-worker.json',{'status':'measured','pid':os.getpid(),'model':MODEL,'score_100':result['score_100'],'finished_unix':time.time()})
        print(json.dumps({'model':MODEL,'task':a.key,'score_100':result['score_100']}),flush=True)
if __name__=='__main__':main()
