"""Prefetch the unchanged source-bound MC visual evaluation during UE replay."""
import sys,os,fcntl,time
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R))
from tools.l3_leaderboard_batch import B,read,write,process_matches
def main():
 row=next(r for r in read(B/'manifest.json')['rows'] if r['id']==sys.argv[1] and r.get('enabled'))
 folder=B/'evaluations/runtime'/row['variant']/row['task_key'];run=folder/'verification';output=folder/'algorithms/visual'
 assert row['task_key']=='l3-g01' and read(run/'run.json')['status'] in {'collected','measured'}
 with (folder/'visual-prefetch.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  marker=folder/'visual-prefetch.json'
  state={'pid':os.getpid(),'row':row['id'],'started_unix':time.time(),'status':'running','output':str(output)}
  write(marker,state)
  try:
   if read(output/'summary.json',{}).get('status')=='measured':
    state['status']='already_measured';return
   if output.exists():output.rename(output.with_name('visual-prefetch-failed-'+str(time.time_ns())))
   from harness.L3.MinecraftVillage.algorithm_judge import judge
   result=judge(run,Path(row['output']),output,Path(os.environ['L3_MATRIX_JUDGE_PROVIDER']))
   state.update(status=result['status'],finished_unix=time.time())
  except Exception as error:
   state.update(status='failed',error=str(error),finished_unix=time.time());raise
  finally:write(marker,state)
if __name__=='__main__':main()
