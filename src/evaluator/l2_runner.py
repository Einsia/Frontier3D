"""Collect independent L2 scene evidence and calculate the fixed L2 score."""

# External evidence type errors are normalized into validation failures.
# ruff: noqa: TRY004

from __future__ import annotations

import hashlib
import json
import math
import platform
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import PIL
from PIL import Image

from .l2 import score_l2
from .metrics import validate_metrics
from .reporting import efficiency_metrics, human_score, vlm_score
from .spec import EvalSpec, contained_path

WORKER = Path(__file__).resolve().with_name("l2_blender.py")


class InspectionTimeout(RuntimeError):
    """A real worker deadline, distinct from candidate or scoring failures."""


def artifact_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _record_digest(record: dict[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key != "record_sha256"}
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _inspect(blender: Path, scene: Path, directory: Path, timeout: float) -> dict[str, Any]:
    from harness.L2.executor import run_process, sandbox_command
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "facts.json"
    command = sandbox_command(blender, scene.parent, WORKER,
        ["--scene", "/work/"+scene.name, "--output", "/audit/facts.json"],
        readonly=True, output=directory)
    process = run_process(command, cwd=scene.parent, logs=directory / "logs", timeout=timeout)
    if process.status in {"timeout", "budget_exhausted"}:
        raise InspectionTimeout(f"Scene inspection timed out after {timeout}s")
    if process.status != "success":
        raise RuntimeError(f"Scene inspection failed: {process.status}; see {directory / 'logs'}")
    result = json.loads(output.read_text())
    if not isinstance(result, dict) or not isinstance(result.get("scene"), dict):
        raise ValueError("Invalid L2 Blender evidence")
    return result


def _load_image(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        return {
            "size": [int(image.width), int(image.height)],
            "mode": image.mode,
            "format": image.format,
        }


def _load_artifact(path: Path) -> dict[str, Any] | None:
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".exr"}:
        return _load_image(path)
    elif path.suffix.lower() == ".py":
        compile(path.read_bytes(), str(path), "exec")
    elif path.suffix.lower() == ".json":
        json.loads(path.read_text(encoding="utf-8"))
    else:
        path.read_text(encoding="utf-8")
    return None


def _harness_record(record, spec, hashes, **context):
    from .l2_record import validate_record
    return validate_record(record, spec, hashes, **context)


def evaluate_l2_submission(
    spec: EvalSpec,
    submission: Path,
    blender: Path,
    *,
    assets_root: Path,
    harness_record: dict[str, Any] | None = None,
    timeout: float = 900.0,
    task_id: str = "L2/unknown",
    task_type: str | None = None,
    trial_id: str = "0",
    board: str | None = None,
    record_path: Path | None = None,
    trusted_runs_root: Path | None = None,
    harness_config: Path | None = None,
) -> dict[str, Any]:
    """Inspect a submission without executing candidate code.

    A trusted runner must provide execution and integrity facts. This function
    deliberately leaves those gates failed when the record is absent or stale.
    """
    if spec.profile != "L2":
        raise ValueError("evaluate_l2_submission requires an L2 EvalSpec")
    validate_metrics(spec)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive finite number")
    if board is not None and board not in {"single-shot", "auto-refinement"}:
        raise ValueError("Unknown leaderboard protocol")
    started = time.monotonic()
    submission = submission.expanduser().resolve()
    assets_root = assets_root.expanduser().resolve()
    blender = blender.expanduser().resolve()
    if not submission.is_dir():
        raise ValueError(f"Submission directory does not exist: {submission}")
    evaluation_root = contained_path(submission, "evaluation")
    evaluation_root.mkdir(exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="l2-", dir=evaluation_root))
    evidence: dict[str, Any] = {"artifacts": {}, "harness": {}}
    errors: list[str] = []
    timed_out = False
    hashes: dict[str, str] = {}
    paths: dict[str, Path] = {}
    for name in spec.required_artifacts:
        artifact: dict[str, Any] = {"loadable": False}
        evidence["artifacts"][name] = artifact
        try:
            path = contained_path(submission, name)
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError("Missing or empty artifact")
            hashes[name] = artifact_sha256(path)
            paths[name] = path
            artifact.update(
                sha256=hashes[name], bytes=path.stat().st_size, path=str(path)
            )
        except (OSError, ValueError) as error:
            artifact["error"] = str(error)
    for index, (name, path) in enumerate(paths.items()):
        artifact = evidence["artifacts"][name]
        try:
            if path.suffix.lower() == ".blend":
                result = _inspect(blender, path, output / f"artifact-{index}", timeout)
                artifact["loadable"] = result["scene"].get("has_real_geometry") is True
                artifact["scene"] = result["scene"]
                if name == spec.scene:
                    evidence.update(result)
            else:
                properties = _load_artifact(path)
                artifact["loadable"] = True
                if properties is not None:
                    artifact.update(properties)
        except (OSError, ValueError, RuntimeError, SyntaxError) as error:
            timed_out = timed_out or isinstance(error, InspectionTimeout)
            artifact["error"] = str(error)
            errors.append(f"{name}: {error}")
    for label, relative in (
        ("reference", spec.reference_scene),
        ("baseline", spec.baseline_scene),
    ):
        if relative is None:
            continue
        try:
            path = contained_path(assets_root, relative)
            result = _inspect(blender, path, output / label, timeout)
            evidence[label] = result["scene"]
            evidence[f"{label}_sha256"] = artifact_sha256(path)
        except (OSError, ValueError, RuntimeError) as error:
            timed_out = timed_out or isinstance(error, InspectionTimeout)
            errors.append(f"{label}: {error}")
    evidence["reference_images"] = {}
    for view, relative in spec.reference_images.items():
        try:
            path = contained_path(assets_root, relative)
            _load_image(path)
            evidence["reference_images"][view] = {
                "path": str(path),
                "sha256": artifact_sha256(path),
            }
        except (OSError, ValueError) as error:
            errors.append(f"reference image {view}: {error}")
    if harness_record is not None:
        try:
            evidence["harness"] = _harness_record(harness_record, spec, hashes,
                record_path=record_path, trusted_runs_root=trusted_runs_root, submission=submission,
                assets_root=assets_root, task_id=task_id, harness_config=harness_config)
            recorded_board = harness_record.get("board")
            if recorded_board not in {"single-shot", "auto-refinement"} or (board is not None and board != recorded_board):
                evidence["harness"] = {}
                raise ValueError("Requested board does not match recorded generation protocol")
            board = recorded_board
        except (OSError, TypeError, ValueError, KeyError) as error:
            errors.append(str(error))
    for name, path in paths.items():
        try:
            if artifact_sha256(path) != hashes[name]:
                raise ValueError("Artifact changed during inspection")
        except (OSError, ValueError) as error:
            evidence["artifacts"][name]["loadable"] = False
            evidence["artifacts"][name]["error"] = str(error)
            errors.append(f"{name}: {error}")
    report = score_l2(spec, evidence)
    harness = evidence["harness"]
    try:
        if "vlm_ratings" in harness:
            report["S_vlm"] = vlm_score(
                harness["vlm_ratings"], harness.get("vlm_importance")
            )
        if "human" in harness:
            report["S_human"] = human_score(**harness["human"])
        if "efficiency" in harness:
            report["efficiency"] = efficiency_metrics(
                final_score=report["S_core"], **harness["efficiency"]
            )
    except (TypeError, ValueError) as error:
        errors.append(f"Auxiliary evidence: {error}")
    report["efficiency"] = dict(harness.get("costs", report["efficiency"]))
    if harness:
        elapsed = time.monotonic()-started
        report['efficiency']['evaluation_seconds'] = elapsed
        report['efficiency']['evaluation_total_seconds'] = report['efficiency'].get('evaluation_total_seconds', 0)+elapsed
        report['efficiency']['total_seconds'] = report['efficiency'].get('total_seconds', 0)+elapsed
    report.update(
        {
            "task_id": task_id,
            "evaluation_kind": harness.get('evaluation_kind', 'unverified'),
            "harness_version": harness.get('harness_version'),
            "generation_protocol": harness.get('generation_protocol'),
            "model": (harness.get('generation') or {}).get('model'),
            "reasoning_effort": (harness.get('generation') or {}).get('reasoning_effort'),
            "task_type": task_type or task_id.split("/")[-1],
            "trial_id": trial_id,
            "board": board or "single-shot",
            "artifact_sha256": hashes,
            "errors": errors,
            "timed_out": timed_out,
            "evaluation_seconds": time.monotonic() - started,
            "software": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "pillow": PIL.__version__,
                "blender": evidence.get("scene", {}).get("blender_version"),
            },
            "evidence_path": str(output / "evidence.json"),
            "report_path": str(output / "report.json"),
        }
    )
    policy = None
    if harness_config is not None:
        from harness.L2.config import load_policy
        policy = load_policy(harness_config, task_id, spec)
    from .l2_diagnostics import write_diagnostics
    route = next((c for checks in spec.checks.values() for c in checks if c.metric == 'l2_route'), None)
    write_diagnostics(evidence, output, entity_parts=policy.entity_parts if policy else {},
                      route_check=route, spec=spec)
    report['diagnostics_path'] = str(output/'scene_diagnostics.json')
    report['requirements_coverage'] = {'task_completion': 'unmapped', 'formal_score_eligible': False}
    if policy and policy.requirements:
        from .l2_requirements import coverage
        report['requirements_coverage'] = coverage(policy.requirements, report)
        report['review_packet'] = str(output/'review/packet.json')
        evidence['audit_views'] = list(policy.views)
    _write_json(output / "evidence.json", evidence)
    _write_json(output / "report.json", report)
    if policy and policy.requirements:
        from harness.L2.review import prepare
        prepare(output/'report.json', policy.requirements, evidence, output/'review')
    return report
