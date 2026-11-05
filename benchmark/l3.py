"""UE stages behind the public benchmark CLI; isolate the nested source layout."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

from benchmark.resources import ROOT, env_path, judge_settings
from orchestrator.tasks import write_json

RELEASE = ROOT / "harness/L3/release"
PATH_SETTINGS = (
    "L3_UE_ROOT",
    "L3_NATIVE_CLI",
    "L3_ASSET_ROOT",
    "L3_PROVIDER_DIR",
    "L3_MATRIX_JUDGE_PROVIDER",
    "L3_CANDIDATE_ENGINE",
    "L3_EVALUATOR_ENGINE",
)


def inventory():
    for row in json.loads((RELEASE / "task-index.json").read_text()):
        yield {
            "task_id": row["release_task_id"],
            "source_task_key": row["task_key"],
            "level": 3,
            "category": row["category"],
            "title": row["title"],
            "route": "ue-v5",
        }


def canonical_task_key(task):
    """Resolve current IDs and the explicitly retained legacy identities only."""
    for row in json.loads((RELEASE / "task-index.json").read_text()):
        identities = {row["task_key"], row["release_task_id"], Path(row["release_task_id"]).name}
        identities.update(row.get("legacy_task_ids", []))
        if task in identities:
            return row["task_key"]
    raise ValueError("Unknown L3 task identity: " + task)


def path_setting(value):
    path = Path(value).expanduser()
    return (
        (env_path().parent / path).resolve()
        if not path.is_absolute()
        else path.resolve()
    )


def runtime(args):
    settings = judge_settings()
    candidate = Path(args.l3_engine).expanduser().resolve() if args.l3_engine else None
    evaluator = (
        Path(args.l3_evaluator_engine).expanduser().resolve()
        if args.l3_evaluator_engine
        else None
    )
    candidate = candidate or (
        path_setting(settings["L3_CANDIDATE_ENGINE"])
        if settings.get("L3_CANDIDATE_ENGINE")
        else None
    )
    evaluator = evaluator or (
        path_setting(settings["L3_EVALUATOR_ENGINE"])
        if settings.get("L3_EVALUATOR_ENGINE")
        else None
    )
    gpu = args.gpu if args.gpu is not None else int(settings.get("L3_GPU") or "0")
    if gpu < 0:
        raise ValueError("L3 GPU index must be nonnegative")
    return Namespace(
        candidate=candidate,
        evaluator=evaluator,
        gpu=gpu,
    )


def private_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # O_TRUNC preserves mode on existing files; chmod also repairs old modes.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream)
    path.chmod(0o600)


def environment(private_root):
    """Honor explicit private JSON providers, otherwise reuse the main env file."""
    settings = judge_settings()
    env = dict(os.environ)
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_root.chmod(0o700)
    for key, value in settings.items():
        if key.startswith("L3_") and value:
            env[key] = str(path_setting(value)) if key in PATH_SETTINGS else value
    from dotenv import dotenv_values

    file = {k: v for k, v in dotenv_values(env_path()).items() if v is not None}
    gen = (
        file
        if any(file.get(k) for k in ("OPENAI_API_KEY", "OPENAI_DATA_API_KEY"))
        else settings
    )
    judge = (
        file
        if any(
            file.get(k)
            for k in ("VLM_API_KEY", "OPENAI_API_KEY", "OPENAI_DATA_API_KEY")
        )
        else settings
    )
    if not settings.get("L3_PROVIDER_DIR"):
        providers = private_root / "providers"
        private_json(
            providers / "openai.json",
            {
                "base_url": settings.get("OPENAI_BASE_URL", ""),
                "api_key": gen.get("OPENAI_DATA_API_KEY")
                or gen.get("OPENAI_API_KEY", ""),
            },
        )
        env["L3_PROVIDER_DIR"] = str(providers)
    if not settings.get("L3_MATRIX_JUDGE_PROVIDER"):
        provider = private_root / "judge.json"
        private_json(
            provider,
            {
                "base_url": settings.get("VLM_BASE_URL")
                or settings.get("OPENAI_BASE_URL", ""),
                "api_key": judge.get("VLM_API_KEY")
                or judge.get("OPENAI_DATA_API_KEY")
                or judge.get("OPENAI_API_KEY", ""),
            },
        )
        env["L3_MATRIX_JUDGE_PROVIDER"] = str(provider)
    return env


def invoke(script, arguments, env, *, capture=False):
    return subprocess.run(
        [sys.executable, str(RELEASE / script), *map(str, arguments)],
        env=env,
        check=True,
        text=True,
        capture_output=capture,
    )


def doctor(args):
    if args.resources_only:
        checked = invoke(
            "run.py", ["doctor", "--resources-only"], dict(os.environ), capture=True
        )
        return json.loads(checked.stdout)
    setup = runtime(args)
    with tempfile.TemporaryDirectory(prefix="3dbench-l3-providers-") as tmp:
        env = environment(Path(tmp))
        from src.generator.harnesses import native_harness

        env["L3_GENERATOR_HARNESS"] = native_harness(getattr(args,"model",None) or judge_settings().get("OPENAI_MODEL", ""))
        command = [sys.executable, str(RELEASE / "run.py"), "doctor"]
        if args.resources_only:
            command += ["--resources-only"]
        else:
            if setup.candidate:
                command += ["--engine", str(setup.candidate)]
            if args.verify_assets:
                command += ["--verify-assets"]
        completed = subprocess.run(
            command, env=env, capture_output=True, text=True, check=False
        )
        if completed.returncode not in (0, 2):
            raise ValueError(
                "L3 preflight failed; check the installed Python dependencies"
            )
        result = json.loads(completed.stdout)
        if not args.resources_only:
            from benchmark.doctor import configured

            if not configured(getattr(args,'model',None) or judge_settings().get("OPENAI_MODEL")):
                result["errors"].append("Set OPENAI_MODEL to the tested model ID")
            if not setup.evaluator:
                result["errors"].append(
                    "Set L3_EVALUATOR_ENGINE or --l3-evaluator-engine"
                )
            else:
                from harness.L3.release.engine_checks import engine_errors

                result["errors"].extend(engine_errors(setup.evaluator, "L3 evaluator"))
                if not os.access(setup.evaluator, os.W_OK):
                    result["errors"].append("L3 evaluator engine must be writable")
            if setup.candidate and setup.candidate == setup.evaluator:
                result["errors"].append(
                    "L3 candidate and evaluator engine copies must differ"
                )
            if setup.evaluator and env.get("L3_UE_ROOT") == str(setup.evaluator):
                result["errors"].append(
                    "L3 evaluator engine must differ from L3_UE_ROOT"
                )
            settings = judge_settings()
            from src.generator.harnesses import CLAUDE_VERSION, generator_harness
            if generator_harness(getattr(args,"model",None) or settings.get("OPENAI_MODEL", "")) == "claude-code":
                result["generator_harness"] = "claude-code"
                try:
                    native=Path(env["L3_NATIVE_CLI"])
                    package=json.loads((native/'@anthropic-ai/claude-code/package.json').read_text())
                    if package['version']!=CLAUDE_VERSION or not os.access(native/'.bin/claude',os.X_OK):
                        raise ValueError('Claude Code installation differs')
                except (KeyError,OSError,ValueError):
                    result["errors"].append("Doubao L3 needs Claude Code "+CLAUDE_VERSION+" in L3_NATIVE_CLI")
            if (
                settings.get("VLM_MODEL", "gpt-6-astra") != "gpt-6-astra"
                or settings.get("VLM_REASONING_EFFORT", "medium") != "medium"
            ):
                result["errors"].append(
                    "L3 judge requires gpt-6-astra with medium effort"
                )
        return result


def initialize(output, model, args):
    setup = runtime(args)
    campaign = output / "l3"
    env = environment(output / ".private/l3")
    binding = {
        "model": model,
        "effort": args.effort,
        "gpu": setup.gpu,
        "candidate_engine": str(setup.candidate) if setup.candidate else None,
        "evaluator_engine": str(setup.evaluator) if setup.evaluator else None,
        "runtime": {k: env.get(k) for k in (*PATH_SETTINGS[:3], "L3_UE_IMAGE")},
        "protocol": "l3-perceptual-quality-v5",
    }
    from src.generator.harnesses import generator_harness, native_harness, POLICY_PATH, REGISTRY_PATH
    selected_harness = native_harness(model)
    binding['model_contract_sha256']=hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest()
    binding['harness_policy_sha256']=hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()
    if generator_harness(model) != "codex":
        binding["harness"] = selected_harness
    bound = campaign / "unified-config.json"
    if not (campaign / "manifest.json").exists():
        invoke(
            "run.py",
            [
                "init",
                "--campaign",
                campaign,
                "--model",
                model,
                "--effort",
                args.effort,
                "--gpu",
                setup.gpu,
                *(["--harness", selected_harness] if selected_harness != "codex" else []),
            ],
            env,
        )
    binding["manifest_sha256"] = hashlib.sha256(
        (campaign / "manifest.json").read_bytes()
    ).hexdigest()
    if bound.exists() and json.loads(bound.read_text()) != binding:
        raise ValueError(
            "L3 campaign configuration changed; choose a new output directory"
        )
    if not bound.exists():
        write_json(bound, binding)
    return setup, env


def native_row(task, output):
    rows = json.loads((output / "l3/manifest.json").read_text())["rows"]
    key = canonical_task_key(task)
    return next(row for row in rows if row["task_key"] == key)


def validate_source(task, output, env):
    try:
        invoke(
            "run.py",
            ["validate", "--campaign", output / "l3", "--task", task],
            env,
            capture=True,
        )
    except subprocess.CalledProcessError as error:
        raise ValueError(
            "L3 frozen source is invalid or changed; inspect the retained submission"
        ) from error


def generate(task, output, model, options, submission=None):
    if submission:
        raise ValueError("--submission is supported for L1/L2 only")
    args = Namespace(**options)
    setup, env = initialize(output, model, args)
    if not setup.candidate:
        raise ValueError("Set L3_CANDIDATE_ENGINE or --l3-engine")
    invoke(
        "run.py",
        [
            "generate",
            "--campaign",
            output / "l3",
            "--task",
            task,
            "--engine",
            setup.candidate,
            "--gpu",
            setup.gpu,
        ],
        env,
    )
    validate_source(task, output, env)
    return {"generation_run": native_row(task, output)["output"]}


def evaluate(task, output, model, options):
    setup, env = initialize(output, model, Namespace(**options))
    if not setup.evaluator:
        raise ValueError("Set L3_EVALUATOR_ENGINE or --l3-evaluator-engine")
    if setup.evaluator == setup.candidate or str(setup.evaluator) == env.get(
        "L3_UE_ROOT"
    ):
        raise ValueError("L3 evaluator requires a separate trusted engine copy")
    row = native_row(task, output)
    folder = output / "l3/evaluations/fresh" / row["id"]
    result = folder / "verifier-result.json"
    if not result.exists():
        collected = folder / "runtime" / row["task_key"] / "run.json"
        resume_collection = (
            (folder / "row.json").is_file()
            and collected.is_file()
            and json.loads(collected.read_text()).get("status") == "collected"
        )
        if folder.exists() and not resume_collection:
            # Keep failed collection/judge evidence before retrying a fresh verifier.
            failed = output / "l3/evaluations/failed"
            failed.mkdir(parents=True, exist_ok=True)
            folder.rename(
                failed
                / (row["id"] + "-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f"))
            )
        invoke(
            "run.py",
            [
                "evaluate",
                "--campaign",
                output / "l3",
                "--task",
                task,
                "--engine",
                setup.evaluator,
                "--gpu",
                setup.gpu,
                "--provider",
                env["L3_MATRIX_JUDGE_PROVIDER"],
                *(["--resume"] if resume_collection else []),
            ],
            env,
        )
    validate_source(task, output, env)
    record = json.loads(result.read_text())
    report = folder / "review-v5" / row["task_key"] / model / "summary.json"
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    raw = json.loads(report.read_text())
    score = raw.get("score_100")
    if (
        record.get("status") != "measured"
        or record.get("report_sha256") != digest
        or raw.get("protocol") != "l3-perceptual-quality-v5"
        or raw.get("status") != "measured"
        or raw.get("missing_axes")
        or type(score) not in (int, float)
        or not 0 <= score <= 100
        or record.get("score_100") != score
    ):
        raise ValueError("L3 cached score is incomplete or changed")
    normalized = {
        "task_id": task,
        "model": model,
        "status": "scored",
        "score_valid": True,
        "S_core": score / 100,
        "score_100": score,
        "method_version": "l3-perceptual-quality-v5",
        "native_report": str(report),
        "native_report_sha256": digest,
    }
    target = output / "main_results" / model / Path(task).name / "report.json"
    if target.exists() and json.loads(target.read_text()) != normalized:
        raise ValueError("L3 normalized report changed")
    write_json(target, normalized)
    return normalized


def assets(args):
    settings = judge_settings()
    root = (
        Path(args.root).expanduser().resolve()
        if args.root
        else settings.get("L3_ASSET_ROOT")
    )
    command = [args.action]
    if args.action != "locks":
        if not root:
            raise ValueError("Set L3_ASSET_ROOT or --root")
        command += ["--root", path_setting(root)]
    invoke("prepare_assets.py", command, dict(os.environ))
    return 0


def validate_report(report, output):
    """Exports must not promote a stale or edited normalized L3 score."""
    row = native_row(report["task_id"], output)
    native = (
        output
        / "l3/evaluations/fresh"
        / row["id"]
        / "review-v5"
        / row["task_key"]
        / report["model"]
        / "summary.json"
    )
    digest = hashlib.sha256(native.read_bytes()).hexdigest()
    raw = json.loads(native.read_text())
    score = raw.get("score_100")
    record = json.loads((native.parents[3] / "verifier-result.json").read_text())
    if (
        digest != report.get("native_report_sha256")
        or digest != record.get("report_sha256")
        or raw.get("protocol") != "l3-perceptual-quality-v5"
        or raw.get("status") != "measured"
        or raw.get("missing_axes")
        or type(score) not in (int, float)
        or not 0 <= score <= 100
        or raw.get("score_100") != report.get("score_100")
        or record.get("status") != "measured"
        or record.get("score_100") != report.get("score_100")
        or report.get("S_core") != raw["score_100"] / 100
    ):
        raise ValueError("L3 report or score changed; inspect retained evidence")
    validate_source(report["task_id"], output, dict(os.environ))
