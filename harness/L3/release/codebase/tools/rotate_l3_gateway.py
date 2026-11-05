"""Atomically replace one host gateway; drain old requests without stopping its agent."""
import argparse,os,signal,subprocess,sys,time
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R))
from tools.l3_leaderboard_batch import B,P,read,write,gateway_env,process_matches

def guard(trial):
 trial=Path(trial);record=read(trial/'gateway-rotation.json');old=record['old_pid'];new=record['new_pid']
 while True:
  if process_matches(old,'l3_model_bridge.py'):
   tasks=Path('/proc')/str(old)/'task'
   if len(list(tasks.iterdir()))==1:
    os.kill(old,signal.SIGTERM);record['old_drained_unix']=time.time();write(trial/'gateway-rotation.json',record)
  state=read(trial/'state.json',{})
  if state.get('status') in {'generated','failed'} and not process_matches(state.get('pid'),'l3_leaderboard_batch.py worker'):
   for pid in [old,new]:
    if process_matches(pid,'l3_model_bridge.py'):os.kill(pid,signal.SIGTERM)
   record['finished_unix']=time.time();write(trial/'gateway-rotation.json',record);return
  time.sleep(3)

def rotate(row):
 trial=Path(row['output']);environment=read(trial/'environment.json');old=environment['gateway_pid']
 prior=read(trial/'gateway-rotation.json',{})
 if prior.get('new_pid')==old and process_matches(old,'l3_model_bridge.py'):return
 assert process_matches(old,'l3_model_bridge.py')
 folder=Path(environment['gateway_directory']);next_socket=folder/('api-next-'+str(time.time_ns())+'.sock')
 with (trial/'gateway-rotation.log').open('a') as log:
  proc=subprocess.Popen([sys.executable,str(R/'tools/l3_model_bridge.py'),'serve','--socket',str(next_socket),
   '--provider',str(P/(row['group']+'.json')),'--ledger',str(trial/'model-requests.jsonl'),
   '--stage-file',str(trial/'model-stage.txt')],env=gateway_env(row['group'],row['model'],row['effort']),
   cwd=R,stdout=log,stderr=log,start_new_session=True)
  for _ in range(100):
   if next_socket.exists():break
   if proc.poll() is not None:raise RuntimeError('New gateway exited; old gateway retained')
   time.sleep(.05)
  else:
   proc.terminate();raise RuntimeError('Gateway bind timeout; old gateway retained')
  os.replace(next_socket,folder/'api.sock')
  environment['gateway_pid']=proc.pid;write(trial/'environment.json',environment)
  write(trial/'gateway-rotation.json',{'old_pid':old,'new_pid':proc.pid,'time':time.time(),'reason':'Load configurable provider concurrency; preserve active streams'})
  guardian=subprocess.Popen([sys.executable,str(Path(__file__)),'--guard',str(trial)],cwd=R,stdout=log,stderr=log,start_new_session=True)
  print(row['id'],'gateway',proc.pid,'drain_guard',guardian.pid,flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--guard');a=p.parse_args()
 if a.guard:guard(a.guard)
 else:
  for row in read(B/'manifest.json')['rows']:
   state=read(Path(row['output'])/'state.json',{})
   if row['group']=='china' and process_matches(state.get('pid'),'l3_leaderboard_batch.py worker'):rotate(row)
