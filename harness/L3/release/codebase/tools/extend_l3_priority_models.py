"""Add the three configured highest-effort model groups."""
def extend():
 
 import copy,fcntl,time,json
 from pathlib import Path
 from tools.l3_leaderboard_batch import B,read,write,variant
 from tools.prioritize_l3_max import select
 new=[('MiniMax-M3.1-Flash','claude'),('doubao-seed-evolving','claude'),('kimi-k3.1-pro','kimi')]
 with (B/'manifest.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  m=read(B/'manifest.json');original=copy.deepcopy(m);templates={r['task_key']:r for r in m['rows']};added=[]
  existing={r['id'] for r in m['rows']}
  for model,harness in new:
   v=variant(model,'max')
   for key,t in sorted(templates.items()):
    rid=key+'--'+v
    if rid in existing:continue
    r={'id':rid,'task_key':key,'task_path':t['task_path'],'task_manifest_sha256':t['task_manifest_sha256'],
       'model':model,'harness':harness,'group':'china','effort':'max','variant':v,
       'status':'queued','reuse_source':None,'output':str(B/'runs'/key/v),'enabled':True,'scheduling_status':'active'}
    added.append(r)
  m['rows']+=added
  m,retired=select(m);assert not retired
  assert len(added) in [0,45]
  if added:
   archive=B/'manifest-history'/('before-extra-max-'+str(time.time_ns())+'.json');write(archive,original)
   m['scope']='Priority table:11 models, highest requested effort,165 active trials;240 other-effort trials paused. Gemini excluded.'
   write(B/'manifest.json',m)
   write(B/'max-priority.json',dict(m['priority_policy'],added_rows=len(added),total_manifest_rows=405,updated_unix=time.time()))
   write(B/'model-catalog-resolution.json',{'checked_unix':time.time(),'source':'authorized provider /v1/models','models':{'MiniMax-M3.1-Flash':'MiniMax-M3.1-Flash','doubao-seed-evolving':'doubao-seed-evolving','kimi-k3.1':'kimi-k3.1-pro'},'gemini':'excluded:optional and no effort specified; preserve previous explicit exclusion'})
  print(json.dumps({'added':len(added),'active':sum(r['enabled'] for r in m['rows']),'paused':sum(not r['enabled'] for r in m['rows']),'total':len(m['rows'])}))

if __name__=="__main__":extend()
