"""Finite, resumable source-bound reference review batch; no score-selected retries."""
import concurrent.futures,time,traceback,hashlib
from .reference_review import CAT,OUT,VERSION,review
from .policy import read,write

def worker(task,run,assets):
    folder=OUT/task['key']/run['model'];folder.mkdir(parents=True,exist_ok=True)
    result=folder/'reference-review.json'
    if result.exists():
        saved=read(result)
        if saved['source_sha256']!=run['images'][0]['submission_sha256'] or saved['method']!=VERSION:raise ValueError('Review source mismatch')
        return
    write(result,review(task,run,assets))

def main():
    data=read(CAT/'snapshot.json');assets=read(CAT/'assets.json')
    OUT.mkdir(exist_ok=True,parents=True)
    frozen=OUT/'input-catalogue.json'
    if not frozen.exists():write(frozen,data)
    else:data=read(frozen)
    jobs={};done=[];errors={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for task in data['tasks']:
            if task.get('level')!=3 or task.get('input_mode')!='image':continue
            for run in task['generation_runs']:
                jobs[pool.submit(worker,task,run,assets)]=task['key']+'/'+run['model']
        for job in concurrent.futures.as_completed(jobs):
            key=jobs[job]
            try:job.result();done.append(key);print('review complete',key,flush=True)
            except Exception as exc:errors[key]=str(exc);traceback.print_exc()
            write(OUT/'reference-progress.json',{'completed':done,'errors':errors,'total':len(jobs),'updated_unix':time.time()})
    if errors:raise RuntimeError('Reference review failures: '+str(errors))
if __name__=='__main__':main()
