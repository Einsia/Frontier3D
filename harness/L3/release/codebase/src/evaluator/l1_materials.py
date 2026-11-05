"""Compare effective materials bound to trusted world-surface regions.

Slot/node names are provenance, not identity. Region comparison is bidirectional
point-to-triangle sampling, with explicit convergence, never a continuous bound.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np

from .l1_material_probe import PROTOCOL
from .l1_surface import SurfaceMesh, load_surface, sample_surface, surface_distances

SCOPES = {"native_constant_principled", "gltf_core_pbr"}
CORE = {"Base Color", "Metallic", "Roughness", "Alpha"}


def _descriptor(slot, scope):
    if not isinstance(slot, dict) or slot.get("status") != "ok":
        raise ValueError("Unsupported or absent effective shader evidence")
    kind, values, flags = slot["kind"], slot["parameters"], slot["flags"]
    if kind not in {"unassigned", "constant_principled"} or not isinstance(values, dict) or not isinstance(flags, dict):
        raise ValueError("Invalid shader descriptor")
    if kind == "unassigned":
        if values or flags:
            raise ValueError("Invalid unassigned descriptor")
        return {"kind": kind, "parameters": {}, "flags": {}}
    if not CORE <= values.keys():
        raise ValueError("Missing core PBR parameters")
    if np.shape(values["Base Color"]) not in {(3,), (4,)} or any(np.shape(values[key]) != () for key in CORE - {"Base Color"}):
        raise ValueError("Invalid core PBR socket shape")
    if type(flags.get("use_backface_culling")) is not bool:
        raise ValueError("Missing or invalid backface flag")
    for value in values.values():
        array = np.asarray(value)
        if array.dtype.kind not in "fiu" or array.ndim > 1 or not array.size or not np.isfinite(array).all():
            raise ValueError("Invalid numeric shader parameter")
    if scope == "gltf_core_pbr":
        emission = np.asarray(values["Emission Color"], dtype=float)[:3] * float(values["Emission Strength"])
        values = {**{key: values[key] for key in sorted(CORE)}, "emission_rgb": emission.tolist()}
        flags = {"use_backface_culling": flags["use_backface_culling"]}
    return {"kind": kind, "parameters": values, "flags": flags}


def _equal(left, right, tolerance):
    if left["kind"] != right["kind"] or left["flags"] != right["flags"]:
        return False
    a, b = left["parameters"], right["parameters"]
    return a.keys() == b.keys() and all(
        np.shape(a[key]) == np.shape(b[key]) and np.max(np.abs(np.asarray(a[key]) - b[key])) <= tolerance
        for key in a
    )


def _load(item, root, scope, *, surface_only=False):
    evidence = item["material_surface"]
    if evidence["protocol"] != PROTOCOL:
        raise ValueError("Invalid material evidence protocol")
    surface = load_surface(item["mesh_payload"], root, surface_only=surface_only)
    assignment = evidence["assignment"]
    if assignment["geometry_sha256"] != item["mesh_payload"]["sha256"]:
        raise ValueError("Material assignment bound to a different geometry payload")
    path = Path(assignment["path"])
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Material assignment escapes trusted inspection root")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != assignment["sha256"]:
        raise ValueError("Material assignment hash mismatch")
    with np.load(io.BytesIO(content), allow_pickle=False) as data:
        if set(data.files) != {"triangle_material_indices"}:
            raise ValueError("Invalid material assignment payload")
        indices = data["triangle_material_indices"]
    slots = evidence["slots"]
    if not isinstance(slots, list) or not slots or indices.shape != (surface.source_triangle_count,) or indices.dtype.kind not in "iu":
        raise ValueError("Material assignment length/type mismatch")
    if (indices < 0).any() or (indices >= len(slots)).any():
        raise ValueError("Material assignment references missing slot")
    indices = indices[surface.source_triangle_indices]
    groups = {}
    for index in np.unique(indices):
        descriptor = _descriptor(slots[int(index)], scope)
        key = json.dumps(descriptor, sort_keys=True, allow_nan=False)
        if key not in groups:
            groups[key] = {"descriptor": descriptor, "mask": indices == index, "slots": [int(index)]}
        else:
            groups[key]["mask"] |= indices == index
            groups[key]["slots"].append(int(index))
    return surface, list(groups.values())


def _region(surface, mask):
    triangles = surface.triangles[mask]
    # Do not include vertices outside the region in the distance sentinels.
    indices, inverse = np.unique(triangles, return_inverse=True)
    return SurfaceMesh(surface.vertices[indices], inverse.reshape(-1, 3))


def compare_material_surfaces(left, right, *, trusted_root, scope, parameter_tolerance,
                              surface_tolerance_m, levels=(256, 1024, 4096), convergence_m=1e-5, seed=0,
                              pose_alignment=False, surface_only=False):
    report = {"protocol": PROTOCOL, "status": "not_measurable", "scope": scope, "regions": [],
              "parameter_tolerance": parameter_tolerance, "surface_tolerance_m": surface_tolerance_m,
              "not_assessed": ["general_shader_graphs", "texture_pixels_and_uv_mapping", "volumes_and_displacement"]}
    if scope == "gltf_core_pbr":
        report["not_assessed"].append("gltf_material_extensions_outside_core_pbr")
    try:
        if type(pose_alignment) is not bool:
            raise ValueError('Invalid pose-alignment option')
        if scope not in SCOPES or not levels or list(levels) != sorted(set(levels)) or any(type(n) is not int or n <= 0 for n in levels):
            raise ValueError("Invalid material scope or sampling configuration")
        if any(isinstance(value, bool) or not math.isfinite(value) or value < 0 for value in (parameter_tolerance, surface_tolerance_m)):
            raise ValueError("Invalid material tolerance")
        if not math.isfinite(convergence_m) or convergence_m <= 0:
            raise ValueError("Invalid material convergence tolerance")
        root = Path(trusted_root)
        a, ag = _load(left, root, scope, surface_only=surface_only)
        b, bg = _load(right, root, scope, surface_only=surface_only)
        report['surface_diagnostics'] = {'left': a.surface_diagnostics, 'right': b.surface_diagnostics}
        if pose_alignment:
            from .l1_material_registration import register_material_surface
            if scope != 'native_constant_principled':
                raise ValueError('Material motion requires native observations')
            b, report['registration'] = register_material_surface(
                left, right, a, b, tolerance_m=surface_tolerance_m, levels=levels,
                convergence_m=convergence_m, seed=seed)
            report.update(hard_gate=False, alignment='pose_anchored_rigid_attachment')
        report["used_parameter_groups"] = [len(ag), len(bg)]
        # No face boundary exists for a uniform equivalent material. Geometry
        # correctness remains a separate mandatory layer in compare_frame.
        if len(ag) == len(bg) == 1 and _equal(ag[0]["descriptor"], bg[0]["descriptor"], parameter_tolerance):
            report.update(status="ok", assignment_method="uniform_entire_surface", effective_parameters=ag[0]["descriptor"])
            return report
        for direction, source, groups, target, targets in (("left_to_right", a, ag, b, bg), ("right_to_left", b, bg, a, ag)):
            for group in groups:
                row = {"direction": direction, "source_slots": group["slots"], "status": "failed",
                       "source_shader": group["descriptor"]}
                report["regions"].append(row)
                compatible = [other for other in targets if _equal(group["descriptor"], other["descriptor"], parameter_tolerance)]
                row["target_slots"] = [index for other in compatible for index in other["slots"]]
                if not compatible:
                    if group["descriptor"]["kind"] == "unassigned" or any(other["descriptor"]["kind"] == "unassigned" for other in targets):
                        row.update(status="not_measurable", reason="Implicit versus explicit default shader equivalence not assessed")
                    else:
                        row["reason"] = "No equivalent effective shader parameters on the other surface"
                    continue
                source_region = _region(source, group["mask"])
                target_region = _region(target, np.logical_or.reduce([other["mask"] for other in compatible]))
                samples = surface_distances(sample_surface(source_region, levels[-1], seed), target_region)
                sentinels = surface_distances(np.concatenate((source_region.vertices, source_region.centers)), target_region)
                maximum = [max(float(samples[:level].max()), float(sentinels.max())) for level in levels]
                row.update(sampled_max_m=maximum[-1], levels=list(levels), maxima_m=maximum,
                           converged=len(maximum) > 1 and abs(maximum[-1] - maximum[-2]) <= convergence_m)
                row["status"] = "failed" if maximum[-1] > surface_tolerance_m else "ok" if row["converged"] else "not_measurable"
        statuses = [row["status"] for row in report["regions"]]
        report.update(status="failed" if "failed" in statuses else "not_measurable" if "not_measurable" in statuses else "ok",
                      assignment_method="bidirectional_compatible_material_region_surface_distance",
                      limitation="Finite samples and vertex/face-center sentinels, not a continuous surface bound")
    except (KeyError, TypeError, ValueError, OSError, IndexError) as error:
        report["reason"] = str(error)
    return report
