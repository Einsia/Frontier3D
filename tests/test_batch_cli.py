"""Exercise every active task through the real batch CLI without paid stages.

Only generation/evaluation stage bodies are doubles. Selection, policy binding,
resource relocation, campaign locks, state persistence, errors and CSV/level
aggregation use the release implementation. These are orchestration tests,
not model-quality or all-task Blender integration evidence.
"""

import csv
import json
import os
import sys
from pathlib import Path

import pytest

from benchmark import __main__ as cli
from benchmark import engine, l3
from benchmark.resources import ROOT


@pytest.fixture
def batch(tmp_path, monkeypatch):
    # The CLI intentionally sets process-global runtime bindings. Restore them
    # after each in-process invocation group so other tests keep their own roots.
    for name in (
        "THREEDBENCH_ENV_FILE",
        "THREEDBENCH_BLENDER",
        "THREEDBENCH_RUN_ROOT",
        "THREEDBENCH_RUNTIME",
        "THREEDBENCH_EXECUTION_TIMEOUT",
        "THREEDBENCH_IMAGE",
        "THREEDBENCH_RESOURCE_ROOT",
    ):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    env = tmp_path / "offline.env"
    env.write_text("OPENAI_MODEL=batch-test-double\nVLM_MODEL=gpt-6-astra\n")
    output = tmp_path / "campaign"
    calls = []
    active = [r["task_id"] for r in cli.all_tasks()]

    def generate(task, root, model, options, submission=None):
        calls.append(("generate", task))
        return {"generation_run": str(root / "jobs" / Path(task).name / "generation")}

    def evaluate(task, root, model, options):
        calls.append(("evaluate", task))
        report = {
            "task_id": task,
            "model": model,
            "status": "scored",
            "score_valid": True,
            "S_core": 0.5,
            "test_only": "stage double",
        }
        engine.write_json(
            root / "main_results" / model / Path(task).name / "report.json", report
        )
        return report

    monkeypatch.setattr(engine, "generate", generate)
    monkeypatch.setattr(engine, "evaluate", evaluate)
    monkeypatch.setattr(l3, "generate", generate)
    monkeypatch.setattr(l3, "evaluate", evaluate)

    def run(command, *selection):
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
                *selection,
            ],
        )
        return cli.main()

    return run, output, calls, active


@pytest.mark.parametrize("command", ["run", "generate", "evaluate"])
def test_all_active_tasks_are_dispatched_once_and_exported(batch, command):
    run, output, calls, active = batch
    assert run(command, "--all") == 0
    expected = [
        (stage, task)
        for task in active
        for stage in (["generate", "evaluate"] if command == "run" else [command])
    ]
    assert calls == expected
    state = json.loads((output / "benchmark.json").read_text())
    assert set(state["tasks"]) == set(active)
    with (output / "scores.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == (0 if command == "generate" else len(active))
    campaign = json.loads((output / "campaign.json").read_text())
    assert campaign["task_release_version"] == "release145-no-codeedit-20261104"
    assert campaign["generation_policy"]["effort"] == "max"
    if command != "generate":
        totals = json.loads((output / "weighted-summary.json").read_text())["models"]
        assert len(totals) == 1
        assert totals[0]["L1_completed"] == 65 and totals[0]["L2_completed"] == 65
        assert totals[0]["L3_completed"] == 15 and totals[0]["total_100"] == 50.0


@pytest.mark.parametrize(
    "selection",
    [
        ["--all", "--level", "1"],
        ["--all", "--level", "2"],
        ["--all", "--level", "3"],
        ["--all", "--level", "1", "2"],
        ["--all", "--category", "Reference2Scene-RealPhoto"],
        [
            "--task",
            "L1/Text2Code/task_L1_Text2Code_001",
            "--task",
            "L2/Brief2Scene/task_L2_Brief2Scene_001",
        ],
    ],
)
def test_filters_dispatch_only_the_selected_population(batch, selection):
    run, _, calls, _ = batch
    assert run("generate", *selection) == 0
    rows = list(cli.all_tasks())
    if "--level" in selection:
        levels = {int(v) for v in selection[selection.index("--level") + 1:]}
        expected = [r["task_id"] for r in rows if r["level"] in levels]
    elif "--category" in selection:
        category = selection[selection.index("--category") + 1]
        expected = [r["task_id"] for r in rows if r["category"] == category]
    else:
        expected = [r["task_id"] for r in rows if r["task_id"] in selection]
    assert calls == [("generate", task) for task in expected]


def test_one_task_failure_continues_batch_and_resume_reuses_campaign(
    batch, monkeypatch
):
    run, output, calls, active = batch
    original = engine.evaluate
    failed = active[len(active) // 2]

    def fail_one(task, *args):
        if task == failed:
            raise RuntimeError("Injected measurement failure; no model call")
        return original(task, *args)

    monkeypatch.setattr(engine, "evaluate", fail_one)
    assert run("run", "--all") == 2
    state = json.loads((output / "benchmark.json").read_text())
    assert len(state["tasks"]) == len(active)
    assert state["tasks"][failed]["status"] == "technical_failure"
    assert state["tasks"][active[-1]]["status"] == "scored"
    assert (
        json.loads((output / "summary.json").read_text())["completed"]
        == len(active) - 1
    )
    identity = (output / "campaign.json").read_bytes()
    with pytest.raises(SystemExit) as error:
        run("evaluate", "--all")
    assert error.value.code == 2
    monkeypatch.setattr(engine, "evaluate", original)
    calls.clear()
    assert run("evaluate", "--all", "--resume") == 0
    assert (output / "campaign.json").read_bytes() == identity
    assert calls == [("evaluate", task) for task in active]
    assert json.loads((output / "summary.json").read_text())["completed"] == len(active)
    calls.clear()
    with pytest.raises(SystemExit) as error:
        run("evaluate", "--all", "--resume", "--model", "different-model")
    assert error.value.code == 2 and calls == []
    assert (output / "campaign.json").read_bytes() == identity


def test_real_engine_reuses_verified_source_and_final_report(tmp_path, monkeypatch):
    """No generation/judging allowed on completed cache hits, even if CLI dispatches."""
    task = "L1/Text2Code/task_L1_Text2Code_001"
    folder = tmp_path / "jobs" / Path(task).name
    source = folder / "source"
    source.mkdir(parents=True)
    (source / "solution.py").write_text("# retained source\n")
    origin = folder / "generation"
    origin.mkdir()
    engine.write_json(
        origin / "generation.json", {"test_only": "retained cache fixture"}
    )
    generated = {
        "submission": str(source),
        "generation_run": str(origin),
        "source_sha256": {"solution.py": engine.sha256(source / "solution.py")},
        "generation_sha256": engine.sha256(origin / "generation.json"),
    }
    engine.write_json(folder / "generate-result.json", generated)
    report = {
        "task_id": task,
        "model": "cache-fixture",
        "status": "scored",
        "S_core": 0.5,
        "score_valid": True,
    }
    engine.write_json(
        tmp_path / "main_results/cache-fixture" / Path(task).name / "report.json",
        report,
    )
    from orchestrator import generator

    engine.write_json(engine.report_receipt(tmp_path, task), {
        'report_sha256': engine.sha256(tmp_path / 'main_results/cache-fixture' / Path(task).name / 'report.json'),
        'generation_sha256': engine.sha256(folder / 'generate-result.json'),
    })

    def forbidden(*args, **kwargs):
        pytest.fail(
            "Completed cache hit must not generate or invoke a new native evaluation"
        )

    monkeypatch.setattr(generator, "generate", forbidden)
    monkeypatch.setattr(engine, "generation_validator", forbidden)
    assert (
        engine.generate(
            task,
            tmp_path,
            "cache-fixture",
            {"tasks_root": str(ROOT / "data/3dbench/tasks")},
        )
        == generated
    )
    assert engine.evaluate(task, tmp_path, "cache-fixture", {}) == report
    (source / "solution.py").write_text("# tampered source\n")
    with pytest.raises(ValueError, match="source changed"):
        engine.evaluate(task, tmp_path, "cache-fixture", {})
