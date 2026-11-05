"""Public CLI: inventory, preflight, generation, evaluation and resumable runs."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tomllib
from harness.common.experiment_policy import (EFFORT, ATTEMPTS, GENERATION_TIMEOUT,
    GENERATION_TOTAL_TIMEOUT, EXECUTION_TIMEOUT, EVALUATION_TIMEOUT, validate_options)

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT/"data/3dbench/tasks"


def inventory(tasks=TASKS):
    for file in sorted(Path(tasks).glob("L[12]/*/*/task.toml")):
        m=tomllib.loads(file.read_text())
        yield dict(task_id=m["id"],level=m["level"],category=m["category"],title=m["title"],
                   route="native-and-legacy-detail" if m.get("harness_status") in {"mvp","implemented"} else "extension",
                   harness_status=m.get("harness_status"))


def all_tasks(tasks=TASKS):
    yield from inventory(tasks)
    from benchmark.l3 import inventory as l3_inventory
    yield from l3_inventory()


def l3_options(parser):
    parser.add_argument("--l3-engine", type=Path, help="Dedicated writable candidate UE engine copy")
    parser.add_argument("--l3-evaluator-engine", type=Path, help="Separate trusted evaluator UE engine copy")
    parser.add_argument("--gpu", type=int, help="L3 NVIDIA GPU index; defaults to L3_GPU or 0")


def main():
    p=argparse.ArgumentParser(description="3DBench L1/L2/L3: generation → Blender/UE execution → frozen evaluation")
    sub=p.add_subparsers(dest="command",required=True)
    listing=sub.add_parser("list");listing.add_argument("--level",type=int,choices=[1,2,3])
    listing.add_argument("--category");listing.add_argument("--tasks-root",type=Path,default=TASKS)
    doctor=sub.add_parser("doctor");doctor.add_argument("--blender",type=Path);doctor.add_argument("--env-file",type=Path,default=ROOT/".env")
    doctor.add_argument("--runtime",choices=["docker","local"],default="docker")
    doctor.add_argument("--resources-only",action="store_true")
    doctor.add_argument("--generator-runtime", choices=["local", "docker"])
    doctor.add_argument("--image", default="3dbench-l1-blender:mvp")
    doctor.add_argument("--level", type=int, nargs="+", choices=[1,2,3])
    doctor.add_argument("--verify-assets", action="store_true", help="Verify every external L3 asset hash")
    doctor.add_argument('--model',help='Check this model instead of OPENAI_MODEL from the selected env file')
    l3_options(doctor)
    assets=sub.add_parser("assets",help="Fetch or verify frozen L3 offline libraries")
    assets.add_argument("action",choices=["locks","fetch","verify"])
    assets.add_argument("--root",type=Path)
    assets.add_argument("--env-file",type=Path,default=ROOT/".env")
    exporting=sub.add_parser("export",help="Refresh campaign CSV and weighted L1/L2/L3 totals")
    exporting.add_argument("--output",type=Path,required=True)
    summary=sub.add_parser("summarize",help="Aggregate normalized L1/L2/L3 scores with the frozen category weights")
    summary.add_argument("--scores",type=Path,action="append",required=True)
    summary.add_argument("--identity",choices=["release","source"],default="release")
    summary.add_argument("--output",type=Path,required=True)
    for cmd in ["run","generate","evaluate"]:
        q=sub.add_parser(cmd)
        q.add_argument("--task",action="append",help="Repeat to select tasks. Omit with --all.")
        q.add_argument("--all",action="store_true")
        q.add_argument("--level",type=int,nargs="+",choices=[1,2,3]);q.add_argument("--category")
        q.add_argument("--tasks-root",type=Path,default=TASKS)
        q.add_argument("--output",type=Path,required=True,help="Fresh or resumable campaign directory")
        q.add_argument("--model",help="Tested model ID; defaults to OPENAI_MODEL")
        q.add_argument("--effort",choices=['max','xhigh','high'],help='Defaults to the model contract: Qwen xhigh, Gemini high, other listed models max')
        q.add_argument("--env-file",type=Path,default=ROOT/".env")
        q.add_argument("--blender",type=Path)
        q.add_argument("--runtime",choices=["docker","local"],default="docker")
        q.add_argument("--generator-runtime",choices=["docker","local"])
        q.add_argument("--image",default="3dbench-l1-blender:mvp")
        q.add_argument("--attempts",type=int,choices=[ATTEMPTS],default=ATTEMPTS)
        q.add_argument("--generation-timeout",type=float,default=GENERATION_TIMEOUT)
        q.add_argument("--generation-total-timeout",type=float,default=GENERATION_TOTAL_TIMEOUT,
                       help="Shared generation budget including retries and delivery validation")
        q.add_argument("--execution-timeout",type=float,default=EXECUTION_TIMEOUT)
        q.add_argument("--evaluation-timeout",type=float,default=EVALUATION_TIMEOUT)
        q.add_argument("--submission",type=Path,help="Trusted source-only submission for one task; no model generation")
        q.add_argument("--resume",action="store_true",help="Use bound cached stages; never regenerate accepted source")
        l3_options(q)
    args=p.parse_args()
    if args.command=="summarize":
        from benchmark.aggregation import normalized_rows,export
        results=export(normalized_rows(args.scores,args.identity),args.output)
        print(json.dumps([{k:r[k] for k in ["model","completed","expected","total_100","status"]} for r in results],ensure_ascii=False,indent=2))
        return 0
    if args.command=="list":
        rows=[r for r in all_tasks(args.tasks_root) if (not args.level or r["level"]==args.level) and (not args.category or r["category"]==args.category)]
        print(json.dumps(rows,ensure_ascii=False,indent=2));return 0
    if args.command=="export":
        from benchmark.export import export_scores
        from benchmark.engine import campaign_lock
        output=args.output.resolve()
        if not (output/"campaign.json").is_file():p.error("campaign.json missing")
        try:
            with campaign_lock(output):
                print(json.dumps(export_scores(output),indent=2))
        except (OSError,ValueError) as error:
            p.error(str(error))
        return 0
    os.environ["THREEDBENCH_ENV_FILE"]=str(args.env_file.resolve())
    if args.command=="assets":
        from benchmark.l3 import assets
        try:return assets(args)
        except ValueError as error:p.error(str(error))
    if args.blender:os.environ["THREEDBENCH_BLENDER"]=str(args.blender.resolve())
    from benchmark.resources import judge_settings
    settings = judge_settings()
    args.generator_runtime = args.generator_runtime or settings.get("GENERATOR_RUNTIME") or "docker"
    if args.command=="doctor":
        from benchmark.doctor import check
        levels=set(args.level or [1,2,3])
        result = check(args) if levels & {1,2} else {"errors":[],"api_calls":0}
        if 3 in levels:
            from benchmark.l3 import doctor as l3_doctor
            try:
                result["l3_runtime"]=l3_doctor(args)
                result["errors"].extend("L3: "+error for error in result["l3_runtime"]["errors"])
            except (OSError,ValueError,KeyError) as error:
                result["errors"].append("L3: "+str(error))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result["errors"] else 0
    if not args.task and not args.all:p.error("select --task or --all")
    if args.task and args.all:p.error("use --task or --all")
    if args.task:
        from benchmark.l3 import canonical_task_key,inventory as l3_inventory
        current={row['source_task_key']:row['task_id'] for row in l3_inventory()}
        try:
            args.task=[current[canonical_task_key(task)] if task.startswith('L3/') else task for task in args.task]
        except ValueError as error:
            p.error(str(error))
    from src.generator.harnesses import model_effort,validate_model_id
    args.model = args.model or settings.get('OPENAI_MODEL')
    try:validate_model_id(args.model)
    except ValueError as error:p.error(str(error))
    args.effort = args.effort or model_effort(args.model)
    options=vars(args).copy()
    try:validate_options(options)
    except ValueError as error:p.error(str(error))
    output=args.output.resolve();tasks=args.tasks_root.resolve()
    rows=[r for r in all_tasks(tasks) if (not args.task or r["task_id"] in args.task) and (not args.level or r["level"] in args.level) and (not args.category or r["category"]==args.category)]
    if not rows or args.task and {r["task_id"] for r in rows}!=set(args.task):p.error("unknown or excluded task selection")
    if args.submission and len(rows)!=1:p.error("--submission requires exactly one task")
    if args.submission and rows[0]["level"]==3:p.error("--submission is supported for L1/L2 only")
    if any(r["level"]==3 for r in rows) and tasks!=TASKS.resolve():p.error("L3 uses released packages; custom --tasks-root is supported for L1/L2 only")
    if output.exists() and any(output.iterdir()) and not args.resume:p.error("output exists; inspect it and use --resume")
    from benchmark.engine import campaign_lock
    try:
        with campaign_lock(output):
            return execute_campaign(args,p,options,output,tasks,rows)
    except ValueError as error:
        p.error(str(error))


def execute_campaign(args,p,options,output,tasks,rows):
    from benchmark.resources import prepare,judge_settings,blender_path
    os.environ.update(THREEDBENCH_RUN_ROOT=str(output),THREEDBENCH_RUNTIME=args.runtime,
                      THREEDBENCH_EXECUTION_TIMEOUT=str(args.execution_timeout),THREEDBENCH_IMAGE=args.image)
    prepare(output/"contracts")
    settings=judge_settings();model=args.model or settings.get("OPENAI_MODEL")
    if not model:p.error("set --model or OPENAI_MODEL")
    if Path(model).is_absolute() or ".." in Path(model).parts:
        p.error("model ID cannot be an absolute path or contain parent traversal")
    for key in ["tasks_root","env_file","blender","output","submission","l3_engine","l3_evaluator_engine"]:
        if options.get(key) is not None:options[key]=str(Path(options[key]).resolve())
    options["blender"] = str(blender_path())
    options["tasks_root"]=str(tasks)
    from benchmark.engine import initialize,generate,evaluate
    from orchestrator.tasks import write_json
    initialize(output,model,args.effort,tasks,options)
    if any(r["level"]==3 for r in rows):
        from benchmark.l3 import initialize as initialize_l3
        initialize_l3(output,model,args)
    statusfile=output/"benchmark.json";state=json.loads(statusfile.read_text()) if statusfile.exists() else {"model":model,"effort":args.effort,"tasks":{}}
    exitcode=0
    for row in rows:
        task=row["task_id"]
        try:
            if row["level"]==3:
                from benchmark.l3 import generate as generate_stage,evaluate as evaluate_stage
            else:
                generate_stage,evaluate_stage=generate,evaluate
            # Generation and judging are intentionally separate stages.
            if args.command in ["run","generate"]:
                result=generate_stage(task,output,model,options,args.submission)
                state["tasks"][task]={"status":"generated","generation":result["generation_run"]}
            if args.command in ["run","evaluate"]:
                result=evaluate_stage(task,output,model,options)
                state["tasks"][task]={"status":result.get("status"),"S_core":result.get("S_core"),
                    "report":str(output/"main_results"/model/Path(task).name/"report.json")}
            print(task,json.dumps(state["tasks"].get(task),ensure_ascii=False),flush=True)
        except Exception as error:
            from benchmark.resources import judge_key
            message=str(error)
            for key in [judge_key(),settings.get("OPENAI_API_KEY"),settings.get("OPENAI_DATA_API_KEY")]:
                if key:message=message.replace(key,"[redacted]")
            state["tasks"][task]={"status":"technical_failure","error":type(error).__name__+": "+message}
            print(task,state["tasks"][task]["error"],file=sys.stderr,flush=True);exitcode=2
        state["updated_utc"]=datetime.now(timezone.utc).isoformat()
        write_json(statusfile,state)
    from benchmark.export import export_scores
    export_scores(output)
    return exitcode


if __name__=="__main__":
    raise SystemExit(main())
