"""Select the requested highest-effort matrix and pause other generation."""
import copy,fcntl,json,os,signal,subprocess,time,concurrent.futures
from pathlib import Path
from tools.l3_leaderboard_batch import B,R,read,write,process_matches
TARGETS={
 "gpt-6-astra":("max","codex"),"gpt-6.1-sol":("max","codex"),
 "gpt-6-luna":("max","codex"),"claude-opus-5-5":("max","claude"),
 "glm-5.3-flash":("max","zcode"),"kimi-k3":("max","kimi"),
 "deepseek-v4.1-flash":("max","dsh"),"qwen3.8-max":("xhigh","claude"),
 "MiniMax-M3.1-Flash":("max","claude"),"doubao-seed-evolving":("max","claude"),
 "kimi-k3.1-pro":("max","kimi")}
def select(manifest):
 out=copy.deepcopy(manifest);retired=[]
 for r in out["rows"]:
  if r["model"]=="qwen3.8-max" and r["effort"]=="xhigh" and r["harness"]!="claude":
   retired.append(copy.deepcopy(r))
   r["variant"]="qwen3.8-max--xhigh--claude"
   r["id"]=r["task_key"]+"--"+r["variant"]
   r["harness"]="claude";r["output"]=str(B/"runs"/r["task_key"]/r["variant"])
   r["status"]="queued";r["reuse_source"]=None
  r["enabled"]=TARGETS.get(r["model"])==(r["effort"],r["harness"])
  r["scheduling_status"]="active" if r["enabled"] else "paused_by_user"
 assert len(out["rows"])==405 and len({r["id"] for r in out["rows"]})==405
 assert sum(r["enabled"] for r in out["rows"])==165
 out["retired_variants"]=sorted(set(out.get("retired_variants",[]))|{r["variant"] for r in retired})
 out["priority_policy"]={"targets":{m:{"effort":v[0],"harness":v[1]} for m,v in TARGETS.items()},
    "active_trials":165,"paused_trials":240,"reason":"User table: max priority, Qwen xhigh on ClaudeCode"}
 out["updated_unix"]=time.time()
 return out,retired

def apply():
 before=read(B/"manifest.json");after,retired=select(before)
 if before.get("priority_policy")==after["priority_policy"] and not retired:return {"already_applied":True}
 stamp=str(time.time_ns());archive=B/"priority-history"/("max-"+stamp)
 write(archive/"manifest-before.json",before)
 for r in after["rows"]:
  if r["variant"]=="qwen3.8-max--xhigh--claude":assert not Path(r["output"]).exists()
 launch=read(B/"launch.json",{})
 for name,cmd in [("controller","l3_leaderboard_batch.py controller"),("probes","l3_leaderboard_batch.py probes")]:
  pid=launch.get(name)
  if process_matches(pid,cmd):os.kill(pid,signal.SIGTERM)
 # Ensure scheduler won't allocate while the worker set and manifest change.
 with (B/"controller.lock").open("a") as ctl:
  fcntl.flock(ctl,fcntl.LOCK_EX)
  with (B/"manifest.lock").open("a") as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   assert read(B/"manifest.json")==before
   enabled={r["id"] for r in after["rows"] if r["enabled"]}
   to_stop=[]
   for r in before["rows"]:
    if r["id"] in enabled:continue
    p=Path(r["output"]);s=read(p/"state.json",{});env=read(p/"environment.json",{})
    if not s:continue
    wp=s.get("pid");ap=s.get("agent_pid")
    worker_live=process_matches(wp,"worker --id "+r["id"])
    agent_live=bool(env.get("container")) and process_matches(ap,"docker exec -i "+env["container"]+" ")
    if not worker_live and not agent_live:continue
    write(archive/(r["id"]+".json"),{"row":r,"state":s})
    if worker_live:
     assert os.getpgid(wp)==wp
     os.killpg(wp,signal.SIGTERM)
    to_stop.append((r,s,env))
   def stop(item):
    r,s,env=item;p=Path(r["output"]);name=env.get("container")
    if name:
     res=subprocess.run(["docker","inspect",name],capture_output=True,text=True,timeout=20)
     if res.returncode==0:
      info=json.loads(res.stdout)[0]
      assert any(Path(m["Source"]).resolve()==(p/"workspace").resolve() for m in info["Mounts"])
      subprocess.run(["docker","stop","--time","20",name],capture_output=True,check=True,timeout=40)
    gp=env.get("gateway_pid")
    if process_matches(gp,str(p/"model-requests.jsonl")):os.kill(gp,signal.SIGTERM)
    s.update(status="paused_by_user",paused_unix=time.time(),pause_reason="max-first table",prior_status=s.get("status"))
    write(p/"state.json",s)
    print("paused",r["id"],flush=True)
    return r["id"]
   with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:stopped=list(pool.map(stop,to_stop))
   write(archive/"retired-qwen-codex-rows.json",retired)
   after["priority_archive"]=str(archive);write(B/"manifest.json",after)
 # Replace evaluation controllers only; existing measurements keep their work.
 for name,cmd in [("collection","l3_matrix_collection.py"),("scoring","l3_matrix_scoring.py controller")]:
  pid=launch.get(name)
  if process_matches(pid,cmd):os.kill(pid,signal.SIGTERM)
 result={"active_trials":165,"paused_trials":240,"stopped":stopped,"qwen_fresh_trials":len(retired),
         "archive":str(archive),"targets":after["priority_policy"]["targets"]}
 write(B/"max-priority.json",result)
 return result
if __name__=="__main__":print(json.dumps(apply()))
