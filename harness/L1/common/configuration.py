"""L1 task-policy contract and effective configuration provenance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import tomllib

from src.evaluator.spec import EvalSpec
from src.generator.task_adapter import BenchmarkTask

from .attempt_log import sha256, sha256_bytes, write_json_atomic
from .config import HarnessConfig

CONFIGURATION_PROTOCOL = "l1-configuration-v1"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
_BINDING_KEYS = ("task_id", "task_manifest_sha256", "instruction_sha256", "config_file_sha256",
                 "config_effective_sha256", "spec_sha256", "spec_file_sha256", "implementation_sha256")


def task_spec(task: BenchmarkTask) -> tuple[Path, EvalSpec]:
    paths = [task.root / "harness" / f"eval_spec{suffix}" for suffix in (".json", ".toml")]
    present = [path for path in paths if path.is_file()]
    if len(present) != 1:
        raise ValueError(f"Exactly one frozen L1 EvalSpec is required for {task.task_id}")
    spec = EvalSpec.load(present[0])
    if spec.profile != "L1":
        raise ValueError("L1 harness requires an L1 EvalSpec")
    return present[0], spec


def validate_task_config(task: BenchmarkTask, config: HarnessConfig, spec: EvalSpec) -> None:
    if task.level != 1 or config.task_id != task.task_id or spec.profile != "L1":
        raise ValueError("L1 task, harness config and EvalSpec profile must agree")
    if tuple(p.as_posix() for p in task.environment_files) != config.environment_files:
        raise ValueError("Harness environment_files must match task manifest environment_files")
    if tuple(spec.required_artifacts) != config.output_files:
        raise ValueError("Harness output_files must match EvalSpec required_artifacts")
    required_entrypoint = "fixed_solution" if task.task_id == "L1/CodeEdit" else "declared_python"
    if config.entrypoint_policy != required_entrypoint:
        raise ValueError(f"{task.task_id} requires entrypoint_policy={required_entrypoint}")


def implementation_binding() -> dict[str, Any]:
    paths = set((PROJECT_ROOT / "harness/L1").rglob("*.py"))
    paths.update((PROJECT_ROOT / "src/evaluator").glob("l1*.py"))
    paths.update(PROJECT_ROOT / name for name in (
        "src/evaluator/metrics.py", "src/evaluator/spec.py", "src/evaluator/reporting.py", "src/evaluator/cli.py",
        "src/generator/client.py", "src/generator/task_adapter.py", "src/render/blender_runner.py",
    ))
    files = {path.relative_to(PROJECT_ROOT).as_posix(): sha256(path) for path in sorted(paths)}
    return {
        "files": files,
        "sha256": sha256_bytes(json.dumps(files, sort_keys=True).encode()),
        "scope": "listed L1 harness/evaluator and shared execution sources; not a dependency or sandbox proof",
    }


def enforce_binding(actual: dict[str, Any], expected: dict[str, Any] | None) -> None:
    if expected is None:
        return
    changed = [key for key in _BINDING_KEYS if key in expected and actual.get(key) != expected[key]]
    if changed:
        raise ValueError(f"L1 configuration changed between phases: {', '.join(changed)}")


def record_binding(record: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """A successful phase cannot omit its configuration provenance."""
    actual = record.get("configuration")
    if (not isinstance(actual, dict) or actual.get("protocol") != CONFIGURATION_PROTOCOL
            or any(not isinstance(actual.get(key), str) or not actual[key] for key in _BINDING_KEYS)):
        raise ValueError("Missing or incomplete L1 configuration record")
    enforce_binding(actual, expected)
    return actual


def configuration_snapshot(
    task: BenchmarkTask, config: HarnessConfig, spec_path: Path, spec: EvalSpec, *,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_task_config(task, config, spec)
    manifest_bytes = (task.root / "task.toml").read_bytes()
    manifest = tomllib.loads(manifest_bytes.decode())
    if type(manifest.get("version")) is not int or manifest["version"] != 1 or manifest.get("id") != task.task_id:
        raise ValueError("Task manifest version/id changed during configuration loading")
    if not config.source_path or sha256(Path(config.source_path)) != config.file_sha256:
        raise ValueError("Harness config bytes changed during configuration loading")
    # A second spec check detects normal concurrent edits, not malicious races.
    if EvalSpec.load(spec_path).digest != spec.digest:
        raise ValueError("EvalSpec changed during configuration loading")
    implementation = implementation_binding()
    default_path = task.root / "harness/harness.toml"
    snapshot = {
        "protocol": CONFIGURATION_PROTOCOL, "task_id": task.task_id,
        "task_manifest_version": manifest["version"],
        "task_manifest_path": str((task.root / "task.toml").resolve()),
        "task_manifest_sha256": sha256_bytes(manifest_bytes),
        "instruction_path": str(task.instruction_path.resolve()),
        "instruction_sha256": sha256(task.instruction_path),
        "config_path": config.source_path,
        "config_source": "task_package" if Path(config.source_path) == default_path.resolve() else "explicit_override",
        "config_file_sha256": config.file_sha256, "config_declared_sha256": config.digest,
        "config_effective_sha256": config.effective_digest,
        "declared": config.source, "effective": config.effective(),
        "harness_version": config.harness_version,
        "spec_path": str(spec_path.resolve()), "spec_sha256": spec.digest,
        "spec_file_sha256": sha256(spec_path), "spec_version": spec.to_dict()["version"],
        "implementation_sha256": implementation["sha256"], "implementation": implementation,
    }
    enforce_binding(snapshot, expected)
    return snapshot


def save_configuration(directory: Path, snapshot: dict[str, Any], spec: EvalSpec) -> Path:
    # Archive the exact hashed source bytes as well as normalized/effective
    # values. Reject an ordinary concurrent edit between validation and copy.
    sources = {}
    for name, path_key, digest_key in (
        ("harness.toml", "config_path", "config_file_sha256"),
        ("eval_spec.source", "spec_path", "spec_file_sha256"),
        ("task.toml", "task_manifest_path", "task_manifest_sha256"),
        ("instruction.md", "instruction_path", "instruction_sha256"),
    ):
        content = Path(snapshot[path_key]).read_bytes()
        if sha256_bytes(content) != snapshot[digest_key]:
            raise ValueError(f"Configuration source changed before freezing: {name}")
        sources[name] = content
    directory.mkdir(parents=True, exist_ok=False)
    for name, content in sources.items():
        (directory / name).write_bytes(content)
    write_json_atomic(directory / "configuration.json", snapshot)
    frozen = directory / "eval_spec.json"
    write_json_atomic(frozen, spec.to_dict())
    return frozen
