"""Native frame return with fixed within-session identity and world geometry.

This checks return of declared entities and separately reports bounded rigid-shape
witnesses for the middle state. Separation, full materials and task roles are
separate obligations; shape registration never changes the return verdict.
"""

from __future__ import annotations

from pathlib import Path

from .l1_cycle_materials import compare_middle_materials, material_cycle_summary
from .l1_geometry import L1GeometryEvaluator
from .l1_reproduction import compare_materials
from .l1_rigid_shape import compare_rigid_shape
from .l1_separation import compare_state_separation

STATE_RETURN_PROTOCOL = "l1-state-return-v1"


def _identity_map(scene: dict) -> dict:
    objects = scene["objects"]
    if not isinstance(objects, dict) or not scene.get("geometry_policy") or scene.get("has_instances") or scene.get("unsupported_geometry"):
        raise ValueError("Complete supported native geometry evidence is required")
    result = {}
    for name, item in objects.items():
        if item.get("entity_scope") != "delivery_geometry":
            continue
        identity = item["session_identity"]
        if type(identity) is not int or identity <= 0 or identity in result:
            raise ValueError("Missing or duplicate within-session object identity")
        result[identity] = (name, item)
    return result


def compare_state_return(
    sequence: dict, geometry: L1GeometryEvaluator, *, output: Path,
    tolerance_m: float, material_tolerance: float,
) -> dict:
    """Compare first/last real surfaces of each fixed entity, never free rematching."""
    report = {
        "protocol": STATE_RETURN_PROTOCOL, "status": "not_measurable",
        "scope": "first_to_last_world_geometry_by_session_identity",
        "identity_preserved": None, "parts": [], "session": {},
        "tolerance_m": tolerance_m, "material_tolerance": material_tolerance,
        "not_assessed": ["global_rigid_registration_completeness", "task_shape_threshold_calibration", "actual_separation", "complete_node_materials",
                         "textures_and_face_assignment", "task_roles"],
    }
    try:
        if (sequence["protocol"] != "l1-state-sequence-v1" or sequence["status"] != "completed"
                or type(sequence["file_loads"]) is not int or sequence["file_loads"] != 1
                or sequence["autoexec_enabled"] is not False or sequence["identity_kind"] != "blender_id_session_uid"
                or sequence["frames"] != [1, 61, 1] or any(type(frame) is not int for frame in sequence["frames"])):
            raise ValueError("A completed, single-load native 1/61/1 sequence is required")
        report["session"] = {key: sequence[key] for key in (
            "session_id", "process_id", "scene_path", "scene_sha256", "spec_sha256", "file_loads",
        )}
        if not report["session"]["session_id"] or type(sequence["process_id"]) is not int or sequence["process_id"] <= 0:
            raise ValueError("Native session binding is missing")
        snapshots = sequence["snapshots"]
        if not isinstance(snapshots, list) or len(snapshots) != 3:
            raise ValueError("Incomplete native state snapshots")
        for index, (snapshot, frame) in enumerate(zip(snapshots, (1, 61, 1))):
            if (type(snapshot["index"]) is not int or snapshot["index"] != index
                    or type(snapshot["frame"]) is not int or snapshot["frame"] != frame
                    or type(snapshot["observed_frame"]) is not int or snapshot["observed_frame"] != frame):
                raise ValueError("Reordered or mislabelled native snapshot")
        scenes = [snapshot["scene"] for snapshot in snapshots]
        identities = [_identity_map(scene) for scene in scenes]
        sets = [set(value) for value in identities]
        report["identity_preserved"] = bool(sets[0]) and all(value == sets[0] for value in sets)
        report["identity_sets"] = [sorted(value) for value in sets]
        for identity in sorted(set.union(*sets)):
            present = [identity in value for value in sets]
            part = {"session_identity": identity, "present_at_states": present}
            report["parts"].append(part)
            if not all(present):
                part.update(status="failed", reason="Delivery entity appeared, disappeared or was replaced during the sequence")
                continue
            left_name, left = identities[0][identity]
            right_name, right = identities[-1][identity]
            part.update(first_name=left_name, last_name=right_name)
            middle_name, middle = identities[1][identity]
            if geometry.config.reproduction_diagnostics:
                part['exploded_shape'] = compare_rigid_shape(
                    left, middle, trusted_root=geometry.config.trusted_root, tolerance_m=tolerance_m,
                    levels=geometry.config.surface_levels, convergence_m=geometry.config.surface_convergence_m,
                    seed=geometry.config.seed,
                )
                part['exploded_shape']['middle_name'] = middle_name
                part['middle_materials'] = compare_middle_materials(
                    left, middle, geometry.config, tolerance_m=tolerance_m, material_tolerance=material_tolerance)
            else:
                omitted={'status':'not_in_scope','hard_gate':False,
                    'reason':'Image quality does not score exploded rigid-shape or intermediate material diagnostics'}
                part.update(exploded_shape=dict(omitted),middle_materials=dict(omitted))
            # One entity per side constrains matching to the observed identity;
            # identical bolts may not trade places to manufacture restoration.
            first = {**scenes[0], "objects": {left_name: left}}
            last = {**scenes[-1], "objects": {right_name: right}}
            measured = geometry.compare_scene_records(first, last, output=output / f"entity-{identity}", tolerance_m=tolerance_m)
            if any("material_colors" not in item and "material_surface" not in item for item in (left, right)):
                materials = {"status": "not_measurable", "reason": "Material color evidence is absent"}
            else:
                materials = compare_materials(first, last, [{"left": left_name, "right": right_name}], tolerance=material_tolerance,
                                              geometry_config={**geometry.worker_configuration(), "surface_tolerance_m": tolerance_m})
            part.update(geometry=measured, materials=materials)
            if measured["status"] != "ok" or materials["status"] == "not_measurable":
                part["status"] = "not_measurable"
            else:
                part["status"] = "ok" if measured["evidence"]["geometry_match"] and materials["status"] == "ok" else "failed"
        statuses = [part["status"] for part in report["parts"]]
        report["status"] = "not_measurable" if "not_measurable" in statuses else (
            "ok" if report["identity_preserved"] and statuses and all(status == "ok" for status in statuses) else "failed"
        )
        shapes = [part.get('exploded_shape', {}).get('status', 'not_measurable') for part in report['parts']]
        report['exploded_shape_diagnostic'] = {
            'protocol': 'l1-exploded-shape-v1', 'hard_gate': False,
            'status': 'failed' if not report['identity_preserved'] else (
                'ok' if shapes and all(status == 'ok' for status in shapes) else 'not_measurable'),
            'scope': 'first_to_middle_fixed_identity_proper_rigid_shape_only',
            'fixed_part_count': len(sets[0]), 'witnessed_count': shapes.count('ok'),
            'not_assessed': ['actual_separation', 'full_cycle_materials', 'task_roles', 'task_threshold_calibration'],
        }
        if geometry.config.reproduction_diagnostics:
            report['separation_diagnostic'] = compare_state_separation(
                identities[0], identities[1], trusted_root=geometry.config.trusted_root)
            report['material_cycle_diagnostic'] = material_cycle_summary(report['parts'])
        else:
            omitted={'status':'not_in_scope','hard_gate':False,'reason':'Outside image scoring policy'}
            report.update(exploded_shape_diagnostic=dict(omitted),separation_diagnostic=dict(omitted),
                material_cycle_diagnostic=dict(omitted))
    except (KeyError, TypeError, ValueError, OSError) as error:
        report.update(status="not_measurable", reason=str(error))
    return report
