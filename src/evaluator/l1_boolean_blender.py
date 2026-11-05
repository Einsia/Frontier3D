"""Independent L1 solid-intersection worker, consuming only hashed mesh packets."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import sys
import traceback
from itertools import pairwise
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def sibling(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INSPECT = sibling("l1_blender")
KERNEL = sibling("l1_mesh")
WINDING = sibling("l1_volume_math")


def load(record, trusted_root):
    if record.get("volume_reliable") is not True:
        raise ValueError(
            "Volume comparison requires independently validated source solids"
        )
    packet = record["mesh_payload"]
    path = Path(packet["path"])
    if (
        packet.get("coordinate_space") != "world_metres"
        or path.is_symlink()
        or not path.resolve().is_relative_to(trusted_root)
    ):
        raise ValueError("Untrusted mesh coordinate space or payload location")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != packet["sha256"]:
        raise ValueError("Mesh packet hash mismatch")
    with np.load(io.BytesIO(content), allow_pickle=False) as data:
        vertices, triangles = data["vertices_m"], data["triangles"]
    if (
        vertices.ndim != 2
        or vertices.shape[1:] != (3,)
        or not np.isfinite(vertices).all()
        or triangles.ndim != 2
        or triangles.shape[1:] != (3,)
        or not len(triangles)
        or triangles.dtype.kind not in "iu"
        or (triangles < 0).any()
        or (triangles >= len(vertices)).any()
    ):
        raise ValueError("Invalid mesh arrays")
    return vertices.astype(float), triangles.astype(np.int64)


def create_object(name, vertices, triangles):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices.tolist(), [], triangles.tolist())
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def volume_bounds(left, right, low, high, levels):
    extent = high - low
    if np.any(extent <= 0):
        return [
            {
                "resolution": n,
                "intersection_lower_m3": 0.0,
                "intersection_upper_m3": 0.0,
                "uncertain_cells": 0,
                "method": "zero_aabb_overlap_volume",
            }
            for n in levels
        ]
    meshes = (left, right)
    trees = [
        BVHTree.FromPolygons(v.tolist(), t.tolist(), all_triangles=True)
        for v, t in meshes
    ]
    guard = float(
        32
        * np.finfo(np.float32).eps
        * max(1e-3, *(float(np.abs(v).max()) for v, t in meshes))
    )
    rows = []
    for resolution in levels:
        axes = [
            low[i] + (np.arange(resolution) + 0.5) * extent[i] / resolution
            for i in range(3)
        ]
        centers = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
        half_diagonal = float(np.linalg.norm(extent / resolution) / 2)
        states = []
        for (vertices, triangles), tree in zip(meshes, trees, strict=True):
            distances = np.array([tree.find_nearest(Vector(p))[3] for p in centers])
            far = distances > half_diagonal + guard
            state = np.full(len(centers), -1, dtype=np.int8)
            state[far] = WINDING.winding_classification(
                vertices, triangles, centers[far]
            )
            states.append(state)
        inside = (states[0] == 1) & (states[1] == 1)
        possible = (states[0] != 0) & (states[1] != 0)
        cell_volume = float(np.prod(extent / resolution))
        rows.append(
            {
                "resolution": resolution,
                "cells": len(centers),
                "intersection_lower_m3": int(inside.sum()) * cell_volume,
                "intersection_upper_m3": int(possible.sum()) * cell_volume,
                "uncertain_cells": int(possible.sum() - inside.sum()),
                "cell_half_diagonal_m": half_diagonal,
                "float32_distance_guard_m": guard,
                "method": "nearest_surface_cell_bounds_plus_winding_v1",
            }
        )
    return rows


def compare(manifest):
    trusted_root = Path(manifest["trusted_root"]).resolve()
    left, right = (
        load(manifest["left"], trusted_root),
        load(manifest["right"], trusted_root),
    )
    levels = manifest["grid_levels"]
    if (
        not levels
        or any(type(n) is not int or not 2 <= n <= 64 for n in levels)
        or levels != sorted(set(levels))
    ):
        raise ValueError("Invalid frozen volume grid levels")
    low = np.maximum(left[0].min(axis=0), right[0].min(axis=0))
    high = np.minimum(left[0].max(axis=0), right[0].max(axis=0))
    # One common numerical origin shift, never independent per-part alignment.
    origin = (left[0].mean(axis=0) + right[0].mean(axis=0)) / 2
    left, right = (left[0] - origin, left[1]), (right[0] - origin, right[1])
    va, vb = KERNEL.triangulated_volume(*left), KERNEL.triangulated_volume(*right)
    if va <= 0 or vb <= 0:
        raise ValueError("Source solid volume must be positive")
    derived = None
    if np.any(high <= low):
        intersection = 0.0
        derived = {"kind": "disjoint_or_contacting_bounds"}
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        a, b = create_object("left", *left), create_object("right", *right)
        b.hide_render = True
        modifier = a.modifiers.new("independent_intersection", "BOOLEAN")
        modifier.operation, modifier.solver, modifier.object = "INTERSECT", "EXACT", b
        facts, _ = INSPECT._collect(KERNEL.GEOMETRY_POLICY)
        derived = facts["objects"][a.name]
        if derived["faces"] == 0:
            intersection = 0.0
            derived["kind"] = "empty_boolean_intersection"
        elif set(derived["invalid_reasons"]) - {"disconnected"}:
            return {
                "status": "not_measurable",
                "reason": "Boolean intersection failed derived-mesh validation",
                "derived": derived,
            }
        else:
            # An intersection may contain multiple disconnected pieces even
            # when each input is one valid solid; sum their signed volume.
            intersection = derived["signed_volume_integral_m3"]
    guard_volume = max(va, vb) * 1e-5
    if not -guard_volume <= intersection <= min(va, vb) + guard_volume:
        return {
            "status": "not_measurable",
            "reason": "Boolean volume violates set bounds",
            "derived": derived,
        }
    unclamped = intersection
    intersection = max(0.0, min(intersection, va, vb))
    rows = volume_bounds(left, right, low - origin, high - origin, levels)
    consistent = all(
        row["intersection_lower_m3"] - guard_volume
        <= intersection
        <= row["intersection_upper_m3"] + guard_volume
        for row in rows
    )
    widths = [r["intersection_upper_m3"] - r["intersection_lower_m3"] for r in rows]
    union = va + vb - intersection
    return {
        "status": "ok" if consistent else "not_measurable",
        "method": "blender_exact_boolean_with_independent_cell_bounds_v1",
        "reason": ""
        if consistent
        else "Boolean and independently sampled cell bounds disagree",
        "coordinate_space": "world_metres",
        "alignment": "none",
        "common_numeric_origin_m": origin.tolist(),
        "derived_coordinate_space": "world_metres_minus_common_numeric_origin",
        "left_volume_m3": va,
        "right_volume_m3": vb,
        "intersection_volume_m3": intersection,
        "unclamped_boolean_volume_m3": unclamped,
        "set_bound_guard_m3": guard_volume,
        "union_volume_m3": union,
        "volume_iou": intersection / union,
        "interference_at_solver_precision": "positive_volume"
        if intersection > 0
        else "none_detected",
        "not_a_task_tolerance_decision": True,
        "grid_bounds": rows,
        "grid_widths_m3": widths,
        "bounds_narrowing": len(rows) > 1
        and all(b <= a + guard_volume for a, b in pairwise(widths)),
        "intersection_bounds_m": [low.tolist(), high.tolist()],
        "blender_version": bpy.app.version_string,
        "derived": derived,
        "limitations": [
            "EXACT is Blender's solver selection, not an infinite-precision guarantee.",
            "Boundary cells remain uncertain; no-hit samples alone never establish no interference.",
            "set_bound_guard_m3 is a solver sanity guard, not a calibrated physical allowance for penetration.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    result = compare(json.loads(args.manifest.read_text(encoding="utf-8")))
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except BaseException:  # noqa: BLE001 - dedicated worker failure boundary
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
