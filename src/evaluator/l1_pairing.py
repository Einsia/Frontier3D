"""One-to-one, world-coordinate L1 scene geometry comparison.

Object names are provenance labels, never identity evidence. This is shared
infrastructure for native/GLB and all-seed comparison; materials and animated
states must be checked by their own layers before claiming full reproduction.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .l1_numeric import tolerance_measurement
from .l1_surface import compare_surfaces, load_surface
from .l1_volume import compare_volumes


def _delivery(scene: dict, *, surface_only=False) -> list[tuple[str, dict]]:
    if (
        not scene.get("geometry_policy")
        or scene.get("has_instances")
        or scene.get("unsupported_geometry")
    ):
        raise ValueError("Scene lacks complete supported L1 geometry evidence")
    parts = [
        (name, item)
        for name, item in scene["objects"].items()
        if item.get("entity_scope") == "delivery_geometry"
    ]
    if any(
        (not surface_only and not item.get("volume_reliable")) or "mesh_payload" not in item
        for _, item in parts
    ):
        raise ValueError("Unvalidated delivery solid in geometry comparison")
    return sorted(parts)


def compare_scene_geometry(
    left: dict,
    right: dict,
    *,
    trusted_root: Path,
    tolerance_m: float,
    sample_levels=(256, 1024, 4096),
    convergence_m=1e-5,
    seed=0,
    blender: Path | None = None,
    output: Path | None = None,
    minimum_volume_iou: float | None = None,
    volume_timeout=120.0,
    volume_grid_levels=(8, 16, 32),
    volume_new_session=True,
    surface_only=False,
) -> dict:
    if surface_only and minimum_volume_iou is not None:
        raise ValueError('Surface-only comparison cannot validate solid volume')
    if not np.isfinite(tolerance_m) or tolerance_m <= 0:
        raise ValueError("Positive world-surface tolerance required")
    if minimum_volume_iou is not None and (
        not np.isfinite(minimum_volume_iou)
        or not 0 <= minimum_volume_iou <= 1
        or blender is None
        or output is None
    ):
        raise ValueError(
            "A declared IoU threshold, Blender and output are required for volume matching"
        )
    try:
        a, b = _delivery(left, surface_only=surface_only), _delivery(right, surface_only=surface_only)
        meshes_a = [load_surface(item["mesh_payload"], trusted_root, surface_only=surface_only) for _, item in a]
        meshes_b = [load_surface(item["mesh_payload"], trusted_root, surface_only=surface_only) for _, item in b]
    except (OSError, ValueError, KeyError) as error:
        return {
            "status": "not_measurable",
            "geometry_match": False,
            "reason": str(error),
        }
    details, adjacency = [], [[] for _ in a]
    unavailable = False
    for i, (name_a, item_a) in enumerate(a):
        bound_a = np.array(
            [meshes_a[i].vertices.min(axis=0), meshes_a[i].vertices.max(axis=0)]
        )
        for j, (name_b, item_b) in enumerate(b):
            bound_b = np.array(
                [meshes_b[j].vertices.min(axis=0), meshes_b[j].vertices.max(axis=0)]
            )
            bbox_error = float(np.max(np.abs(bound_a - bound_b)))
            pair = {
                "left": name_a,
                "right": name_b,
                "bounds_error_m": bbox_error,
                "status": "ok",
                "within_tolerance": False,
            }
            details.append(pair)
            _, bounds_decision = tolerance_measurement(bound_a, bound_b, tolerance_m)
            if not bounds_decision["within_tolerance"]:
                pair["reason"] = (
                    "World bounds already disprove the declared surface tolerance"
                )
                continue
            surface = compare_surfaces(
                meshes_a[i],
                meshes_b[j],
                levels=sample_levels,
                seed=seed,
                convergence_m=convergence_m,
            )
            pair["surface"] = surface
            maximum = surface["levels"][-1]["sampled_max_m"]
            _, distance_decision = tolerance_measurement(maximum, 0.0, tolerance_m)
            if not distance_decision["within_tolerance"]:
                pair["reason"] = "Measured point-to-surface distance exceeds tolerance"
                continue
            if not surface["converged"]:
                pair.update(
                    status="not_measurable", reason="Surface sampling did not converge"
                )
                unavailable = True
                continue
            if minimum_volume_iou is not None:
                volume = compare_volumes(
                    item_a,
                    item_b,
                    trusted_root=trusted_root,
                    output=output / f"pair-{i:03d}-{j:03d}",
                    blender=blender,
                    timeout=volume_timeout,
                    grid_levels=volume_grid_levels,
                    new_session=volume_new_session,
                )
                pair["volume"] = volume
                if volume["status"] != "ok":
                    pair.update(
                        status="not_measurable",
                        reason="Intersection volume unavailable",
                    )
                    unavailable = True
                    continue
                if volume["volume_iou"] < minimum_volume_iou:
                    pair["reason"] = "Measured volume IoU below the declared threshold"
                    continue
            pair["within_tolerance"] = True
            adjacency[i].append(j)
    owners = {}

    def augment(i, seen):
        for j in adjacency[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owners or augment(owners[j], seen):
                owners[j] = i
                return True
        return False

    for i in sorted(range(len(a)), key=lambda k: len(adjacency[k])):
        augment(i, set())
    matched_left = set(owners.values())
    matched = bool(a) and len(a) == len(b) == len(owners)
    return {
        "status": "not_measurable" if unavailable and not matched else "ok",
        "method": "global_one_to_one_world_geometry_v1",
        "surface_only": surface_only,
        "surface_diagnostics": {'left': [m.surface_diagnostics for m in meshes_a],
                                'right': [m.surface_diagnostics for m in meshes_b]},
        "alignment": "none",
        "geometry_match": matched,
        "left_parts": len(a),
        "right_parts": len(b),
        "matched_parts": len(owners),
        "matches": [
            {"left": a[i][0], "right": b[j][0]} for j, i in sorted(owners.items())
        ],
        "unmatched_left": [
            name for i, (name, _) in enumerate(a) if i not in matched_left
        ],
        "unmatched_right": [name for j, (name, _) in enumerate(b) if j not in owners],
        "tolerance_m": tolerance_m,
        "minimum_volume_iou": minimum_volume_iou,
        "pair_evidence": details,
        "not_assessed": [
            "materials",
            "animation",
            "hierarchy",
            "dependencies",
            "task-specific semantic features",
        ],
        "limitations": [
            "Surface maxima are finite-sample diagnostics, not continuous Hausdorff bounds.",
            "Thresholds must be frozen/calibrated by the calling protocol.",
        ],
    }
