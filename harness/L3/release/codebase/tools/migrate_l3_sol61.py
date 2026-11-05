"""Migrate Sol model configurations while preserving existing trial records."""
import copy,fcntl,os,signal,subprocess,time
from pathlib import Path
from tools.l3_leaderboard_batch import B,R,read,write,variant,process_matches
OLD="gpt-6-sol"
NEW="gpt-6.1-sol"

def replacement(manifest):
    rows=manifest["rows"]
    old=[r for r in rows if r["model"]==OLD]
    if not old:
        assert len([r for r in rows if r["model"]==NEW])==60
        return copy.deepcopy(manifest),[]
    assert len(old)==60 and not any(r["model"]==NEW for r in rows)
    assert {(r["task_key"],r["effort"]) for r in old}=={(k,e) for k in {r["task_key"] for r in old} for e in ["medium","high","xhigh","max"]}
    out=copy.deepcopy(manifest)
    fresh=[]
    for r in old:
        v=variant(NEW,r["effort"])
        fresh.append({"id":r["task_key"]+"--"+v,"task_key":r["task_key"],
          "task_path":r["task_path"],"task_manifest_sha256":r["task_manifest_sha256"],
          "model":NEW,"harness":"codex","group":"openai","effort":r["effort"],
          "variant":v,"status":"queued","reuse_source":None,
          "output":str(B/"runs"/r["task_key"]/v)})
    out["rows"]=[r for r in out["rows"] if r["model"]!=OLD]+fresh
    assert len(out["rows"])==360 and len({r["id"] for r in out["rows"]})==360
    out["retired_models"]=sorted(set(out.get("retired_models",[]))|{OLD})
    out["scope"]="GPT-6 Astra, GPT-6 Luna, GPT-6.1 Sol; Opus5.5, GLM5.3Flash, KimiK3, DeepSeekV4.1Flash, Qwen3.8Max"
    out["updated_unix"]=time.time()
    return out,old

def migrate():
    before=read(B/"manifest.json");after,old=replacement(before)
    if not old:return {"already_migrated":True}
    for row in after["rows"]:
        if row["model"]==NEW:assert not Path(row["output"]).exists(),"New model must use a clean workspace"
    stamp=str(time.time_ns());archive=B/"model-migrations"/("sol61-"+stamp)
    write(archive/"manifest-before.json",before)
    launch=read(B/"launch.json",{});pid=launch.get("controller")
    if process_matches(pid,"l3_leaderboard_batch.py controller"):
        os.kill(pid,signal.SIGTERM)
    with (B/"controller.lock").open("a") as ctl:
        fcntl.flock(ctl,fcntl.LOCK_EX)
        with (B/"manifest.lock").open("a") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            current=read(B/"manifest.json")
            assert current==before,"Manifest changed concurrently"
            stopped=[]
            for row in old:
                p=Path(row["output"]);s=read(p/"state.json",{});env=read(p/"environment.json",{})
                if s:write(archive/(row["id"]+".json"),{"row":row,"state":s})
                wp=s.get("pid");ap=s.get("agent_pid")
                worker_live=process_matches(wp,"worker --id "+row["id"])
                agent_live=bool(env.get("container")) and process_matches(ap,"docker exec -i "+env["container"]+" ")
                if not worker_live and not agent_live:continue
                if worker_live:
                    assert os.getpgid(wp)==wp,"Worker must own its process group"
                    os.killpg(wp,signal.SIGTERM)
                name=env.get("container")
                if name:
                    inspected=subprocess.run(["docker","inspect",name],capture_output=True,text=True,timeout=20)
                    if inspected.returncode==0:
                        import json
                        info=json.loads(inspected.stdout)[0]
                        assert any(Path(m["Source"]).resolve()==(p/"workspace").resolve() for m in info["Mounts"])
                        subprocess.run(["docker","stop","--time","20",name],capture_output=True,check=True,timeout=40)
                gp=env.get("gateway_pid")
                if process_matches(gp,str(p/"model-requests.jsonl")):os.kill(gp,signal.SIGTERM)
                s.update(status="superseded",superseded_by=NEW,superseded_unix=time.time())
                write(p/"state.json",s);stopped.append(row["id"])
            write(archive/"retired-rows.json",old)
            after["retired_rows_archive"]=str(archive/"retired-rows.json")
            write(B/"manifest.json",after)
            result={"model":NEW,"efforts":["medium","high","xhigh","max"],"new_sol_trials":60,
             "total":360,"reused":sum(r["status"]=="reused" for r in after["rows"]),
             "new_generation":sum(r["status"]!="reused" for r in after["rows"]),
             "stopped":stopped,"archive":str(archive)}
            write(B/"sol61-migration.json",result)
            return result
if __name__=="__main__":
    import json
    print(json.dumps(migrate()))
