"""Run the evaluator-owned original-to-seed L1 semantic comparison."""

from __future__ import annotations

import json
import time
from functools import wraps
from pathlib import Path
from typing import Any

from src.evaluator.l1_budget import DeadlineBudget
from src.evaluator.l1_compute import run_compute
from src.evaluator.l1_failures import InspectionFailure
from src.evaluator.l1_geometry import GeometryConfig, L1GeometryEvaluator
from src.evaluator.l1_inspection_receipt import validate_inspection
from src.evaluator.l1_runner import _check_deadline, _inspect


def frame_policy(task_id: str, spec=None) -> dict[str, Any]:
    """Use task deliverable states, never require animation from a static GLB."""
    pieces = task_id.split('/')
    category = pieces[1] if len(pieces) in {2, 3} and pieces[0] == 'L1' else None
    allowed = {'Text2Code', 'Image2Code', 'CodeEdit'}
    if len(pieces) == 3:
        allowed.add('Image2Code-SingleView')
        prefix = f'task_L1_{category}_'
        if not pieces[2].startswith(prefix) or len(pieces[2][len(prefix):]) != 3 or not pieces[2][len(prefix):].isdigit():
            raise ValueError(f"Unsupported L1 reproduction task: {task_id}")
    if category not in allowed:
        raise ValueError(f"Unsupported L1 reproduction task: {task_id}")
    if spec is not None:
        raw = spec.to_dict() if hasattr(spec, 'to_dict') else spec
        if raw.get('l1_image_quality', {}).get('version') == 'l1-reference-visual-v2.0.0':
            checks = [c for group in raw['checks'].values() for c in group
                      if c['metric'] == 'procedural_material_sequence' and c.get('applicable', True)]
            if len(checks) != 1 or checks[0]['params']['frames'] not in ([1], [1, 61, 1], [1, 31, 61, 91, 121, 1]):
                raise ValueError('Visual frame policy requires explicit supported state sequence')
            frames = checks[0]['params']['frames']
            if any(type(frame) is not int for frame in frames):
                raise ValueError('Visual frame policy requires integer states')
            return {'protocol': 'l1-reproduction-frame-policy-v1', 'task_id': task_id,
                    'native_frames': list(frames), 'glb_frames': [1], 'cross_format_frames': [],
                    'scope': 'Visual v2 native material states; GLB readability only, no animation equality',
                    'native_inspection': 'single_session_material_audit',
                    'limitation': 'No motion, rigid shape, attachment or GLB animation quality claim'}
    # These instructions explicitly request a static pose and no exploded
    # state. Category-wide assembly defaults would add a hidden task.
    static_part = task_id in {
        'L1/Text2Code/task_L1_Text2Code_013',
        'L1/Text2Code/task_L1_Text2Code_014',
        'L1/Image2Code/task_L1_Image2Code_007',
        'L1/Image2Code/task_L1_Image2Code_009',
        'L1/Image2Code-SingleView/task_L1_Image2Code-SingleView_009',
        'L1/Image2Code-SingleView/task_L1_Image2Code-SingleView_012',
    }
    return {
        "protocol": "l1-reproduction-frame-policy-v1",
        "task_id": task_id,
        "native_frames": [1] if category == "CodeEdit" or static_part else [1, 61, 1],
        "glb_frames": [1],
        "cross_format_frames": [1],
        "scope": "Native declared states; exported GLB at assembled frame 1 only",
        "native_inspection": "single_session_with_fixed_identity_return",
        "limitation": "Return checks do not prove rigid shape preservation during explosion, true separation or complete materials",
    }


def _frame(
    geometry: L1GeometryEvaluator, left: dict, right: dict, *, output: Path,
    tolerance_m: float, material_tolerance: float, frame: int, deadline: float,
    material_scope: str = "native_constant_principled",
) -> dict[str, Any]:
    return run_compute("reproduction_frame", {
        "config": geometry.worker_configuration(), "left": left, "right": right,
        "arguments": {"output": str(output), "tolerance_m": tolerance_m},
        "frame": frame, "material_tolerance": material_tolerance,
        "material_scope": material_scope,
    }, output=output, deadline=deadline)


def _sequence(frames: list[dict], *, expected_frames: tuple[int, ...], context: dict, output: Path, deadline: float) -> dict:
    try:
        _check_deadline(deadline, "before reproduction sequence comparison")
        return run_compute("reproduction_sequence", {
            "frames": frames, "expected_frames": expected_frames, "context": context,
        }, output=output, deadline=deadline)
    except InspectionFailure as failure:
        # Preserve all frame slots but do not perform candidate-state equality
        # or material comparisons after budget exhaustion.
        return {
            "protocol": "l1-reproduction-v1", "status": "not_measurable", "frames": frames,
            "sequence": [item.get("frame") for item in frames], "expected_sequence": list(expected_frames),
            "sequence_valid": False, "round_trip": None, "context": context,
            "failure": {"status": failure.status, "code": failure.code, "reason": failure.reason},
        }


def _failure_frame(frame: int, error: Exception) -> dict:
    failure = {"status": error.status, "code": error.code, "reason": error.reason} if isinstance(error, InspectionFailure) else {
        "status": "not_measurable", "code": "REPRODUCTION_COMPARE_ERROR", "reason": str(error),
    }
    return {"frame": frame, "status": "not_measurable", "failure": failure, "within_tolerance": False}


def _observe(blender, scene, spec_path, output, timeout, *, inspections, **kwargs):
    """Keep every attempted observation, including failures before a second side."""
    slot = {"scene_path": str(scene), "spec_path": str(spec_path), "status": "not_started"}
    inspections[str(output)] = slot
    try:
        result = _inspect(blender, scene, spec_path, output, timeout, **kwargs)
        slot.update(inspector_execution=result.get("inspector_execution"),
                    inspector_persistence=result.get("inspector_persistence"))
        slot["validation"] = validate_inspection(
            result, scene=scene, spec=spec_path, deadline=kwargs["deadline"],
            frame=kwargs.get("frame", 1), frames=kwargs.get("frames"),
        )
        slot["status"] = "verified"
        return result
    except BaseException as error:
        # Preserve original cancellation and all observations made so far.
        slot.update(status="interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "unavailable",
                    failure={"code": str(getattr(error, "code", type(error).__name__)),
                             "status": getattr(error, "status", "infrastructure_error")})
        for key in ("inspector_execution", "inspector_persistence", "inspection_validation_io"):
            if hasattr(error, key):
                slot[key] = getattr(error, key)
        error.reproduction_inspections = inspections
        raise


def _native_sequence(
    *, blender: Path, original: Path, candidate: Path, spec_path: Path,
    output: Path, geometry: L1GeometryEvaluator, frames: tuple[int, ...], context: dict,
    timeout: float, deadline: float, tolerance_m: float, material_tolerance: float, inspections: dict,
) -> dict:
    """Observe each artifact once, then compare cross-run frames and own return."""
    sessions = {}
    comparisons = []
    return_reports = {}
    errors = (InspectionFailure, OSError, KeyError, TypeError, ValueError, RuntimeError)
    try:
        for side, scene in (("original", original), ("seed", candidate)):
            _check_deadline(deadline, "before native sequence observation")
            observed = _observe(blender, scene, spec_path, output / "session" / side, timeout, inspections=inspections,
                                views=False, deadline=deadline, frames=frames)
            sessions[side] = observed["state_sequence"]
            _check_deadline(deadline, "after native sequence observation")
    except errors as error:
        comparisons = [_failure_frame(frame, error) for frame in frames]
    else:
        for index, frame in enumerate(frames):
            try:
                _check_deadline(deadline, "before native sequence frame comparison")
                compared = _frame(geometry, sessions["original"]["snapshots"][index]["scene"],
                                  sessions["seed"]["snapshots"][index]["scene"],
                                  output=output / f"frame-{index:02d}" / "geometry",
                                  tolerance_m=tolerance_m, material_tolerance=material_tolerance,
                                  frame=frame, deadline=deadline)
                _check_deadline(deadline, "after native sequence frame comparison")
                comparisons.append(compared)
            except errors as error:
                comparisons.append(_failure_frame(frame, error))
        if len(frames) > 1:
            for side, sequence in sessions.items():
                try:
                    _check_deadline(deadline, "before native fixed-identity return comparison")
                    return_reports[side] = run_compute("state_return", {
                        "config": geometry.worker_configuration(), "sequence": sequence,
                        "arguments": {"output": str(output / "return" / side), "tolerance_m": tolerance_m,
                                      "material_tolerance": material_tolerance},
                    }, output=output / "return" / side, deadline=deadline)
                    _check_deadline(deadline, "after native fixed-identity return comparison")
                except errors as error:
                    return_reports[side] = {"protocol": "l1-state-return-v1", "status": "not_measurable",
                                            "failure": _failure_frame(frames[-1], error)["failure"]}
    bindings = {side: {key: sequence[key] for key in (
        "protocol", "session_id", "process_id", "file_loads", "frames", "scene_path", "scene_sha256", "spec_sha256",
    )} for side, sequence in sessions.items()}
    return _sequence(comparisons, expected_frames=frames, context={**context, "state_sessions": bindings,
                     "state_returns": return_reports}, output=output / "sequence", deadline=deadline)


def _retain_inspections(function):
    @wraps(function)
    def retained(**kwargs):
        inspections = {}
        try:
            return function(**kwargs, _inspections=inspections)
        except BaseException as error:
            # Cancellation can also arrive during geometry/sequence comparison,
            # after observation succeeded; retain the completed observations.
            error.reproduction_inspections = inspections
            raise
    return retained


@_retain_inspections
def compare_seed_artifacts(
    *,
    blender: Path,
    spec_path: Path,
    trusted_root: Path,
    original_artifacts: dict[str, Path],
    seed_root: Path,
    output_root: Path,
    task_id: str,
    trial_id: str,
    program_seed: int,
    repair_round: int = 0,
    timeout: float,
    deadline: float | None = None,
    tolerance_m: float = 1e-5,
    material_tolerance: float = 1e-5,
    frames: tuple[int, ...] | None = None,
    _inspections: dict | None = None,
) -> dict[str, Any]:
    """Compare native and GLB artifacts for one fixed seed.

    The helper intentionally returns structured unavailability on missing
    originals or failed worker calls.  It never turns a skipped comparison into
    a reproduction pass.
    """
    started = time.monotonic()
    policy = frame_policy(task_id)
    expected_native = tuple(policy["native_frames"])
    if frames is not None and (type(frames) is not tuple or any(type(frame) is not int for frame in frames)
                               or frames != expected_native):
        raise ValueError("Reproduction frames must match the task-owned frame policy")
    frames = expected_native
    if deadline is None:
        deadline = DeadlineBudget.start(timeout, started=started).deadline
    original_artifacts = {name: path for name, path in original_artifacts.items() if name in {"scene.blend", "scene.glb"}}
    output_root.mkdir(parents=True, exist_ok=True)
    if not original_artifacts:
        return {
            "protocol": "l1-reproduction-v1",
            "status": "not_configured",
            "reason": "No original pre-existing scene artifact was frozen",
            "artifacts": {},
            "frame_policy": policy,
            "cost_seconds": time.monotonic() - started,
        }
    score_policy = json.loads(spec_path.read_text())
    from src.evaluator.l1_image_quality import visual_only
    if visual_only(score_policy):
        from src.evaluator.l1_image_execution import bind_delivery
        result = bind_delivery(original_artifacts=original_artifacts, seed_root=seed_root,
            output_root=output_root, spec_path=spec_path, deadline=deadline)
        return {**result, 'cost_seconds': time.monotonic() - started}
    geometry = L1GeometryEvaluator(
        GeometryConfig(
            trusted_root=trusted_root,
            surface_only=any(k in score_policy for k in ('l1_edit_quality','l1_image_quality')),
            reproduction_diagnostics='l1_image_quality' not in score_policy,
            surface_tolerance_m=tolerance_m,
            surface_levels=(256, 1024, 4096),
            surface_convergence_m=tolerance_m,
        )
    )
    artifacts: dict[str, Any] = {}
    inspections: dict[str, Any] = _inspections if _inspections is not None else {}
    for name in ("scene.blend", "scene.glb"):
        original = original_artifacts.get(name)
        candidate = seed_root / name
        artifact_frames = frames if name == "scene.blend" else tuple(policy["glb_frames"])
        if original is None or not original.is_file() or not candidate.is_file():
            artifacts[name] = {
                "status": "not_measurable",
                "reason": "Original or seed artifact is missing",
                "expected_sequence": list(artifact_frames),
            }
            continue
        context = {
            "task_id": task_id, "trial_id": trial_id, "program_seed": program_seed,
            "repair_round": repair_round, "original_artifact": name, "candidate_artifact": name,
            "frame_policy": policy,
        }
        if name == "scene.blend":
            artifacts[name] = _native_sequence(
                blender=blender, original=original, candidate=candidate, spec_path=spec_path,
                output=output_root / "scene-blend", geometry=geometry, frames=artifact_frames, context=context,
                timeout=timeout, deadline=deadline, tolerance_m=tolerance_m, material_tolerance=material_tolerance,
                inspections=inspections,
            )
            continue
        frame_reports: list[dict[str, Any]] = []
        for index, frame in enumerate(artifact_frames):
            frame_root = output_root / name.replace(".", "-") / f"frame-{index:02d}"
            try:
                left = _observe(
                    blender,
                    original,
                    spec_path,
                    frame_root / "original",
                    timeout,
                    inspections=inspections,
                    views=False,
                    deadline=deadline,
                    frame=frame,
                )
                right = _observe(
                    blender,
                    candidate,
                    spec_path,
                    frame_root / "seed",
                    timeout,
                    inspections=inspections,
                    views=False,
                    deadline=deadline,
                    frame=frame,
                )
                _check_deadline(deadline, "before reproduction comparison")
                frame_report = _frame(
                    geometry,
                    left["scene"],
                    right["scene"],
                    output=frame_root / "geometry",
                    tolerance_m=tolerance_m,
                    frame=frame, material_tolerance=material_tolerance, deadline=deadline,
                    material_scope="gltf_core_pbr",
                )
                _check_deadline(deadline, "after reproduction comparison")
                frame_reports.append(frame_report)
            except InspectionFailure as error:
                frame_reports.append(
                    {
                        "frame": frame,
                        "status": "not_measurable",
                        "failure": {
                            "status": error.status,
                            "code": error.code,
                            "reason": error.reason,
                        },
                        "within_tolerance": False,
                    }
                )
            except (OSError, KeyError, TypeError, ValueError, RuntimeError) as error:
                frame_reports.append(
                    {
                        "frame": frame,
                        "status": "not_measurable",
                        "failure": {
                            "status": "not_measurable",
                            "code": "REPRODUCTION_COMPARE_ERROR",
                            "reason": str(error),
                        },
                        "within_tolerance": False,
                    }
                )
        context = {
            "task_id": task_id,
            "trial_id": trial_id,
            "program_seed": program_seed,
            "repair_round": repair_round,
            "original_artifact": name,
            "candidate_artifact": name,
        }
        artifacts[name] = _sequence(
            frame_reports,
            expected_frames=artifact_frames,
            context={**context, "frame_policy": policy},
            output=output_root / name.replace(".", "-") / "sequence", deadline=deadline,
        )
    # A native artifact and its GLB are both candidate deliverables.  Comparing
    # each one to the original is not enough: a stale or exploded export could
    # still be individually loadable.  Keep this as a separate semantic chain
    # so format loss is visible without conflating it with missing artifacts.
    format_consistency: dict[str, Any] = {
        "protocol": "l1-reproduction-v1",
        "status": "not_configured",
        "artifacts": {},
        "frames": policy["cross_format_frames"],
        "context": {
            "task_id": task_id,
            "trial_id": trial_id,
            "program_seed": program_seed,
            "repair_round": repair_round,
        },
    }
    original_native = original_artifacts.get("scene.blend")
    original_glb = original_artifacts.get("scene.glb")
    candidate_native = seed_root / "scene.blend"
    candidate_glb = seed_root / "scene.glb"
    if (
        original_native is not None
        and original_glb is not None
        and original_native.is_file()
        and original_glb.is_file()
        and candidate_native.is_file()
        and candidate_glb.is_file()
    ):
        format_consistency["status"] = "ok"
        for label, left_path, right_path in (
            ("original", original_native, original_glb),
            ("candidate", candidate_native, candidate_glb),
        ):
            frame_reports: list[dict[str, Any]] = []
            for index, frame in enumerate(policy["cross_format_frames"]):
                frame_root = (
                    output_root / "cross-format" / label / f"frame-{index:02d}"
                )
                try:
                    left = _observe(
                        blender,
                        left_path,
                        spec_path,
                        frame_root / "native",
                        timeout,
                        inspections=inspections,
                        views=False,
                        deadline=deadline,
                        frame=frame,
                    )
                    right = _observe(
                        blender,
                        right_path,
                        spec_path,
                        frame_root / "glb",
                        timeout,
                        inspections=inspections,
                        views=False,
                        deadline=deadline,
                        frame=frame,
                    )
                    _check_deadline(deadline, "before cross-format comparison")
                    frame_report = _frame(
                        geometry,
                        left["scene"],
                        right["scene"],
                        output=frame_root / "geometry",
                        tolerance_m=tolerance_m,
                        frame=frame, material_tolerance=material_tolerance, deadline=deadline,
                        material_scope="gltf_core_pbr",
                    )
                    _check_deadline(deadline, "after cross-format comparison")
                    frame_reports.append(frame_report)
                except InspectionFailure as error:
                    frame_reports.append(
                        {
                            "frame": frame,
                            "status": "not_measurable",
                            "failure": {
                                "status": error.status,
                                "code": error.code,
                                "reason": error.reason,
                            },
                            "within_tolerance": False,
                        }
                    )
                except (OSError, KeyError, TypeError, ValueError, RuntimeError) as error:
                    frame_reports.append(
                        {
                            "frame": frame,
                            "status": "not_measurable",
                            "failure": {
                                "status": "not_measurable",
                                "code": "REPRODUCTION_FORMAT_COMPARE_ERROR",
                                "reason": str(error),
                            },
                            "within_tolerance": False,
                        }
                    )
            format_consistency["artifacts"][label] = _sequence(
                frame_reports,
                expected_frames=tuple(policy["cross_format_frames"]),
                context={
                    **format_consistency["context"],
                    "format_pair": "native_to_glb",
                    "side": label,
                    "frame_policy": policy,
                },
                output=output_root / "cross-format" / label / "sequence", deadline=deadline,
            )
        statuses = [item.get("status") for item in format_consistency["artifacts"].values()]
        if any(status == "not_measurable" for status in statuses):
            format_consistency["status"] = "not_measurable"
        elif not all(status == "ok" for status in statuses):
            format_consistency["status"] = "failed"
    else:
        format_consistency.update(
            status="not_measurable", reason="Both native and GLB artifacts are required on both sides",
        )
    format_consistency["required_formats"] = {
        "original": {"scene.blend": original_native is not None, "scene.glb": original_glb is not None},
        "candidate": {"scene.blend": candidate_native.is_file(), "scene.glb": candidate_glb.is_file()},
    }
    statuses = [item.get("status") for item in artifacts.values()]
    if format_consistency["status"] != "not_configured":
        statuses.append(format_consistency["status"])
    if not artifacts:
        status = "not_configured"
    elif any(item.get("status") == "not_measurable" for item in artifacts.values()) or "not_measurable" in statuses:
        status = "not_measurable"
    elif all(item.get("status") == "ok" for item in artifacts.values()):
        status = "ok" if format_consistency["status"] in {"ok", "not_configured"} else "failed"
    else:
        status = "failed"
    exhausted = deadline is not None and time.monotonic() >= deadline
    return {
        "protocol": "l1-reproduction-v1",
        "status": "not_measurable" if exhausted else status,
        "budget_exhausted": exhausted,
        "inspections": inspections,
        "artifacts": artifacts,
        "format_consistency": format_consistency,
        "artifact_statuses": statuses,
        "frames": list(frames),
        "frame_policy": policy,
        "cost_seconds": time.monotonic() - started,
    }


__all__ = ["compare_seed_artifacts", "frame_policy"]
