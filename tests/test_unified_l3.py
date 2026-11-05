"""Public L3 CLI integration; only paid generation and UE collection are replaced."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from benchmark import __main__ as cli
from benchmark import l3

TASK = "L3/Image2Environment/task_L3_Image2Environment_005"


@pytest.fixture
def unified(tmp_path, monkeypatch):
    for key in (
        "THREEDBENCH_ENV_FILE",
        "THREEDBENCH_RUN_ROOT",
        "THREEDBENCH_RUNTIME",
        "THREEDBENCH_EXECUTION_TIMEOUT",
        "THREEDBENCH_IMAGE",
        "THREEDBENCH_RESOURCE_ROOT",
    ):
        monkeypatch.setenv(key, os.environ.get(key, ""))
    env = tmp_path / "main.env"
    env.write_text(
        "OPENAI_MODEL=unified-fixture\nOPENAI_BASE_URL=https://generator.invalid/v1\n"
        "OPENAI_API_KEY=fixture-generator-token\nVLM_BASE_URL=https://judge.invalid/v1\n"
        "VLM_API_KEY=fixture-judge-token\nL3_CANDIDATE_ENGINE=candidate-engine\n"
        "L3_EVALUATOR_ENGINE=trusted-engine\nL3_UE_ROOT=original-engine\n"
    )
    output = tmp_path / "campaign"
    invoke = l3.invoke
    calls = []

    def stages(script, arguments, child_env, **kwargs):
        arguments = list(map(str, arguments))
        command = arguments[0]
        if script != "run.py" or command not in {"generate", "evaluate"}:
            return invoke(script, arguments, child_env, **kwargs)
        calls.append((command, arguments, child_env.copy()))
        row = l3.native_row(TASK, output)
        trial = Path(row["output"])
        if command == "generate":
            project = trial / "workspace/project"
            project.mkdir(parents=True, exist_ok=True)
            source = project / "scene.py"
            source.write_text("# source fixture, not a UE scene\n")
            l3.write_json(
                trial / "trial.json",
                {
                    "status": "generated_awaiting_independent_verification",
                    "model": row["model"],
                    "reasoning_effort": "max",
                },
            )
            l3.write_json(trial / "environment.json", {"task_key": row["task_key"]})
            l3.write_json(
                trial / "submission-manifest.json",
                {
                    "model": row["model"],
                    "effort": "max",
                    "harness": "codex",
                    "files": {
                        "scene.py": hashlib.sha256(source.read_bytes()).hexdigest()
                    },
                },
            )
        else:
            folder = output / "l3/evaluations/fresh" / row["id"]
            report = (
                folder / "review-v5" / row["task_key"] / row["model"] / "summary.json"
            )
            l3.write_json(
                report,
                {
                    "score_100": 73.5,
                    "protocol": "l3-perceptual-quality-v5",
                    "status": "measured",
                    "missing_axes": [],
                },
            )
            l3.write_json(
                folder / "verifier-result.json",
                {
                    "status": "measured",
                    "score_100": 73.5,
                    "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
                },
            )
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(l3, "invoke", stages)

    def run(command, *args):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "benchmark",
                command,
                "--env-file",
                str(env),
                "--output",
                str(output),
                "--task",
                TASK,
                *args,
            ],
        )
        return cli.main()

    return run, output, env, calls


def test_l3_runs_from_main_cli_and_exports_verified_normalized_score(unified):
    run, output, env, calls = unified
    assert run("run") == 0
    assert [c[0] for c in calls] == ["generate", "evaluate"]
    for command, arguments, child_env in calls:
        engine = "candidate-engine" if command == "generate" else "trusted-engine"
        assert arguments[arguments.index("--engine") + 1] == str(env.parent / engine)
        assert arguments[arguments.index("--task") + 1] == TASK
        provider = Path(child_env["L3_PROVIDER_DIR"]) / "openai.json"
        assert json.loads(provider.read_text())["api_key"] == "fixture-generator-token"
        assert provider.stat().st_mode & 0o777 == 0o600
    state = json.loads((output / "benchmark.json").read_text())
    assert state["tasks"][TASK]["status"] == "scored"
    report = json.loads(
        next((output / "main_results").rglob("report.json")).read_text()
    )
    assert report["S_core"] == 0.735 and report["score_100"] == 73.5
    totals = json.loads((output / "weighted-summary.json").read_text())["models"][0]
    assert totals["L3_completed"] == 1 and totals["total_100"] is None
    assert "fixture-generator-token" not in (output / "run-options.json").read_text()
    calls.clear()
    assert run("evaluate", "--resume") == 0
    assert (
        not calls
    )  # Actual frozen-source validation still runs in a child interpreter.


@pytest.mark.parametrize("tamper", ["source", "report", "normalized"])
def test_resume_rejects_changed_source_or_score_without_new_judging(unified, tamper):
    run, output, _, calls = unified
    assert run("run") == 0
    row = l3.native_row(TASK, output)
    if tamper == "source":
        target = Path(row["output"]) / "workspace/project/scene.py"
        target.write_text("# changed source\n")
    elif tamper == "report":
        target = next((output / "l3/evaluations/fresh").rglob("summary.json"))
        data = json.loads(target.read_text())
        data["score_100"] = 99
        target.write_text(json.dumps(data))
    else:
        target = next((output / "main_results").rglob("report.json"))
        data = json.loads(target.read_text())
        data["S_core"] = 0.99
        target.write_text(json.dumps(data))
    calls.clear()
    assert run("evaluate", "--resume") == 2
    assert not calls
    assert (
        json.loads((output / "benchmark.json").read_text())["tasks"][TASK]["status"]
        == "technical_failure"
    )
    assert json.loads((output / "summary.json").read_text())["completed"] == 0
    assert json.loads((output / "weighted-summary.json").read_text())["models"] == []


def test_changed_l3_engine_binding_is_rejected_before_stages(unified):
    run, output, _, calls = unified
    assert run("generate") == 0
    original = (output / "l3/unified-config.json").read_bytes()
    calls.clear()
    with pytest.raises(SystemExit) as error:
        run("evaluate", "--resume", "--l3-evaluator-engine", "/different/engine")
    assert error.value.code == 2 and not calls
    assert (output / "l3/unified-config.json").read_bytes() == original


def test_failed_evaluation_evidence_is_preserved_before_retry(unified):
    run, output, _, calls = unified
    assert run("generate") == 0
    row = l3.native_row(TASK, output)
    failed = output / "l3/evaluations/fresh" / row["id"]
    failed.mkdir(parents=True)
    (failed / "collection.log").write_text("retained failed UE collection\n")
    assert run("evaluate", "--resume") == 0
    retained = list((output / "l3/evaluations/failed").rglob("collection.log"))
    assert len(retained) == 1 and retained[0].read_text().startswith("retained failed")
    assert [c[0] for c in calls] == ["generate", "evaluate"]


def test_completed_collection_dispatches_scoring_resume_without_archiving(unified):
    run, output, _, calls = unified
    assert run("generate") == 0
    row = l3.native_row(TASK, output)
    folder = output / "l3/evaluations/fresh" / row["id"]
    l3.write_json(folder / "row.json", row)
    l3.write_json(
        folder / "runtime" / row["task_key"] / "run.json", {"status": "collected"}
    )
    assert run("evaluate", "--resume") == 0
    assert "--resume" in calls[-1][1]
    assert (folder / "row.json").is_file()
    assert not (output / "l3/evaluations/failed").exists()


def test_resume_rejects_edited_native_manifest_before_stages(unified):
    run, output, _, calls = unified
    assert run("generate") == 0
    file = output / "l3/manifest.json"
    manifest = json.loads(file.read_text())
    manifest["rows"][0]["model"] = "changed-model"
    file.write_text(json.dumps(manifest))
    calls.clear()
    with pytest.raises(SystemExit) as error:
        run("generate", "--resume")
    assert error.value.code == 2 and not calls


def test_main_l3_doctor_reports_missing_host_without_blender_or_secret_output(tmp_path):
    env = tmp_path / "empty.env"
    env.write_text("")
    child = {"PATH": "", "LANG": "C.UTF-8"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmark",
            "doctor",
            "--level",
            "3",
            "--env-file",
            str(env),
        ],
        cwd=l3.ROOT,
        env=child,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2 and "Traceback" not in result.stderr
    data = json.loads(result.stdout)
    assert data["l3_runtime"]["release"]["tasks"] == 15
    assert data["errors"] and all("Blender" not in e for e in data["errors"])
    assert data["api_calls"] == 0 and not data["l3_runtime"]["ue_launched"]


def test_main_assets_uses_env_relative_root(tmp_path, monkeypatch):
    env = tmp_path / "main.env"
    env.write_text("L3_ASSET_ROOT=libraries\n")
    monkeypatch.setenv("THREEDBENCH_ENV_FILE", str(env))
    calls = []
    monkeypatch.setattr(
        l3, "invoke", lambda script, args, child: calls.append((script, args))
    )
    from argparse import Namespace

    assert l3.assets(Namespace(action="verify", root=None)) == 0
    assert calls == [
        ("prepare_assets.py", ["verify", "--root", tmp_path / "libraries"])
    ]


def test_resource_doctor_ignores_unconfigured_runtime_values(tmp_path):
    env = tmp_path / "main.env"
    env.write_text("L3_GPU=not-configured\nL3_UE_ROOT=missing-engine\n")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmark",
            "doctor",
            "--level",
            "3",
            "--resources-only",
            "--env-file",
            str(env),
        ],
        cwd=l3.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["l3_runtime"]["release"]["tasks"] == 15


def test_asset_cli_override_is_relative_to_working_directory(tmp_path, monkeypatch):
    from argparse import Namespace

    config = tmp_path / "settings/main.env"
    config.parent.mkdir()
    config.write_text("L3_ASSET_ROOT=ignored-env-root\n")
    monkeypatch.setenv("THREEDBENCH_ENV_FILE", str(config))
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(l3, "invoke", lambda script, args, env: calls.append(args))
    assert l3.assets(Namespace(action="verify", root=Path("cli-assets"))) == 0
    assert calls == [["verify", "--root", tmp_path / "cli-assets"]]


def test_export_revalidates_l3_native_report(unified, monkeypatch):
    run, output, _, calls = unified
    assert run("run") == 0
    native = next((output / "l3/evaluations/fresh").rglob("summary.json"))
    raw = json.loads(native.read_text())
    raw["score_100"] = 100
    native.write_text(json.dumps(raw))
    calls.clear()
    monkeypatch.setattr(sys, "argv", ["benchmark", "export", "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2 and not calls
