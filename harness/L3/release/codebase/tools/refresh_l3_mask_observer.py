"""Refresh only the instance-ID pass of a failed verifier, preserving all evidence."""
import argparse,fcntl,hashlib,json,shutil,subprocess,time,sys,contextlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from harness.L3.MinecraftVillage.protocol import read_json,write_json,tree_digest,digest
from tools.prepare_l3_trial import assert_engine_available

def nonmask_source(text):
    text=text.replace('#include "Components/TextRenderComponent.h"\n','')
    text=text.replace('#include "Components/MeshComponent.h"\n','')
    a=text.index('    if(Op==TEXT("instance_masks"))')
    b=text.index('    if(Op==TEXT("ray"))',a)
    return text[:a]+text[b:]

def refresh(run,engine,gpu,lock_held=False):
    engine=engine.resolve()
    lock=ROOT/"data/l3/locks"/("engine-"+hashlib.sha256(str(engine).encode()).hexdigest()[:16]+".lock")
    with (contextlib.nullcontext() if lock_held else lock.open("a")) as handle:
        if not lock_held:fcntl.flock(handle,fcntl.LOCK_EX)
        assert_engine_available(engine)
        r=read_json(run/"run.json");project=run/"workspace/project"
        if r["status"]!="failed":raise ValueError("Refresh requires failed verifier")
        if tree_digest(project)!=r["verification_source_sha256"]:raise ValueError("Verifier source changed")
        if tree_digest(Path(r["source"]))!=r["source_sha256"]:raise ValueError("Candidate changed")
        target=project/"Plugins/BenchRuntime/Source/BenchRuntime/Private/BenchObserver.cpp"
        master=ROOT/"ue5/BenchRuntime/Source/BenchRuntime/Private/BenchObserver.cpp"
        if nonmask_source(target.read_text())!=nonmask_source(master.read_text()):
            raise ValueError("Observer changes extend beyond ID render pass")
        info=json.loads(subprocess.check_output(["docker","inspect",r["container"]],text=True))[0]
        if info["State"]["Running"]:raise ValueError("Verifier is already running")
        stamp=str(time.time_ns());archive=run/"mask-render-recovery"/stamp;archive.mkdir(parents=True)
        shutil.copy2(run/"run.json",archive/"run.json")
        shutil.copy2(target,archive/"BenchObserver.cpp")
        shutil.copy2(master,target)
        command=list(r["command"])
        for index,value in enumerate(command):
            if value.startswith("type=bind,src=") and "/engines/" in value:
                command[index]="type=bind,src="+str(engine)+",dst="+value.split(",dst=",1)[1]
        command[command.index("--gpus")+1]="device="+str(gpu)
        if command!=r["command"]:
            subprocess.run(["docker","rm",r["container"]],check=True,capture_output=True)
            subprocess.run(command,check=True,capture_output=True)
            subprocess.run(["docker","stop","--time","10",r["container"]],check=True,capture_output=True)
            r["command"]=command
        if tree_digest(project/"Plugins/BenchRuntime")!=tree_digest(ROOT/"ue5/BenchRuntime"):
            raise ValueError("Unreviewed observer differences")
        try:
            subprocess.run(["docker","start",r["container"]],check=True,capture_output=True)
            with (archive/"build.log").open("w") as log:
                subprocess.run(["docker","exec",r["container"],"python3","/opt/l3-public/ue.py","build","/workspace/project",
                    "--output","/workspace/build-mask-"+stamp,"--jobs","16","--blueprints"],stdout=log,stderr=log,check=True)
        finally:subprocess.run(["docker","stop","--time","10",r["container"]],capture_output=True)
        evidence=run/"workspace/episodes/reference"
        if evidence.exists():shutil.move(evidence,archive/"reference")
        for name in ["reference.json","reference-view.json","mask-palette.json"]:
            if (run/name).exists():shutil.copy2(run/name,archive/name)
        r["episodes"].pop("reference",None)
        r["observer_sha256"]=tree_digest(project/"Plugins/BenchRuntime")
        r["verification_source_sha256"]=tree_digest(project)
        r["mask_observer_recovery"]={"archive":str(archive),"scope":"ID-pass mesh material and text overlay coverage only; RGB, geometry, and interactions unchanged",
            "retained_episode_observer_sha256":read_json(archive/"run.json")["observer_sha256"]}
        write_json(run/"run.json",r)
        write_json(archive/"result.json",{"status":"ready_to_resume","observer_sha256":r["observer_sha256"]})
        print("Mask verifier rebuilt; reference capture queued for recollection",flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--run",type=Path,required=True);p.add_argument("--engine",type=Path,required=True);p.add_argument("--gpu",type=int,required=True)
    a=p.parse_args();refresh(a.run.resolve(),a.engine.resolve(),a.gpu)
