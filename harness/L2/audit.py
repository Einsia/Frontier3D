"""Controller-side validation of evaluator-owned facts and decoded image pixels."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from harness.common.attempt_log import sha256
from src.evaluator.spec import relative_path

AUDIT_VERSION = "l2-integrity-v2"


def regular_file(root: Path, name: str) -> Path:
    path = root / relative_path(name)
    # Check before resolving; resolving first erases symlink evidence.
    current = root
    for part in Path(name).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Symlink artifact: {name}")
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"Missing, empty or unsafe artifact: {name}")
    if path.stat().st_nlink != 1:
        raise ValueError(f"Hard-linked artifact: {name}")
    return path


def image_pixels(path: Path):
    with Image.open(path) as image:
        image.load()
        pixels = np.asarray(image.convert("RGBA"))
        metadata = {"size": list(image.size), "mode": image.mode, "format": image.format,
                    "pixel_sha256": hashlib.sha256(str(pixels.shape).encode() + pixels.tobytes()).hexdigest()}
    return pixels, metadata


def artifact_state(root: Path, required: tuple[str, ...], views: tuple[dict, ...]):
    artifacts, failures = {}, []
    expected = {v["artifact"]: v["resolution"] for v in views}
    for name in required:
        try:
            path = regular_file(root, name)
            item = {"sha256": sha256(path), "bytes": path.stat().st_size}
            artifacts[name] = item
            if name.endswith(".py"):
                compile(path.read_bytes(), name, "exec")
            elif name in expected:
                _, info = image_pixels(path)
                item.update(info)
                if info["size"] != expected[name] or info["format"] != "PNG":
                    raise ValueError(f"Invalid native PNG dimensions or format: {name}")
        except (OSError, ValueError, SyntaxError) as error:
            failures.append(str(error))
    return artifacts, failures


def compare_images(candidate: Path, replay: Path, mean_limit: float, p99_limit: float):
    left, left_info = image_pixels(candidate)
    right, right_info = image_pixels(replay)
    result = {"candidate": left_info, "replay": right_info, "passed": False}
    if left.shape != right.shape:
        result["reason"] = "Image dimensions differ"
        return result
    error = np.abs(left.astype(np.float64) - right.astype(np.float64)) / 255
    result.update(mean_error=float(error.mean()), p99_error=float(np.quantile(error, .99)),
                  mean_limit=mean_limit, p99_limit=p99_limit)
    result["passed"] = result["mean_error"] <= mean_limit and result["p99_error"] <= p99_limit
    return result


def scene_audit(facts: dict, baseline: dict | None, *, edit: bool) -> dict:
    scene = facts["scene"]
    failures = []
    audit = scene.get("audit", {})
    for field in ("drivers", "autoexec_texts", "script_nodes", "compositor_images",
                  "linked_libraries", "external_resources"):
        if field not in audit or audit[field]:
            failures.append({"check": field, "details": audit.get(field, "missing evidence")})
    if scene.get("has_real_geometry") is not True:
        failures.append({"check": "real_geometry"})
    inherited = set()
    if edit:
        if baseline is None:
            failures.append({"check": "baseline", "details": "missing baseline"})
        else:
            source = baseline["scene"]
            for name, before in source["objects"].items():
                after = scene["objects"].get(name)
                if after is None:
                    failures.append({"check": "preservation", "object": name, "field": "missing"})
                    continue
                unchanged = True
                if before.get('type') == 'MESH' and any(not before.get(f) or not after.get(f)
                        for f in ('geometry_sha256', 'evaluated_geometry_sha256', 'data_sha256')):
                    failures.append({'check': 'preservation', 'object': name, 'field': 'missing_geometry_evidence'})
                for field in ("type", "parent", "location", "rotation", "scale", "visible_render",
                              "geometry_sha256", "evaluated_geometry_sha256", "data_sha256",
                              "material_sha256", "constraints_sha256"):
                    left, right = before.get(field), after.get(field)
                    same = left == right
                    if field in {"location", "rotation", "scale"} and left is not None and right is not None:
                        same = bool(np.allclose(left, right, atol=1e-5, rtol=0))
                    if not same:
                        unchanged = False
                        failures.append({"check": "preservation", "object": name, "field": field})
                if unchanged and name in source.get("billboard_suspects", []):
                    inherited.add(name)
            for field in ("world_sha256", "render", "render_settings_sha256"):
                if source.get(field) != scene.get(field):
                    failures.append({"check": "preservation", "field": field})
            if not source.get('render_settings_sha256') or not scene.get('render_settings_sha256'):
                failures.append({'check': 'preservation', 'field': 'missing_render_settings'})
    suspects = sorted(set(scene.get("billboard_suspects", [])) - inherited)
    if suspects:
        failures.append({"check": "billboard_review", "objects": suspects})
    return {"version": AUDIT_VERSION, "passed": not failures, "failures": failures,
            "inherited_texture_planes": sorted(inherited),
            "limitations": ["Billboard detection is a conservative low-poly image-texture heuristic; flagged new planes require review.",
                            "This version does not prove semantic correctness or detect every possible cheating strategy."]}


def record_digest(record: dict) -> str:
    payload = {k: v for k, v in record.items() if k != "record_sha256"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(",", ":")).encode()).hexdigest()
