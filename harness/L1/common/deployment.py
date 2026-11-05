"""Read-only L1 policy drift audit and explicit, receipt-backed config copying.

Task packages are runtime authority. Only harness.toml is synchronized; this
tool never copies hidden answers, task inputs, EvalSpec or arbitrary trees.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from src.generator.task_adapter import load_benchmark_task

from .attempt_log import sha256, sha256_bytes, write_json_atomic
from .config import load_config, parse_config
from .configuration import implementation_binding, task_spec, validate_task_config

DEPLOYMENT_PROTOCOL = "l1-configuration-deployment-v1"
TASK_IDS = ("L1/Text2Code", "L1/Image2Code", "L1/CodeEdit")


def _path(root: Path, relative: str) -> Path:
    root = root.expanduser().absolute()
    path = root / relative
    for candidate in path.parents:
        # Intermediate directory symlinks are not safe deployment destinations.
        if candidate.is_symlink():
            raise ValueError("Configuration deployment may not traverse symlinks")
    if path.is_symlink():
        raise ValueError("Configuration deployment may not replace a symlink")
    return path


def _paths(task_id: str, tasks_root: Path, templates_root: Path) -> tuple[Path, Path]:
    if task_id not in TASK_IDS:
        raise ValueError("Deployment supports only the three declared L1 task IDs")
    return (_path(tasks_root, f"{task_id}/harness/harness.toml"),
            _path(templates_root, f"{task_id.split('/')[1]}/harness.toml"))


def _diff(left: Any, right: Any, prefix="") -> list[dict[str, Any]]:
    if isinstance(left, dict) and isinstance(right, dict):
        result = []
        for key in sorted(set(left) | set(right)):
            result.extend(_diff(left.get(key), right.get(key), f"{prefix}/{key}"))
        return result
    return [] if left == right and type(left) is type(right) else [{"field": prefix, "task": left, "template": right}]


def audit(tasks_root: Path, templates_root: Path, task_ids=TASK_IDS) -> dict[str, Any]:
    reports = []
    for task_id in task_ids:
        item: dict[str, Any] = {"task_id": task_id, "status": "invalid"}
        try:
            task_path, template_path = _paths(task_id, tasks_root, templates_root)
            item.update(task_path=str(task_path), template_path=str(template_path))
            task = load_benchmark_task(task_id, tasks_root)
            spec_path, spec = task_spec(task)
            task_config = load_config(task_path)
            template = load_config(template_path)
            validate_task_config(task, task_config, spec)
            differences = _diff(task_config.effective(), template.effective())
            item.update(
                status="in_sync" if task_config.file_sha256 == template.file_sha256
                else "policy_drift" if differences else "formatting_drift",
                task_sha256=task_config.file_sha256, template_sha256=template.file_sha256,
                task_effective_sha256=task_config.effective_digest,
                template_effective_sha256=template.effective_digest,
                task_version=task_config.harness_version, template_version=template.harness_version,
                spec_path=str(spec_path), spec_sha256=spec.digest, differences=differences,
            )
            try:
                validate_task_config(task, template, spec)
                item["template_contract_valid"] = True
            except ValueError as error:
                item.update(template_contract_valid=False, template_contract_error=str(error))
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            item.update(error_type=type(error).__name__, reason=str(error))
        reports.append(item)
    return {"protocol": DEPLOYMENT_PROTOCOL, "runtime_authority": "task_package",
            "status": "in_sync" if reports and all(r["status"] == "in_sync" for r in reports) else "drift_or_invalid",
            "tasks": reports}


def synchronize(
    task_id: str, tasks_root: Path, templates_root: Path, *, direction: str,
    expected_target_sha256: str, receipts_dir: Path,
) -> dict[str, Any]:
    """Copy one explicitly selected config after validating its exact bytes.

    An existing target requires its reviewed hash (or 'missing' for bootstrap).
    Keep a durable backup and intent receipt before replacing only that file.
    """
    if direction not in {"task-to-template", "template-to-task"}:
        raise ValueError("Explicit synchronization direction is required")
    task_path, template_path = _paths(task_id, tasks_root, templates_root)
    source, target = (task_path, template_path) if direction == "task-to-template" else (template_path, task_path)
    source_bytes = source.read_bytes()
    proposed = parse_config(source_bytes, source_path=source)
    task = load_benchmark_task(task_id, tasks_root)
    spec_path, spec = task_spec(task)
    validate_task_config(task, proposed, spec)
    previous = target.read_bytes() if target.is_file() else None
    old_hash = sha256_bytes(previous) if previous is not None else "missing"
    if old_hash != expected_target_sha256:
        raise ValueError("Target hash differs from the reviewed expected hash; no files changed")
    receipt_root = receipts_dir.expanduser().absolute()
    for protected in (tasks_root.expanduser().resolve(), templates_root.expanduser().resolve()):
        if receipt_root.resolve().is_relative_to(protected):
            raise ValueError("Deployment receipts must be outside task and template roots")
    receipt_root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=f"{task_id.replace('/', '__')}__", dir=receipt_root))
    backup = directory / "previous.harness.toml"
    if previous is not None:
        with backup.open("xb") as stream:
            stream.write(previous)
            stream.flush()
            os.fsync(stream.fileno())
    (directory / "proposed.harness.toml").write_bytes(source_bytes)
    receipt = {
        "protocol": DEPLOYMENT_PROTOCOL, "task_id": task_id, "direction": direction,
        "source": str(source), "target": str(target), "previous_sha256": old_hash,
        "new_sha256": sha256_bytes(source_bytes), "effective_sha256": proposed.effective_digest,
        "harness_version": proposed.harness_version, "spec_sha256": spec.digest,
        "spec_file_sha256": sha256(spec_path), "task_manifest_sha256": sha256(task.root / "task.toml"),
        "implementation": implementation_binding(), "created_at_ns": time.time_ns(),
        "backup_path": str(backup) if previous is not None else None,
        "receipt_path": str(directory / "receipt.json"), "status": "prepared",
        "scope": "one harness.toml; EvalSpec, instructions, inputs and reference assets untouched",
    }
    write_json_atomic(directory / "receipt.json", receipt)
    temporary: Path | None = None
    try:
        # Recheck immediately before replacement; this is not a lock against
        # hostile concurrent filesystem writers (G08 remains a separate task).
        _paths(task_id, tasks_root, templates_root)
        current = sha256(target) if target.is_file() else "missing"
        if current != old_hash or sha256(source) != receipt["new_sha256"]:
            raise ValueError("Source or target changed after preparation")
        if sha256(spec_path) != receipt["spec_file_sha256"] or sha256(task.root / "task.toml") != receipt["task_manifest_sha256"]:
            raise ValueError("Task contract changed after preparation")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".harness-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(source_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        receipt["replacement_performed"] = True
        if sha256(target) != receipt["new_sha256"]:
            raise ValueError("Target changed after replacement")
        receipt.update(status="applied", target_sha256=receipt["new_sha256"], finished_at_ns=time.time_ns())
        write_json_atomic(directory / "receipt.json", receipt)
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        receipt.update(status="failed_or_interrupted", error_type=type(error).__name__, finished_at_ns=time.time_ns())
        write_json_atomic(directory / "receipt.json", receipt)
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit/synchronize L1 harness policy; runtime authority is the task package")
    parser.add_argument("action", choices=("check", "sync-template", "deploy"))
    parser.add_argument("--task", choices=TASK_IDS)
    parser.add_argument("--tasks-root", type=Path, default=Path("data/3dbench/task"))
    parser.add_argument("--templates-root", type=Path, default=Path("harness/L1"))
    parser.add_argument("--expected-target-sha256", help="Reviewed current target hash, or 'missing' for a new file")
    parser.add_argument("--receipts-dir", type=Path, default=Path("data/task_runs/l1_config_deployments"))
    parser.add_argument("--report", type=Path, help="Optional audit JSON outside task/template roots")
    args = parser.parse_args()
    try:
        report = args.report.expanduser().absolute() if args.report is not None else None
        if report is not None:
            if any(report.resolve().is_relative_to(root.expanduser().resolve()) for root in (args.tasks_root, args.templates_root)):
                raise ValueError("Audit reports must be outside task/template roots")
            if report.is_symlink() or (report.exists() and not report.is_file()):
                raise ValueError("Audit report must be a regular file, not a symlink or directory")
        if args.action == "check":
            result = audit(args.tasks_root, args.templates_root, (args.task,) if args.task else TASK_IDS)
            code = 0 if result["status"] == "in_sync" else 1
        else:
            if args.task is None or args.expected_target_sha256 is None:
                raise ValueError("Mutation requires --task and --expected-target-sha256")
            result = synchronize(
                args.task, args.tasks_root, args.templates_root,
                direction="task-to-template" if args.action == "sync-template" else "template-to-task",
                expected_target_sha256=args.expected_target_sha256, receipts_dir=args.receipts_dir,
            )
            code = 0
        if report is not None:
            report.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(report, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "error", "error_type": type(error).__name__, "reason": str(error)}, ensure_ascii=False))
        return 1
