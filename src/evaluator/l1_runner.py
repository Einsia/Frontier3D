"""Collect independent L1 evidence and bind trusted harness records to artifacts."""

# Invalid external JSON records are validation errors, including wrong types.
# ruff: noqa: TRY004

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess  # noqa: F401 - public patch seam for inspector worker tests
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import PIL
from PIL import Image

from .l1 import failed_l1_report
from .l1_budget import DeadlineBudget, positive_seconds
from .l1_compute import run_compute
from .l1_failures import InspectionFailure, pointer_token, record_failure
from .l1_file_io import run_file_io
from .l1_finalization import ReportFinalizer
from .l1_geometry import GeometryConfig, L1GeometryEvaluator
from .l1_inspection import MISSING, InspectionSession
from .l1_parent_io import (
    ensure_directory,
    make_temp_directory,
    prepare_inspector,
    write_bounded_json,
)
from .metrics import validate_metrics
from .spec import EVALUATOR_VERSION, EvalSpec, contained_path

WORKER = Path(__file__).resolve().with_name("l1_blender.py")


def _check_deadline(deadline: float | None, stage: str) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise InspectionFailure(
            "infrastructure_error", "EVALUATION_BUDGET_EXHAUSTED",
            f"Shared evaluator deadline exhausted {stage}",
        )


def artifact_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_json(path: Path, value: Any, *, deadline: float | None = None) -> None:
    """Write evaluator metadata through the bounded persistence worker.

    ``deadline=None`` remains a compatibility path for test callbacks and
    legacy callers; all normal L1 evaluation writes pass the shared deadline.
    """
    if deadline is None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        return
    write_bounded_json(path, value, deadline=deadline)


def _validate_state_sequence(result: dict, *, frames: tuple[int, ...], process_id: int,
                             scene: Path, scene_sha256: str, spec_sha256: str) -> None:
    """Reject incomplete, reordered or unbound single-session worker output."""
    def require(condition):
        if not condition:
            raise ValueError("State sequence contract mismatch")

    try:
        sequence = result["state_sequence"]
        require(sequence["protocol"] == "l1-state-sequence-v1" and sequence["status"] == "completed")
        require(type(sequence["process_id"]) is int and sequence["process_id"] == process_id)
        require(type(sequence["file_loads"]) is int and sequence["file_loads"] == 1)
        require(sequence["frames"] == list(frames) and all(type(frame) is int for frame in sequence["frames"]))
        require(isinstance(sequence["session_id"], str) and len(sequence["session_id"]) == 32)
        int(sequence["session_id"], 16)
        require(sequence["scene_path"] == str(scene.resolve()) and sequence["scene_sha256"] == scene_sha256)
        require(sequence["spec_sha256"] == spec_sha256 and sequence["autoexec_enabled"] is False)
        require(sequence["identity_kind"] == "blender_id_session_uid")
        snapshots = sequence["snapshots"]
        require(isinstance(snapshots, list) and len(snapshots) == len(frames))
        for index, (snapshot, frame) in enumerate(zip(snapshots, frames)):
            require(type(snapshot["index"]) is int and snapshot["index"] == index)
            require(type(snapshot["frame"]) is int and snapshot["frame"] == frame)
            require(type(snapshot["observed_frame"]) is int and snapshot["observed_frame"] == frame)
            require(isinstance(snapshot["scene"]["objects"], dict))
            identities = [item["session_identity"] for item in snapshot["scene"]["objects"].values()]
            require(all(type(identity) is int and identity > 0 for identity in identities))
            require(len(identities) == len(set(identities)))
        require(result["scene"] == snapshots[0]["scene"])
    except (KeyError, TypeError, ValueError) as error:
        raise InspectionFailure("infrastructure_error", "WORKER_PROTOCOL_ERROR",
                                "Invalid or unbound Blender state sequence") from error


def _validate_texture_resource_policy(scene: dict, roots: list[Path]) -> None:
    # Legacy synthetic observations without this layer remain loadable; a new
    # observation or any explicit resource grant must echo the exact authority.
    if not roots and 'texture_resource_policy' not in scene:
        return
    expected = {'protocol': 'l1-texture-resource-policy-v1', 'external_roots': [str(root) for root in roots],
                'default_external_access': 'denied', 'packed_images': 'allowed'}
    if scene.get('texture_resource_policy') != expected:
        raise InspectionFailure('infrastructure_error', 'WORKER_PROTOCOL_ERROR', 'Texture resource authority differs from request')


def _inspect(
    blender: Path,
    scene: Path,
    spec_path: Path,
    directory: Path,
    timeout: float,
    *,
    views: bool = True,
    beauty_view: str | None = None,
    deadline: float | None = None,
    frame: int = 1,
    frames: tuple[int, ...] | None = None,
    material_resource_roots: tuple[Path, ...] = (),
) -> dict[str, Any]:
    # Reject malformed API requests before creating an inspection/persistence
    # session. Error metadata must not launch a child for an invalid request.
    if frames is not None and (
        type(frames) is not tuple or not 1 <= len(frames) <= 16
        or any(type(value) is not int or value < 0 for value in frames)
        or scene.suffix.lower() != ".blend" or views or beauty_view is not None
    ):
        raise ValueError("State sequence requires 1–16 nonnegative native frames with views=False")
    with InspectionSession(directory, timeout, deadline) as session:
        session.record.update(scene_path=str(scene), spec_path=str(spec_path),
                              frame=frame if type(frame) is int else None,
                              frames=list(frames) if type(frames) is tuple and len(frames) <= 16
                              and all(type(value) is int for value in frames) else None)
        result = _inspect_body(blender, scene, spec_path, directory, session, views=views,
                               beauty_view=beauty_view, frame=frame, frames=frames,
                               material_resource_roots=material_resource_roots)
    result['inspector_execution'] = session.evidence()
    result['inspector_persistence'] = session.persistence.evidence()
    return result


def _inspect_body(blender, scene, spec_path, directory, session, *, views, beauty_view, frame, frames,
                  material_resource_roots):
    if type(material_resource_roots) is not tuple or len(material_resource_roots) > 16:
        raise ValueError('Material resource roots require a bounded explicit tuple')
    if material_resource_roots and beauty_view is not None:
        raise ValueError('Texture resource authority is for material observation, not beauty rendering')
    session.guard()
    try:
        prepared = prepare_inspector(
            str(blender), WORKER, deadline=session.budget.deadline,
            resource_roots=tuple(Path(root) for root in material_resource_roots),
            beauty=beauty_view is not None,
        )
    except (InspectionFailure, KeyboardInterrupt, SystemExit) as error:
        session.record["launch_preparation"] = getattr(error, "parent_io", None)
        if isinstance(error, InspectionFailure):
            if error.code == "PARENT_IO_BUDGET_EXHAUSTED":
                raise session.timeout() from error
            child_error = (getattr(error, "parent_io", {}).get("worker_result") or {}).get("error_type")
            code = "BLENDER_UNAVAILABLE" if child_error == "BlenderUnavailable" else "INSPECTION_LAUNCH_PREPARATION_FAILED"
            raise InspectionFailure("infrastructure_error", code,
                                    "Inspector launcher/resource discovery failed") from error
        raise
    session.record["launch_preparation"] = prepared
    roots = [Path(root) for root in prepared["result"]["material_resource_roots"]]
    session.guard()
    bind_inputs = frames is not None or beauty_view is not None
    source_hash = session.hash(scene, 'before', 'scene') if bind_inputs else None
    spec_hash = session.hash(spec_path, 'before', 'spec') if bind_inputs else None
    output = directory / "facts.json"
    command = [
        prepared["result"]["launcher"]["path"],
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "-noaudio",
        "--threads",
        "4",
        "--python-exit-code",
        "1",
        "--python",
        prepared["result"]["runner"],
        "--",
        "--scene",
        str(scene),
        "--spec",
        str(spec_path),
        "--output",
        str(output),
        "--frame",
        str(frame),
    ]
    environment = os.environ.copy()
    for root in roots:
        command += ['--material-resource-root', str(root)]
    if not views:
        command.append("--no-views")
    if frames is not None:
        command += ["--frames", *(str(value) for value in frames)]
    if beauty_view is not None:
        command += ["--beauty-view", beauty_view]
        # GL-backed native engines need a display on this headless host.
        # Do not silently replace rendering with a diffuse-color approximation.
        display_prefix = prepared["result"]["display"]["prefix"]
        if display_prefix:
            command = [*display_prefix, *command]
            environment["LIBGL_ALWAYS_SOFTWARE"] = "1"
            environment.pop("EGL_PLATFORM", None)
    # A process group includes Xvfb and Blender so timeouts leave no children.
    returncode = session.launch(command, environment)
    if returncode != 0:
        failure = session.read_json('failure.json', optional=True, limit=65536)
        if failure is not MISSING:
            try:
                if not isinstance(failure, dict) or set(failure) != {'status', 'code', 'reason'} or any(
                    not isinstance(value, str) or not value for value in failure.values()
                ):
                    raise ValueError('Invalid worker failure record')
                classified = InspectionFailure(**failure)
            except (ValueError, TypeError) as error:
                raise InspectionFailure('infrastructure_error', 'WORKER_PROTOCOL_ERROR', str(error)) from error
            raise classified
        raise InspectionFailure(
            'infrastructure_error', 'WORKER_PROCESS_ERROR', f'Blender exited with {returncode}; see {directory / "inspect.log"}')
    result = session.read_json('facts.json')
    required = "views" if beauty_view is not None else "scene"
    if not isinstance(result, dict) or not isinstance(result.get(required), dict):
        raise InspectionFailure(
            "infrastructure_error",
            "WORKER_PROTOCOL_ERROR",
            "Invalid Blender inspection output",
        )
    if frames is not None:
        _validate_state_sequence(result, frames=frames, process_id=session.record['pid'], scene=scene,
                                 scene_sha256=source_hash, spec_sha256=spec_hash)
    if bind_inputs:
        if session.hash(scene, 'after', 'scene') != source_hash or session.hash(spec_path, 'after', 'spec') != spec_hash:
            raise InspectionFailure("not_measurable", "INSPECTION_INPUT_CHANGED",
                                    "Scene or specification changed during inspection")
        if beauty_view is not None:
            result['views'][beauty_view]['source_sha256'] = source_hash
            result['views'][beauty_view]['spec_file_sha256'] = spec_hash
    if required == 'scene':
        observations = [snapshot['scene'] for snapshot in result['state_sequence']['snapshots']] if frames is not None else [result['scene']]
        for observed_scene in observations:
            _validate_texture_resource_policy(observed_scene, roots)
    session.guard()
    return result


def _collect_beauty_views(
    blender: Path,
    scene: Path,
    spec_path: Path,
    output: Path,
    timeout: float,
    spec: EvalSpec,
    evidence: dict[str, Any],
    errors: list[str],
    deadline: float | None = None,
) -> None:
    """Isolate each native render from geometry inspection and from other views."""
    for view in spec.render_views:
        if not view.get("beauty"):
            continue
        view_id = view["id"]
        entry = evidence.setdefault("views", {}).setdefault(view_id, {})
        try:
            result = _inspect(
                blender,
                scene,
                spec_path,
                output / view_id,
                timeout,
                beauty_view=view_id,
                deadline=deadline,
            )
            native = result["views"][view_id]
            path = Path(native["image"])
            if not path.resolve().is_relative_to(output.resolve()):
                raise ValueError("Render image escapes evaluator output")
            metadata = run_file_io('image_metadata', {'path': str(path)}, output=output / 'file_io',
                                   deadline=deadline, timeout=timeout)
            if metadata['size'] != view.get("beauty_resolution", [960, 720]):
                raise ValueError("Native render resolution differs from EvalSpec")
            if view.get('camera_source') in {'saved', 'declared'}:
                mask = Path(native['mask'])
                if not mask.resolve().is_relative_to(output.resolve()):
                    raise ValueError('Geometry mask escapes evaluator output')
                mask_io = run_file_io('image_metadata', {'path': str(mask)}, output=output / 'file_io',
                                     deadline=deadline, timeout=timeout)
                if mask_io['sha256'] != native['mask_sha256'] or mask_io['size'] != metadata['size']:
                    raise ValueError('Geometry mask hash or size mismatch')
                native['mask_io'] = mask_io
            entry.update(native, image_sha256=metadata['sha256'], image_io=metadata,
                         inspector_execution=result.get("inspector_execution"),
                         inspector_persistence=result.get("inspector_persistence"))
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            entry.pop("image", None)
            entry["render_error"] = str(error)
            errors.append(f"beauty {view_id}: {error}")
            failure = (
                error
                if isinstance(error, InspectionFailure)
                else InspectionFailure(
                    "infrastructure_error", "RENDER_TOOL_ERROR", str(error)
                )
            )
            record_failure(
                spec, evidence, [f"/views/{pointer_token(view_id)}"], failure
            )


def _load_non_scene(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix == ".py":
        compile(path.read_bytes(), str(path), "exec")
    elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        with Image.open(path) as image:
            image.load()
    elif suffix == ".json":
        json.loads(path.read_text(encoding="utf-8"))
    elif suffix in {".txt", ".md", ".csv", ".toml"}:
        path.read_text(encoding="utf-8")
    else:
        raise ValueError(f"No artifact loader registered for {suffix!r}")


def _harness_record(
    record: dict[str, Any], spec: EvalSpec, hashes: dict[str, str]
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("Harness record must be an object")
    json.dumps(record, allow_nan=False)
    if (
        record.get("evaluator_version") != EVALUATOR_VERSION
        or record.get("spec_sha256") != spec.digest
        or record.get("artifact_sha256") != hashes
    ):
        raise ValueError(
            "Harness record does not match evaluator version, EvalSpec or artifact hashes"
        )
    for field in ("execution_passed", "integrity_passed"):
        if type(record.get(field)) is not bool:
            raise ValueError(f"Harness record requires boolean {field}")
    runs = record.get("seed_runs", {})
    if not isinstance(runs, dict):
        raise ValueError("seed_runs must be an object keyed by frozen seed")
    for seed, run in runs.items():
        if (
            seed not in {str(s) for s in spec.seeds}
            or not isinstance(run, dict)
            or type(run.get("passed")) is not bool
        ):
            raise ValueError("Invalid seed run record")
    reproduction = record.get("reproduction_consistency")
    if reproduction is not None:
        if not isinstance(reproduction, dict):
            raise ValueError("reproduction_consistency must be an object")
        if reproduction.get("protocol") != "l1-reproduction-v1":
            raise ValueError("Invalid reproduction protocol")
        if reproduction.get("status") not in {
            "ok",
            "failed",
            "not_configured",
            "not_measurable",
        }:
            raise ValueError("Invalid reproduction status")
        per_seed = reproduction.get("per_seed", {})
        if not isinstance(per_seed, dict):
            raise ValueError("reproduction per_seed must be an object")
        allowed_seeds = {str(s) for s in spec.seeds}
        if set(per_seed) - allowed_seeds:
            raise ValueError("Reproduction contains an unknown seed")
        for seed, result in per_seed.items():
            if not isinstance(result, dict) or result.get("status") not in {
                "ok",
                "failed",
                "not_configured",
                "not_measurable",
            }:
                raise ValueError(f"Invalid reproduction result for seed {seed}")
    return record


def _seed_reproduction_evidence(
    harness: dict[str, Any], expected_seeds: tuple[int, ...] | None = None
) -> dict[str, Any]:
    """Summarize trusted per-seed semantic reproduction for requirement bindings."""
    reproduction = harness.get("reproduction_consistency")
    if not isinstance(reproduction, dict):
        return {
            "status": "not_measurable",
            "operation": "seed_reproduction",
            "reason": "Trusted harness record has no reproduction consistency report",
            "evidence": {
                "reproduction_match": False,
                "seed_statuses": {},
            },
        }
    per_seed = reproduction.get("per_seed", {})
    if not isinstance(per_seed, dict) or not per_seed:
        return {
            "status": "not_measurable",
            "operation": "seed_reproduction",
            "reason": "Trusted harness record has no per-seed reproduction evidence",
            "evidence": {
                "reproduction_match": False,
                "seed_statuses": {},
            },
        }
    keys = (
        [str(seed) for seed in expected_seeds]
        if expected_seeds is not None
        else list(per_seed)
    )
    seed_statuses = {
        seed: per_seed.get(seed, {}).get("status")
        if isinstance(per_seed.get(seed), dict)
        else None
        for seed in keys
    }
    statuses = set(seed_statuses.values())
    if (None in statuses or "not_measurable" in statuses or "not_configured" in statuses
            or reproduction.get("status") in {"not_measurable", "not_configured"}):
        status = "not_measurable"
    elif "failed" in statuses or reproduction.get("status") == "failed":
        status = "failed"
    elif statuses == {"ok"}:
        status = "ok"
    else:
        status = "infrastructure_error"
    return {
        "status": status,
        "operation": "seed_reproduction",
        "reason": None if status == "ok" else "At least one seed lacks a passing semantic reproduction result",
        "evidence": {
            "reproduction_match": status == "ok",
            "seed_statuses": seed_statuses,
            "seed_count": len(seed_statuses),
            "protocol": reproduction.get("protocol"),
        },
    }


def _geometry_protocol_evidence(
    spec: EvalSpec,
    evidence: dict[str, Any],
    output: Path,
    *,
    blender: Path,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Attach shared geometry comparisons to one formal L1 inspection.

    The report remains separate from task-specific metrics until thresholds and
    semantic role policies are frozen.  It is nevertheless produced by the
    trusted evaluator, hash-bound to inspector mesh packets, and is never
    inferred from model-authored JSON.
    """
    from .l1_image_quality import visual_only
    if visual_only(spec.to_dict()):
        return {'protocol': 'l1-geometry-v1', 'status': 'not_configured', 'comparisons': {},
                'reason': 'CAD equivalence is outside visual v2 scoring; deliberately not measured'}
    if "l1_geometry" not in spec.to_dict():
        return {
            "protocol": "l1-geometry-v1",
            "status": "not_configured",
            "reason": "EvalSpec does not enable shared L1 geometry evidence",
            "comparisons": {},
        }
    candidate = evidence.get("scene")
    if not isinstance(candidate, dict):
        return {
            "protocol": "l1-geometry-v1",
            "status": "not_measurable",
            "reason": "Candidate native scene facts are unavailable",
            "comparisons": {},
        }
    tolerance = float(spec.tolerances.get("dimension_m", 1e-5))
    evaluator = L1GeometryEvaluator(
        GeometryConfig(
            trusted_root=output,
            surface_only='l1_edit_quality' in spec.to_dict(),
            surface_tolerance_m=tolerance,
            surface_levels=(256, 1024, 4096),
            surface_convergence_m=tolerance,
            blender=blender,
        )
    )
    pairs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    reference = evidence.get("reference")
    baseline = evidence.get("baseline")
    if isinstance(reference, dict):
        pairs["native_reference"] = (candidate, reference)
    if isinstance(baseline, dict):
        pairs["native_baseline"] = (candidate, baseline)
    glb = evidence.get("artifacts", {}).get("scene.glb", {}).get("scene")
    if isinstance(glb, dict):
        pairs["native_glb"] = (candidate, glb)
    comparisons: dict[str, Any] = {}
    for name, (left, right) in pairs.items():
        if deadline is not None and time.monotonic() >= deadline:
            comparisons[name] = {
                "protocol": "l1-geometry-v1",
                "operation": "scene_pairing",
                "status": "infrastructure_error",
                "failure": {
                    "status": "infrastructure_error",
                    "code": "EVALUATION_BUDGET_EXHAUSTED",
                    "reason": "Shared evaluator deadline was exhausted before geometry comparison",
                },
                "evidence": {},
            }
            continue
        comparisons[name] = evaluator.compare_scene_records(
            left,
            right,
            output=output / "geometry" / name,
            tolerance_m=tolerance,
            deadline=deadline,
        )
        if deadline is not None and time.monotonic() >= deadline:
            # Also reject a result that expired during IPC/finalization.
            comparisons[name].update({
                "status": "infrastructure_error",
                "failure": {
                    "status": "infrastructure_error", "code": "EVALUATION_BUDGET_EXHAUSTED",
                    "reason": "Shared deadline exhausted during geometry comparison",
                },
            })
    harness = evidence.get("harness")
    if isinstance(harness, dict) and "reproduction_consistency" in harness:
        comparisons["seed_reproduction"] = _seed_reproduction_evidence(
            harness, spec.seeds
        )
    if not pairs:
        status = "not_measurable"
        reason = "No trusted reference, baseline, or GLB scene facts were available"
    elif any(item.get("status") == "infrastructure_error" for item in comparisons.values()):
        status = "infrastructure_error"
        reason = "At least one shared geometry comparison was interrupted or unavailable"
    elif any(item.get("status") != "ok" for item in comparisons.values()):
        status = "failed"
        reason = "At least one shared geometry comparison did not match"
    else:
        status = "ok"
        reason = None
    report = {
        "protocol": "l1-geometry-v1",
        "status": status,
        "reason": reason,
        "report_path": str(output / "geometry_protocol.json"),
        "settings": {
            "surface_tolerance_m": tolerance,
            "surface_levels": [256, 1024, 4096],
            "alignment": "none",
            "blender": str(blender),
        },
        "comparisons": comparisons,
    }
    _write_json(output / "geometry_protocol.json", report, deadline=deadline)
    return report


def evaluate_l1_submission(
    spec: EvalSpec,
    submission: Path,
    blender: Path | None,
    *,
    assets_root: Path,
    harness_record: dict[str, Any] | None = None,
    timeout: float = 900.0,
    task_id: str = "L1/unknown",
    task_type: str | None = None,
    trial_id: str = "0",
    board: str = "single-shot",
    deadline: float | None = None,
    on_phase: Callable[[str, str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Inspect artifacts; execution/audit results must come from a trusted runner.

    This does not execute ``solution.py``. Syntax validity and loadability cannot
    establish successful execution. Missing/stale execution or anti-cheat records
    therefore fail the global gate while retaining diagnostic module scores.
    """
    started = time.monotonic()
    from .l1_image_quality import visual_only
    image_visual = visual_only(spec.to_dict())
    validate_metrics(spec)
    positive_seconds(timeout, "timeout")
    if deadline is not None:
        DeadlineBudget.start(timeout, deadline=deadline)  # Validate inherited timestamp.
    else:
        deadline = DeadlineBudget.start(timeout, started=started).deadline
    if board not in {"single-shot", "auto-refinement"}:
        raise ValueError("Unknown leaderboard protocol")
    submission = submission.expanduser().resolve()
    assets_root = assets_root.expanduser().resolve()
    # Discovery belongs to each deadline-bound InspectionSession. Do not
    # resolve a caller-controlled executable in the evaluator supervisor.
    blender = Path(blender) if blender is not None else Path(os.environ.get("BLENDER_BIN") or "blender")
    if not submission.is_dir():
        raise ValueError(f"Submission directory does not exist: {submission}")
    evaluation_root = contained_path(submission, "evaluation")
    path_io = [ensure_directory(evaluation_root, deadline=deadline, parents=True)["execution"]]
    # A fresh run directory prevents stale reports/masks surviving a failed run.
    temporary_output = make_temp_directory(evaluation_root, deadline=deadline, prefix="l1-")
    path_io.append(temporary_output["execution"])
    output = Path(temporary_output["result"]["path"]).resolve()
    spec_path = output / "eval_spec.json"
    _write_json(spec_path, spec.to_dict(), deadline=deadline)
    evidence: dict[str, Any] = {
        "artifacts": {}, "harness": {}, "path_io": path_io,
        "remaining_parent_io": ["launch_setup", "logs"],
    }
    errors: list[str] = []
    hashes: dict[str, str] = {}
    paths: dict[str, Path] = {}
    instruction_hash = None
    instruction_path = assets_root / 'instruction.md'
    if instruction_path.is_file():
        try:
            instruction_io = run_file_io('hash', {'path': str(instruction_path)},
                                         output=output / 'file_io', deadline=deadline)
            instruction_hash = instruction_io['sha256']
            evidence['instruction_io'] = instruction_io
        except (OSError, ValueError, InspectionFailure) as error:
            failure = error if isinstance(error, InspectionFailure) else InspectionFailure(
                'infrastructure_error', 'INSTRUCTION_FILE_UNAVAILABLE', str(error))
            record_failure(spec, evidence, ['/instruction'], failure)
    for name in spec.required_artifacts:
        artifact: dict[str, Any] = {"loadable": False}
        evidence["artifacts"][name] = artifact
        try:
            path = contained_path(submission, name)
            metadata = run_file_io('hash', {'path': str(path)}, output=output / 'file_io', deadline=deadline)
            hashes[name] = metadata['sha256']
            paths[name] = path
            artifact.update(sha256=hashes[name], bytes=metadata['bytes'], hash_io=metadata)
        except (OSError, ValueError, InspectionFailure) as error:
            artifact["error"] = str(error)
            if name == spec.scene or isinstance(error, InspectionFailure):
                record_failure(
                    spec,
                    evidence,
                    (["/scene", "/probes", "/views"] if name == spec.scene else [])
                    + ([f"/artifacts/{pointer_token(name)}"] if isinstance(error, InspectionFailure) else []),
                    error if isinstance(error, InspectionFailure) else InspectionFailure(
                        "not_measurable", "CANDIDATE_SCENE_MISSING", str(error)
                    ),
                )

    for index, (name, path) in enumerate(paths.items()):
        artifact = evidence["artifacts"][name]
        try:
            if path.suffix.lower() in {".blend", ".glb", ".gltf"}:
                result = _inspect(
                    blender,
                    path,
                    spec_path,
                    output / f"artifact-{index}",
                    timeout,
                    views=name == spec.scene,
                    deadline=deadline,
                )
                # An empty export is loadable but not a usable 3D delivery.
                artifact["loadable"] = result["scene"].get("has_real_geometry") is True
                artifact["scene"] = result["scene"]
                artifact["inspector_execution"] = result.get("inspector_execution")
                artifact["inspector_persistence"] = result.get("inspector_persistence")
                if name == spec.scene:
                    evidence.update(result)
            else:
                artifact['validation_io'] = run_file_io('validate_artifact', {'path': str(path)},
                                                         output=output / 'file_io', deadline=deadline)
                artifact["loadable"] = True
        except (OSError, ValueError, RuntimeError, SyntaxError) as error:
            artifact["error"] = str(error)
            errors.append(f"{name}: {error}")
            # Known candidate parse faults remain failed deliverables. Unknown
            # tool faults are unavailable evidence, not proof of a bad scene.
            failure = (
                error
                if isinstance(error, InspectionFailure)
                else InspectionFailure(
                    "not_measurable"
                    if isinstance(error, (SyntaxError, UnicodeError, ValueError))
                    else "infrastructure_error",
                    "ARTIFACT_INSPECTION_ERROR",
                    str(error),
                )
            )
            scopes = ["/scene", "/probes", "/views"] if name == spec.scene else []
            if failure.status != "not_measurable":
                scopes.append(f"/artifacts/{pointer_token(name)}")
            record_failure(spec, evidence, scopes, failure)

    if "scene" in evidence and spec.scene in paths:
        _collect_beauty_views(
            blender,
            paths[spec.scene],
            spec_path,
            output / "beauty",
            timeout,
            spec,
            evidence,
            errors,
            deadline,
        )

    if spec.reference_images:
        reference_images: dict[str, Any] = {}
        reference_dir = output / "reference_images"
        ensure_directory(reference_dir, deadline=deadline, parents=True)
        for view, relative in spec.reference_images.items():
            try:
                path = contained_path(assets_root, relative)
                staged = reference_dir / f"{view}{path.suffix.lower()}"
                metadata = run_file_io('stage_image', {'path': str(path), 'target': str(staged)},
                                       output=output / 'file_io', deadline=deadline)
                reference_images[view] = {
                    "path": str(staged),
                    "sha256": metadata['sha256'],
                    "size": metadata['size'],
                    "file_io": metadata,
                }
            except (OSError, ValueError, InspectionFailure) as error:
                errors.append(f"reference image {view}: {error}")
                record_failure(
                    spec,
                    evidence,
                    [f"/reference_images/{pointer_token(view)}"],
                    error if isinstance(error, InspectionFailure) else InspectionFailure(
                        "infrastructure_error",
                        "REFERENCE_IMAGE_UNAVAILABLE",
                        str(error),
                    ),
                )
        evidence["reference_images"] = reference_images

    from .l1_image_pair import collect_reference_masks
    collect_reference_masks(spec, evidence, assets_root, output, deadline=deadline)

    for label, relative in (
        ("reference", spec.reference_scene),
        ("baseline", spec.baseline_scene),
    ):
        if relative is None or image_visual:
            continue
        try:
            path = contained_path(assets_root, relative)
            metadata = run_file_io('hash', {'path': str(path)}, output=output / 'file_io', deadline=deadline)
            evidence[f"{label}_sha256"] = metadata['sha256']
            evidence[f"{label}_io"] = metadata
            result = _inspect(
                blender,
                path,
                spec_path,
                output / label,
                timeout,
                views=label == "reference",
                deadline=deadline,
            )
            evidence[label] = result["scene"]
            evidence[f"{label}_inspector_execution"] = result.get("inspector_execution")
            evidence[f"{label}_inspector_persistence"] = result.get("inspector_persistence")
            if label == "reference":
                evidence["reference_views"] = result["views"]
        except (OSError, ValueError, RuntimeError) as error:
            errors.append(f"{label}: {error}")
            # A broken evaluator-owned reference is always infrastructure,
            # even if the Blender loader identifies a malformed scene.
            scopes = [f"/{label}"] + (
                ["/reference_views"] if label == "reference" else []
            )
            failure = (
                error
                if isinstance(error, InspectionFailure)
                else InspectionFailure(
                    "infrastructure_error", "REFERENCE_SCENE_UNAVAILABLE", str(error)
                )
            )
            record_failure(spec, evidence, scopes, failure)

    if harness_record is not None:
        try:
            evidence["harness"] = _harness_record(harness_record, spec, hashes)
        except (TypeError, ValueError) as error:
            errors.append(str(error))
            record_failure(
                spec,
                evidence,
                ["/harness"],
                InspectionFailure(
                    "infrastructure_error", "TRUSTED_RECORD_MISMATCH", str(error)
                ),
            )
    for name, path in paths.items():
        try:
            metadata = run_file_io('hash', {'path': str(path)}, output=output / 'file_io', deadline=deadline)
            evidence['artifacts'][name]['final_hash_io'] = metadata
            if metadata['sha256'] != hashes[name]:
                raise ValueError("Artifact changed during inspection")
        except (OSError, ValueError, InspectionFailure) as error:
            evidence["artifacts"][name]["loadable"] = False
            evidence["artifacts"][name]["error"] = str(error)
            errors.append(f"{name}: {error}")
            if isinstance(error, InspectionFailure):
                record_failure(spec, evidence, [f"/artifacts/{pointer_token(name)}"], error)

    from .l1_numeric_checks import collect_numeric_checks
    if not image_visual:
        collect_numeric_checks(spec, evidence, output, deadline=deadline, assets_root=assets_root)

    from .l1_edit_surface import collect as collect_edit_surface
    collect_edit_surface(spec, evidence, output, deadline)
    from .l1_edit_probes import collect as collect_edit_probes
    collect_edit_probes(spec, evidence, output, deadline)

    from .l1_material_sequence import collect_material_sequences
    collect_material_sequences(spec, evidence, paths, output, task_id=task_id, blender=blender,
                               spec_path=spec_path, timeout=timeout, deadline=deadline)

    evidence["geometry_protocol"] = _geometry_protocol_evidence(
        spec,
        evidence,
        output,
        blender=blender,
        deadline=deadline,
    )

    from .l1_area_diagnostics import collect_area_diagnostics
    if not image_visual:
        collect_area_diagnostics(spec, evidence, output, deadline=deadline)

    def record_budget_failure() -> bool:
        try:
            _check_deadline(deadline, "before evaluation finalization")
        except InspectionFailure as failure:
            if not any(item.get("code") == failure.code for item in evidence.get("inspection_failures", [])):
                record_failure(spec, evidence, ["/budget"], failure)
            return True
        return False

    record_budget_failure()

    if on_phase is not None:
        infrastructure_failed = bool(evidence.get("infrastructure_errors")) or (
            evidence["geometry_protocol"].get("status") == "infrastructure_error"
        )
        on_phase("inspection", "failed" if infrastructure_failed else "completed", {
            "evidence_dir": str(output),
            "infrastructure_error_count": len(evidence.get("infrastructure_errors", [])),
            "geometry_protocol_status": evidence["geometry_protocol"].get("status"),
        })
        on_phase("scoring", "started", {"evidence_dir": str(output)})
    scoring_failed = False
    scoring_interrupt = None
    try:
        # run_compute emits an explicit not-started receipt at an expired
        # deadline; a separate pre-check would lose that failure provenance.
        report = run_compute(
            "score", {"spec": spec.to_dict(), "evidence": evidence},
            output=output / "scoring", deadline=deadline,
        )
        errors.extend(report.pop("auxiliary_errors", []))
    except (InspectionFailure, KeyboardInterrupt, SystemExit) as error:
        scoring_interrupt = error if isinstance(error, (KeyboardInterrupt, SystemExit)) else None
        failure = error if isinstance(error, InspectionFailure) else InspectionFailure(
            "infrastructure_error", "COMPUTE_INTERRUPTED", type(error).__name__,
        )
        scoring_failed = True
        record_failure(spec, evidence, ["/scoring"], failure)
        report = failed_l1_report(spec, failure)
        if isinstance(getattr(error, "compute_execution", None), dict):
            report["compute_execution"] = error.compute_execution
        report["scoring_failure"] = {
            "code": failure.code, "status": failure.status,
            "exception_type": type(error).__name__,
        }
        errors.append(failure.code)
    expired = record_budget_failure()
    report.update(
        {
            "task_id": task_id,
            "task_type": task_type or task_id.split("/")[-1],
            "trial_id": trial_id,
            "board": board,
            "evaluation_kind": "independent_artifact_inspection",
            "instruction_sha256": instruction_hash,
            "artifact_sha256": hashes,
            "geometry_protocol_status": evidence["geometry_protocol"].get("status"),
            "geometry_protocol": evidence["geometry_protocol"],
            "geometry_protocol_path": str(output / "geometry_protocol.json")
            if (output / "geometry_protocol.json").is_file()
            else None,
            "errors": errors,
            "evaluation_seconds": time.monotonic() - started,
            "budget_exhausted": expired or any(
                item.get("code") == "EVALUATION_BUDGET_EXHAUSTED"
                for item in evidence.get("inspection_failures", [])
            )
            or any(
                (comparison.get("failure") or {}).get("code")
                == "EVALUATION_BUDGET_EXHAUSTED"
                for comparison in evidence["geometry_protocol"].get(
                    "comparisons", {}
                ).values()
            ),
            "scoring_failed": scoring_failed,
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
    if report["budget_exhausted"]:
        # This also protects legacy/fixture specs without l1_protocol. Scores
        # already computed are diagnostic evidence, never a valid late pass.
        report.update(G=0, case_pass=False, S_core=0.0, S_diagnostic=0.0, declared_checks_pass=False,
                      status="infrastructure_error", task_completion="incomplete")
        report["gates"]["budget"] = {"passed": False, "reason": "EVALUATION_BUDGET_EXHAUSTED"}
    if scoring_failed:
        # Raw inspector/compute evidence already lives in stage directories.
        # Do not repeatedly serialize candidate-sized geometry/state after a
        # timeout. This path depends only on frozen spec/phase metadata.
        compact = {
            "protocol": "l1-failure-evidence-v1", "spec_sha256": spec.digest,
            "artifact_sha256": hashes,
            "inspection_failures": evidence.get("inspection_failures", []),
            "infrastructure_errors": evidence.get("infrastructure_errors", []),
            "measurement_failures": evidence.get("measurement_failures", {}),
            "raw_evidence_directory": str(output),
            "reason": "Scoring unavailable; stage-local evidence retained without reserializing candidate data",
        }
        report["geometry_protocol"] = {
            "protocol": "l1-geometry-v1", "status": evidence["geometry_protocol"].get("status"),
            "report_path": report["geometry_protocol_path"], "details_retained_in_stage_files": True,
        }
        report["failure_report_policy"] = "spec_bounded_no_metric_retry_stage_evidence_retained"
        final_evidence = compact
    else:
        final_evidence = evidence
    finalizer = ReportFinalizer(spec, output, deadline)
    compute_session = report.get("compute_execution", {}).get("record_persistence", {})
    cleanup_deadline = compute_session.get("cleanup_deadline_monotonic")
    if scoring_failed and cleanup_deadline is not None:
        # The compute failure already began cleanup. Publication cannot obtain
        # a fresh allowance just because it has a separate ACK ledger.
        finalizer.persistence.cleanup_deadline = cleanup_deadline
    try:
        report = finalizer.finish(report, final_evidence)
    except BaseException as error:
        if scoring_interrupt is None:
            raise
        scoring_interrupt.finalization_report = getattr(error, "finalization_report", report)
        scoring_interrupt.finalization_failure = type(error).__name__
        raise scoring_interrupt from error
    if scoring_interrupt is not None:
        scoring_interrupt.finalization_report = report
        raise scoring_interrupt
    if on_phase is not None:
        on_phase("scoring", "failed" if report["scoring_failed"] or report["budget_exhausted"] else "completed", {
            "report_path": str(output / "report.json"),
            "evidence_path": str(output / "evidence.json"),
            "case_pass": report.get("case_pass"),
        })
    if not report.get("budget_exhausted") and time.monotonic() >= deadline:
        # Caller checkpoint I/O is not yet migrated, but it cannot make the
        # direct API return a late successful result. The caller's phase
        # ledger must still handle its own failure/timeout terminal state.
        report = finalizer.fail(report, final_evidence, InspectionFailure(
            "infrastructure_error", "EVALUATION_BUDGET_EXHAUSTED", "Final phase callback exhausted deadline"))
    return report
