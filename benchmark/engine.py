"""Generation and frozen legacy-detail evaluation in a standalone campaign."""
from pathlib import Path
from dataclasses import replace
from contextlib import contextmanager
import fcntl
import json
import os
import shutil
import tempfile
import time

from orchestrator.tasks import load_task, sha256, write_json, regular
from orchestrator.runner import snapshot, generation_validator
from harness.common.experiment_policy import GENERATION_TOTAL_TIMEOUT, binding, validate_options
from benchmark.resources import ROOT, resource, blender_path, env_path, judge_model, judge_settings


@contextmanager
def campaign_lock(root):
    """One process owns generation and score writes for a campaign."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".campaign.lock").open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Campaign is owned by another process") from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read(path):
    return json.loads(Path(path).read_text())


def task_bindings(task):
    names = {'task.toml', task.manifest['instruction']}
    names.update(str(Path(task.manifest['environment']) / name) for name in task.manifest['environment_files'])
    harness = task.root / task.manifest['harness']
    names.update(str(p.relative_to(task.root)) for p in harness.rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc', '.pyo'})
    return {name: sha256(regular(task.root, name)) for name in sorted(names)}


def report_receipt(root, task_id):
    return root / 'jobs' / Path(task_id).name / 'evaluate-result.json'


def verify_report(root, task_id, model):
    receipt = read(report_receipt(root, task_id))
    report = root / 'main_results' / model / Path(task_id).name / 'report.json'
    if receipt['report_sha256'] != sha256(report):
        raise ValueError('Accepted evaluation report changed')
    generation = root / 'jobs' / Path(task_id).name / 'generate-result.json'
    if receipt['generation_sha256'] != sha256(generation):
        raise ValueError('Accepted evaluation generation binding changed')
    result = read(report)
    if result.get('task_id') != task_id or result.get('model') != model:
        raise ValueError('Accepted evaluation identity changed')
    return result


def _links(root, tasks):
    link = root / "inputs/data/3dbench/tasks"
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.exists():
        link.symlink_to(tasks, target_is_directory=True)
    if link.resolve() != tasks.resolve():
        raise ValueError("Campaign task package changed")


def initialize(root, model, effort, tasks, options):
    from src.generator.harnesses import validate_model_id
    validate_model_id(model)
    validate_options(options)
    root.mkdir(parents=True, exist_ok=True)
    _links(root, tasks)
    settings = judge_settings()
    campaign = {
        "models":[model], "reasoning_effort":effort, "frozen":str(root / "inputs"),
        "task_release_version":"release145-no-codeedit-20261104",
        "aggregation_policy_sha256":sha256(ROOT/"configs/release/aggregation-policy.json"),
        "task_source":str(tasks), "scoring_version":"legacy-detail-20261019-v2",
        "provider_transport":settings.get("VLM_BASE_URL") or settings.get("OPENAI_BASE_URL", ""),
        "detail_measurement_profile":"detail-only-v1",
        "detail_variant_policy":"full-frozen-population-v1",
        "detail_invocation_profile":"detail-single-round-cached-v1",
        "detail_variant_workers":1, "judge_model":judge_model(),
        "generation_policy":binding(options),
        "execution":{k:options.get(k) for k in ("runtime","image","generator_runtime","blender")},
    }
    from src.generator.harnesses import CLAUDE_DOCKER_IMAGE, NATIVE_DOCKER_IMAGE, generator_harness, POLICY_PATH, REGISTRY_PATH
    selected_harness=generator_harness(model)
    campaign['model_contract_sha256']=sha256(REGISTRY_PATH)
    campaign['harness_policy_sha256']=sha256(POLICY_PATH)
    campaign['execution']['generator_harness']=selected_harness
    if selected_harness!='codex':
        campaign['execution']['generator_image']=(settings.get('GENERATOR_CLAUDE_DOCKER_IMAGE') or CLAUDE_DOCKER_IMAGE) if selected_harness=='claude-code' else settings.get('GENERATOR_NATIVE_DOCKER_IMAGE') or NATIVE_DOCKER_IMAGE
    file = root / "campaign.json"
    if file.exists() and read(file) != campaign:
        raise ValueError("Campaign configuration changed; choose a new output directory")
    if not file.exists():
        write_json(file, campaign)
    linear = root / "linear_config"
    if not linear.exists():
        shutil.copytree(resource("linear_config"), linear)
    write_json(root / "run-options.json", options)


def generate(task_id, root, model, options, submission=None):
    from orchestrator.generator import generate as call_generator
    from src.generator.client import GeneratorConfig
    task = load_task(task_id, Path(options["tasks_root"]), require_harness=False)
    folder = root / "jobs" / task.root.name
    folder.mkdir(parents=True, exist_ok=True)
    resultpath = folder / "generate-result.json"
    if resultpath.exists():
        result = read(resultpath)
        verify_generated(result)
        return result
    origin = folder / "generation"
    origin.mkdir(exist_ok=True)
    inputs = task_bindings(task)
    inputpath = origin / 'task-bindings.json'
    if inputpath.exists() and read(inputpath) != inputs:
        raise ValueError('Accepted task inputs or harness changed')
    if not inputpath.exists():
        write_json(inputpath, inputs)
    manifest = dict(task_id=task_id, model=model, model_call=submission is None,
                    provided_source=submission is not None, reasoning_effort=options["effort"], status="running",
                    attempts={}, instruction_sha256=sha256(task.root/"instruction.md"))
    from src.generator.harnesses import generator_harness
    if submission is None and generator_harness(model) != "codex":
        manifest["harness"] = generator_harness(model)
    if (task.root/"harness/eval_spec.json").is_file():
        from src.evaluator.spec import EvalSpec
        manifest["spec_sha256"] = EvalSpec.load(task.root/"harness/eval_spec.json").digest
    write_json(origin/"run.json", manifest)
    validate = generation_validator(task, origin, manifest, blender=blender_path(),
        runtime=options["runtime"], image=options["image"], seed=0,
        attempt_timeout=options["execution_timeout"])
    budget = options.get("generation_total_timeout", GENERATION_TOTAL_TIMEOUT)
    budgetpath = origin/"generation-budget.json"
    prior = read(budgetpath) if budgetpath.exists() else {}
    consumed = prior.get("consumed_seconds", 0.)
    if prior.get("status") == "running":
        consumed += max(0., time.time()-prior["started_epoch"])
    retained = read(origin / 'generation.json').get('attempts', []) if (origin / 'generation.json').exists() else []
    accepted = bool(retained and retained[-1].get('status') == 'success')
    if consumed >= budget and not accepted:
        raise TimeoutError("Shared generation budget exhausted; retain this campaign")
    started = time.monotonic()
    write_json(budgetpath, {"limit_seconds":budget,"consumed_seconds":consumed,
                           "started_epoch":time.time(),"status":"running"})
    deadline = started + budget-consumed
    try:
        if submission is None:
            config = GeneratorConfig.from_env(env_path(),model=model)
            config = replace(config, model=model, reasoning_effort=options["effort"])
            source, history = call_generator(task, origin, deadline=deadline,
                timeout=options["generation_timeout"], attempts=options["attempts"],
                runtime=options["generator_runtime"], config=config, env_file=env_path(),
                validate_submission=validate, resume=(origin/"generation.json").exists())
        else:
            source = origin/"provided-source"
            snapshot(Path(submission), source, exclude=("scene.blend","scene.glb","main.png","alternate.png","novel.png"))
            work = origin/"provided-validation"
            work.mkdir()
            history = validate(source, work, deadline)
            if not history or history[-1]["status"] != "success":
                raise ValueError("Provided source did not produce the task deliverables")
            write_json(origin/"generation.json", {"attempts":[], "source":"provided by caller; no model generation"})
    finally:
        write_json(budgetpath, {"limit_seconds":budget,
            "consumed_seconds":consumed+time.monotonic()-started,"status":"stopped"})
    if task_bindings(task) != inputs:
        raise ValueError('Task inputs or harness changed during generation')
    frozen = origin/"source"
    # Publish atomically so an interrupted copy cannot block a successful resume.
    with tempfile.TemporaryDirectory(prefix='source-staging-', dir=origin) as tmp:
        staging = Path(tmp) / 'source'
        hashes = snapshot(source, staging)
        if frozen.exists():
            from orchestrator.runner import tree_files
            if set(tree_files(frozen)) != set(hashes) or any(sha256(regular(frozen, n)) != h for n, h in hashes.items()):
                raise ValueError('Accepted generated source changed')
        else:
            staging.rename(frozen)
    if submission is None and history:
        manifest['attempts']['baseline'] = history[-1].get('validation_attempts', [])
    manifest.update(status="generated", phase="completed", source_sha256=hashes,
                    submission=str(frozen), generation_source=str(origin))
    write_json(origin/"run.json", manifest)
    result = dict(status="completed", submission=str(frozen), source_sha256=hashes,
                  generation_run=str(origin), generation_sha256=sha256(origin/"generation.json"),
                  provided_source=submission is not None,
                  task_id=task_id, task_root=str(task.root), task_sha256=inputs)
    write_json(resultpath, result)
    return result


def verify_generated(result):
    if 'task_sha256' in result:
        task = load_task(result['task_id'], Path(result['task_root']).parents[2], require_harness=False)
        if task_bindings(task) != result['task_sha256']:
            raise ValueError('Accepted task inputs or harness changed')
        from orchestrator.runner import tree_files
        if set(tree_files(Path(result['submission']))) != set(result['source_sha256']):
            raise ValueError('Accepted generated source changed')
    for name, digest in result["source_sha256"].items():
        if sha256(regular(Path(result["submission"]),name)) != digest:
            raise ValueError("Accepted generated source changed")
    if sha256(regular(Path(result["generation_run"]),'generation.json')) != result["generation_sha256"]:
        raise ValueError("Accepted generation history changed")


def evaluate(task_id, root, model, options):
    folder = root/"jobs"/Path(task_id).name
    generated = read(folder/"generate-result.json")
    verify_generated(generated)
    reportpath = root/"main_results"/model/Path(task_id).name/"report.json"
    if report_receipt(root, task_id).exists():
        report = verify_report(root, task_id, model)
        if report.get("S_core") is not None:
            return report
    task = load_task(task_id, Path(options["tasks_root"]), require_harness=False)
    bindings = {"instruction.md":sha256(task.root/"instruction.md")}
    job = dict(campaign=str(root), model=model, effort=options["effort"], task_id=task_id,
               tasks_root=options["tasks_root"], bindings=bindings,
               judge_transport=read(root/"campaign.json")["provider_transport"])
    if task.manifest.get("harness_status") not in {"mvp","implemented"}:
        from tools.experiment_additions import evaluate as addition
        result = addition(job, folder, generated)
        source_report = Path(result["report"])
        if sha256(source_report) != result["report_sha256"]:
            raise ValueError("Extension report changed before export")
        write_json(reportpath, read(source_report))
    else:
        os.environ["THREEDBENCH_DEFER_JUDGES"] = "1"
        nativepath = folder/"native-result.json"
        try:
            if nativepath.exists():
                native = read(nativepath)
            else:
                if task.manifest["level"] == 1:
                    from orchestrator.runner import run_case
                else:
                    from orchestrator.l2_runner import run_case
                native = run_case(task_id, submission=Path(generated["submission"]),
                    tasks_root=Path(options["tasks_root"]), output_root=folder/"native",
                    blender=blender_path(), runtime=options["runtime"], image=options["image"],
                    attempts=options["attempts"], timeout=options["evaluation_timeout"],
                    attempt_timeout=options["execution_timeout"],
                    reproduction_timeout=options["execution_timeout"])
                write_json(nativepath, native)
        finally:
            os.environ.pop("THREEDBENCH_DEFER_JUDGES", None)
        run = Path(native["run_dir"])
        origin = Path(generated["generation_run"])
        retained = read(run/"run.json")
        if not retained.get("instruction_sha256"):
            retained["instruction_sha256"] = bindings["instruction.md"]
        if generated.get("provided_source"):
            retained["provided_source"] = True
        write_json(run/"run.json", retained)
        row = dict(task_id=task_id, category=task.manifest["category"],
                   status=native["status"], run_dir=str(run), spec_sha256=native["spec_sha256"],
                   instruction_sha256=bindings["instruction.md"],
                   previous_row={"source_provenance":{"source_run_dir":str(origin),
                                 "source_run_sha256":sha256(origin/"run.json")}})
        batchpath = root/model/"batch.json"
        batch = read(batchpath) if batchpath.exists() else {"model":model,"cases":[]}
        batch["cases"] = [r for r in batch["cases"] if r["task_id"] != task_id] + [row]
        write_json(batchpath, batch)
        from tools.watch_effort_historical import worker
        worker(root, task_id)
    report = read(reportpath)
    if report.get("S_core") is None:
        raise ValueError("Evaluation incomplete; measurements were retained for inspection")
    write_json(report_receipt(root, task_id), {
        'report_sha256': sha256(reportpath),
        'generation_sha256': sha256(folder / 'generate-result.json'),
    })
    return report
