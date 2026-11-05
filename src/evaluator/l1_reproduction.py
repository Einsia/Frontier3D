"""Semantic comparison helpers for L1 original-to-rerun reproduction.

Geometry matching is delegated to ``l1-geometry-v1``.  This module adds the
separate material and animation-state layer and keeps an unavailable layer
distinct from a measurable mismatch.  Object names are only provenance labels;
the geometry report supplies the one-to-one pairing.
"""

from __future__ import annotations

import json
import math
from typing import Any

REPRODUCTION_PROTOCOL = "l1-reproduction-v1"
_DEFAULT_COLOR_TOLERANCE = 1e-6


def _compiled_diagnostic(left, right, geometry_config, material_scope, tolerance):
    """Supplement the formal constant gate; do not upgrade or override it.

    The default reproduction_frame/state_return callers already run inside the
    deadline-controlled compute process. Keep finite sampling explicit and
    independent of the (separately calibrated) geometry sampling policy.
    """
    if geometry_config is not None and not geometry_config.get('reproduction_diagnostics', True):
        return {'protocol':'l1-compiled-field-comparison-v1','status':'not_in_scope','hard_gate':False,
                'reason':'Image policy uses native appearance; optional shader diagnostics are outside validity'}
    from .l1_field_comparison import compare_compiled_material_fields

    if geometry_config is None or material_scope != 'native_constant_principled':
        return {'protocol': 'l1-compiled-field-comparison-v1', 'status': 'not_measurable', 'hard_gate': False,
                'scope': 'native_compiled_principled_input_fields',
                'reason': 'Trusted native comparison required; glTF normalization is not assessed'}
    return compare_compiled_material_fields(
        left, right, trusted_root=geometry_config['trusted_root'], parameter_tolerance=tolerance,
        surface_tolerance_m=geometry_config['surface_tolerance_m'], levels=(64, 256), seed=geometry_config['seed'],
    )


def _colors(scene: dict[str, Any], name: str, *, shader=False) -> list[list[float]] | None:
    objects = scene.get("objects")
    if not isinstance(objects, dict) or not isinstance(objects.get(name), dict):
        return None
    if shader:
        evidence = objects[name].get("material_color_evidence")
        if not isinstance(evidence, dict) or evidence.get("protocol") != "l1-material-color-v1" or evidence.get("status") != "ok":
            return None
        values = evidence.get("colors")
        if values is None:
            return None
    else:
        values = objects[name].get("material_colors")
    if values is None:
        return []
    if not isinstance(values, list):
        return None
    result: list[list[float]] = []
    for color in values:
        if not isinstance(color, (list, tuple)) or not color:
            return None
        row = [float(value) for value in color]
        if any(not math.isfinite(value) for value in row):
            return None
        result.append(row)
    return sorted(result)


def _state_signature(scene: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Keep frame-state evidence compact while retaining world pose/materials."""
    objects = scene.get("objects")
    if not isinstance(objects, dict):
        return None
    signature = []
    for item in objects.values():
        if not isinstance(item, dict):
            return None
        values = {
            "type": item.get("type"),
            "entity_scope": item.get("entity_scope"),
            "visible_render": item.get("visible_render"),
            "dimensions": item.get("dimensions"),
            "matrix_world": item.get("matrix_world"),
            "material_colors": item.get("material_colors"),
        }
        signature.append(values)
    return sorted(signature, key=lambda value: json.dumps(value, sort_keys=True))


def compare_materials(
    left_scene: dict[str, Any],
    right_scene: dict[str, Any],
    matches: list[dict[str, str]],
    *,
    tolerance: float = _DEFAULT_COLOR_TOLERANCE,
    geometry_config: dict | None = None,
    material_scope: str = "native_constant_principled",
) -> dict[str, Any]:
    """Compare base-color slots; legacy viewport facts remain labelled proxies."""
    if isinstance(tolerance, bool) or not math.isfinite(float(tolerance)) or tolerance < 0:
        raise ValueError("material tolerance must be finite and nonnegative")
    if any("material_surface" in scene.get("objects", {}).get(match.get(side), {})
           for match in matches for scene, side in ((left_scene, "left"), (right_scene, "right"))):
        from .l1_materials import compare_material_surfaces
        details = []
        for match in matches:
            left = left_scene['objects'].get(match['left'], {})
            right = right_scene['objects'].get(match['right'], {})
            if geometry_config is None:
                result = {"status": "not_measurable", "reason": "Trusted material surface comparison context missing"}
            else:
                result = compare_material_surfaces(
                    left, right,
                    trusted_root=geometry_config["trusted_root"], scope=material_scope, parameter_tolerance=tolerance,
                    surface_tolerance_m=geometry_config["surface_tolerance_m"], levels=geometry_config["surface_levels"],
                    convergence_m=geometry_config["surface_convergence_m"], seed=geometry_config["seed"],
                    surface_only=geometry_config.get('surface_only', False),
                )
            if any('material_compiled_fields' in item for item in (left, right)):
                result['compiled_field_diagnostic'] = _compiled_diagnostic(left, right, geometry_config, material_scope, tolerance)
            details.append({**match, "color_source": "shader_base_color", "material_source": "effective_surface_parameters", **result})
        statuses = [item["status"] for item in details]
        status = "failed" if "failed" in statuses else "not_measurable" if "not_measurable" in statuses else "ok"
        return {"protocol": REPRODUCTION_PROTOCOL, "status": status, "matches": details,
                "matched_parts": len(matches), "material_match": status == "ok", "tolerance": float(tolerance),
                "scope": material_scope, "not_assessed": sorted({value for item in details for value in item.get("not_assessed", [])})}
    details: list[dict[str, Any]] = []
    unavailable = False
    passed = True
    for match in matches:
        left_name, right_name = match.get("left"), match.get("right")
        def has_shader(scene, name):
            objects = scene.get("objects")
            return isinstance(objects, dict) and isinstance(objects.get(name), dict) and "material_color_evidence" in objects[name]
        shader = has_shader(left_scene, left_name) or has_shader(right_scene, right_name)
        # A new shader observation must not be compared to an old viewport
        # proxy, or fall back when the actual graph cannot be observed.
        left = _colors(left_scene, left_name, shader=shader)
        right = _colors(right_scene, right_name, shader=shader)
        detail: dict[str, Any] = {"left": left_name, "right": right_name,
                                  "color_source": "shader_base_color" if shader else "legacy_diffuse_proxy"}
        if left is None or right is None:
            detail.update(status="not_measurable", reason="Material evidence is absent or invalid")
            unavailable = True
        elif len(left) != len(right):
            detail.update(
                status="failed",
                reason="Material slot count differs",
                left_slots=len(left),
                right_slots=len(right),
            )
            passed = False
        else:
            maximum = max(
                (abs(a - b) for left_row, right_row in zip(left, right) for a, b in zip(left_row, right_row)),
                default=0.0,
            )
            same_shape = all(len(a) == len(b) for a, b in zip(left, right))
            within = same_shape and maximum <= float(tolerance)
            detail.update(
                status="ok" if within else "failed",
                max_abs_error=maximum,
                tolerance=float(tolerance),
                within_tolerance=within,
            )
            passed = passed and within
        details.append(detail)
    status = "not_measurable" if unavailable else "ok" if passed else "failed"
    return {
        "protocol": REPRODUCTION_PROTOCOL,
        "status": status,
        "matches": details,
        "matched_parts": len(matches),
        "material_match": status == "ok",
        "tolerance": float(tolerance),
        "scope": "base_color_slots_only",
        "not_assessed": ["other_shader_parameters", "general_node_graphs", "textures", "face_assignments"],
    }


def compare_frame(
    left_scene: dict[str, Any],
    right_scene: dict[str, Any],
    geometry_report: dict[str, Any],
    *,
    frame: int,
    material_tolerance: float = _DEFAULT_COLOR_TOLERANCE,
    geometry_config: dict | None = None,
    material_scope: str = "native_constant_principled",
) -> dict[str, Any]:
    """Combine one geometry pairing and its material evidence for one frame."""
    if type(frame) is not int or frame < 0:
        raise ValueError("frame must be a nonnegative integer")
    evidence = geometry_report.get("evidence", geometry_report)
    matches = evidence.get("matches", []) if isinstance(evidence, dict) else []
    if not isinstance(matches, list):
        matches = []
    materials = compare_materials(
        left_scene,
        right_scene,
        matches,
        tolerance=material_tolerance,
        geometry_config=geometry_config, material_scope=material_scope,
    )
    geometry_ok = (
        geometry_report.get("status") == "ok"
        and evidence.get("geometry_match") is True
    )
    geometry_unavailable = geometry_report.get("status") in {
        "not_measurable", "not_implemented", "infrastructure_error", "not_configured",
    }
    status = "not_measurable" if geometry_unavailable else "ok" if geometry_ok and materials["status"] == "ok" else (
        "not_measurable"
        if geometry_report.get("status") != "failed" and materials["status"] == "not_measurable"
        else "failed"
    )
    return {
        "frame": frame,
        "status": status,
        "geometry": geometry_report,
        "materials": materials,
        "candidate_state": _state_signature(right_scene),
        "within_tolerance": status == "ok",
    }


def compare_sequence(
    frames: list[dict[str, Any]],
    *,
    expected_frames: tuple[int, ...] = (1, 61, 1),
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a frame sequence and expose round-trip and seed provenance."""
    actual = tuple(item.get("frame") for item in frames)
    sequence_valid = actual == expected_frames
    statuses = [item.get("status") for item in frames]
    all_passed = sequence_valid and bool(frames) and all(status == "ok" for status in statuses)
    round_trip = None
    if len(expected_frames) >= 2 and expected_frames[0] == expected_frames[-1] == 1:
        sides = (context or {}).get("state_returns", {})
        valid = isinstance(sides, dict) and set(sides) == {"original", "seed"} and all(
            isinstance(item, dict) and item.get("protocol") == "l1-state-return-v1"
            and item.get("scope") == "first_to_last_world_geometry_by_session_identity"
            and isinstance(item.get("session"), dict) and item["session"].get("session_id")
            and item.get("status") in {"ok", "failed", "not_measurable"}
            for item in sides.values()
        )
        return_status = "not_measurable" if not valid or any(item["status"] == "not_measurable" for item in sides.values()) else (
            "ok" if all(item["status"] == "ok" for item in sides.values()) else "failed"
        )
        round_trip = {
            "status": return_status, "restored_frame": return_status == "ok" and sequence_valid,
            "method": "same_session_fixed_identity_world_surface_return", "sides": sides,
            "legacy_signature_equal_diagnostic": bool(frames) and frames[0].get("candidate_state") == frames[-1].get("candidate_state"),
        }
        if not valid:
            round_trip["reason"] = "Bound single-session return evidence is missing; independent frame signatures are insufficient"
        statuses.append(return_status)
        all_passed = all_passed and return_status == "ok"
    return {
        "protocol": REPRODUCTION_PROTOCOL,
        "status": "not_measurable" if not frames or "not_measurable" in statuses
        else "ok" if all_passed else "failed",
        "sequence": list(actual),
        "expected_sequence": list(expected_frames),
        "sequence_valid": sequence_valid,
        "frames": frames,
        "round_trip": round_trip,
        "context": context or {},
    }


__all__ = [
    "REPRODUCTION_PROTOCOL",
    "compare_frame",
    "compare_materials",
    "compare_sequence",
]
