"""Blender submission evaluator used by the end-to-end diagnostic pipeline."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps
from skimage.metrics import structural_similarity

from src.generator.task_adapter import BenchmarkTask

WORKER = Path(__file__).resolve().with_name("blender_inspect.py")


def _ratio(left: float, right: float) -> float:
    if left == right == 0:
        return 1.0
    return min(left, right) / max(left, right) if max(left, right) else 0.0


def _dimension_score(
    candidate: list[float] | None, reference: list[float] | None
) -> float:
    if not candidate or not reference:
        return 0.0
    scores = []
    for actual, expected in zip(candidate, reference, strict=True):
        tolerance = max(abs(expected) * 0.25, 1e-6)
        scores.append(max(0.0, 1.0 - abs(actual - expected) / tolerance))
    return sum(scores) / len(scores)


def _inspect_scene(
    blender: Path,
    scene: Path,
    output: Path,
    render: Path | None,
    timeout: float,
) -> dict[str, Any]:
    command = [
        str(blender),
        "--background",
        "--factory-startup",
        "-noaudio",
        "--python-exit-code",
        "1",
        "--python",
        str(WORKER),
        "--",
        "--scene",
        str(scene),
        "--output",
        str(output),
    ]
    if render is not None:
        command.extend(("--render", str(render)))
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    output.with_suffix(".log").write_text(
        completed.stdout + completed.stderr, encoding="utf-8"
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Blender inspection exited with {completed.returncode}")
    return json.loads(output.read_text(encoding="utf-8"))


def _letterboxed_rgb(path: Path, size: tuple[int, int]) -> Any:
    image = Image.open(path).convert("RGB")
    return __import__("numpy").asarray(
        ImageOps.pad(image, size, method=Image.Resampling.LANCZOS), dtype="uint8"
    )


def _ssim(candidate: Path, reference: Path) -> float:
    with Image.open(reference) as reference_image:
        size = reference_image.size
    left = _letterboxed_rgb(candidate, size)
    right = _letterboxed_rgb(reference, size)
    return float(structural_similarity(left, right, channel_axis=2, data_range=255))


def _render_visibility(path: Path) -> dict[str, float | bool]:
    pixels = np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0
    peak = float(pixels.max())
    visible_fraction = float(np.mean(pixels > (2.0 / 255.0)))
    # A valid dark-background render may have a low mean, but it must contain
    # at least some visible signal. This rejects empty/all-black output without
    # imposing an aesthetic brightness target.
    passed = peak >= 0.01 and visible_fraction >= 0.001
    return {
        "passed": passed,
        "mean_luminance": float(pixels.mean()),
        "std_luminance": float(pixels.std()),
        "peak_luminance": peak,
        "visible_fraction": visible_fraction,
    }


def _matching_images(submission: Path, task: BenchmarkTask) -> list[tuple[Path, Path]]:
    reference_dir = task.root / "solution" / "renders"
    if not reference_dir.is_dir():
        return []
    candidate_by_name = {
        path.name: path
        for path in submission.glob("*.png")
        if path.is_file() and "comparison" not in path.name
    }
    return [
        (candidate_by_name[reference.name], reference)
        for reference in sorted(reference_dir.glob("*.png"))
        if reference.name in candidate_by_name
    ]


def _reference_images(task: BenchmarkTask) -> list[Path]:
    return [task.environment_dir.joinpath(*path.parts) for path in task.image_files]


def _candidate_images(submission: Path, canonical_render: Path) -> list[Path]:
    paths = sorted(
        path
        for path in submission.glob("*.png")
        if path.is_file() and "comparison" not in path.name
    )
    if canonical_render.is_file() and canonical_render not in paths:
        paths.insert(0, canonical_render)
    return paths


def evaluate_blender_submission(
    task: BenchmarkTask,
    submission: Path,
    blender: Path,
    *,
    timeout: float = 900.0,
    vlm_config: Any = None,
) -> dict[str, Any]:
    started = time.monotonic()
    submission = submission.expanduser().resolve()
    evaluation_dir = submission / "evaluation"
    evaluation_dir.mkdir(parents=True, exist_ok=True)
    scene = submission / "scene.blend"
    report: dict[str, Any] = {
        "schema_version": 1,
        "task_id": task.task_id,
        "backend": "blender",
        "status": "failed",
        "programmatic": {},
        "vlm": {"status": "not_requested"},
        "limitations": [],
    }
    if not scene.is_file():
        report["failure"] = "missing scene.blend"
        return report
    candidate_state_path = evaluation_dir / "candidate_scene.json"
    reference_state_path = evaluation_dir / "reference_scene.json"
    canonical_render = evaluation_dir / "authored_main.png"
    try:
        candidate = _inspect_scene(
            blender, scene, candidate_state_path, canonical_render, timeout
        )
        reference_scene = task.root / "solution" / "scene.blend"
        reference = (
            _inspect_scene(
                blender, reference_scene, reference_state_path, None, timeout
            )
            if reference_scene.is_file()
            else None
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        report["failure"] = f"scene inspection failed: {error}"
        report["elapsed_seconds"] = time.monotonic() - started
        return report

    mesh_objects = [obj for obj in candidate["objects"] if obj["type"] == "MESH"]
    topology = (
        sum(
            obj.get("vertices", 0) > 0 and obj.get("nonmanifold_edges", 0) == 0
            for obj in mesh_objects
        )
        / len(mesh_objects)
        if mesh_objects
        else 0.0
    )
    artifact_names = (
        "solution.py",
        "scene.blend",
        "scene.glb",
    )
    artifact_score = sum(
        (submission / name).is_file() for name in artifact_names
    ) / len(artifact_names)
    if reference:
        geometry = _dimension_score(
            candidate.get("global_dimensions"), reference.get("global_dimensions")
        )
        organization = (
            _ratio(candidate["mesh_count"], reference["mesh_count"])
            + _ratio(candidate["object_count"], reference["object_count"])
            + _ratio(candidate["material_count"], reference["material_count"])
        ) / 3
    else:
        geometry = 1.0 if mesh_objects else 0.0
        organization = min(1.0, candidate["object_count"] / 8)

    image_pairs = _matching_images(submission, task)
    image_metrics = [
        {
            "candidate": left.name,
            "reference": right.name,
            "ssim": _ssim(left, right),
        }
        for left, right in image_pairs
    ]
    render_score = (
        sum(item["ssim"] for item in image_metrics) / len(image_metrics)
        if image_metrics
        else 0.0
    )
    camera_score = 1.0 if candidate["camera_count"] > 0 else 0.0
    render_visibility = (
        _render_visibility(canonical_render)
        if canonical_render.is_file()
        else {
            "passed": False,
            "mean_luminance": 0.0,
            "std_luminance": 0.0,
            "peak_luminance": 0.0,
            "visible_fraction": 0.0,
        }
    )
    execution_gate = bool(
        mesh_objects
        and camera_score
        and canonical_render.is_file()
        and render_visibility["passed"]
    )
    programmatic_score = (
        100.0
        * execution_gate
        * (
            0.25 * geometry
            + 0.20 * topology
            + 0.20 * organization
            + 0.20 * render_score
            + 0.15 * artifact_score
        )
    )
    report["programmatic"] = {
        "score": programmatic_score,
        "execution_gate": execution_gate,
        "geometry_dimension_score": geometry,
        "topology_valid_ratio": topology,
        "organization_score": organization,
        "render_ssim_score": render_score,
        "artifact_completeness": artifact_score,
        "canonical_render_visibility": render_visibility,
        "candidate_scene": {
            key: candidate[key]
            for key in (
                "object_count",
                "mesh_count",
                "camera_count",
                "light_count",
                "material_count",
                "global_dimensions",
            )
        },
        "image_metrics": image_metrics,
    }
    if not image_pairs:
        report["limitations"].append(
            "No same-name candidate/reference render pairs; render score is zero."
        )
    if not render_visibility["passed"]:
        report["limitations"].append(
            "Canonical render is effectively black; execution gate failed."
        )
    report["limitations"].append(
        "Pilot programmatic score is a generic diagnostic, not the frozen task-specific leaderboard metric."
    )

    if vlm_config is not None:
        from .vlm import evaluate_with_vlm

        try:
            judgment = evaluate_with_vlm(
                vlm_config,
                task.instruction,
                _reference_images(task),
                _candidate_images(submission, canonical_render),
            )
            report["vlm"] = {"status": "passed", **judgment}
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            report["vlm"] = {
                "status": "failed",
                "error": f"{type(error).__name__}: {error}",
            }
    report["status"] = "passed" if execution_gate else "failed"
    report["elapsed_seconds"] = time.monotonic() - started
    (evaluation_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
