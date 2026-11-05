"""Fixed trusted operations for the killable L1 compute worker (no pickle)."""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from pathlib import Path


def dispatch(operation: str, payload: dict, entered=lambda: None) -> dict:
    if operation == 'edit_hole_profiles':
        from src.evaluator.l1_edit_probes import measure
        entered()
        return measure(payload)
    if operation == 'edit_surface':
        from src.evaluator.l1_edit_surface import measure
        entered()
        return measure(payload)
    if operation == 'slot_plate_edit':
        from src.evaluator.l1_slot_plate_edit import inspect_slot_plate_edit
        entered()
        return inspect_slot_plate_edit(payload['scene'], payload['baseline'], payload['design'],
            trusted_root=payload['trusted_root'], material_scope=payload['material_scope'],
            material_tolerance=payload['material_tolerance'], deadline=payload['measurement_deadline'],
            quality_mode=payload.get('quality_mode', False))
    if operation == 'slot_plate_structure':
        from src.evaluator.l1_slot_plate_structure import inspect_plate_structure
        entered()
        return inspect_plate_structure(payload['scene'], payload['baseline'], payload['design'],
            trusted_root=payload['trusted_root'], baseline_root=payload['baseline_root'],
            material_scope=payload['material_scope'], material_tolerance=payload['material_tolerance'],
            deadline=payload['measurement_deadline'])
    if operation == 'slot_plate_preservation':
        from src.evaluator.l1_slot_plate_preservation import inspect_plate_preservation
        entered()
        return inspect_plate_preservation(payload['scene'], payload['baseline'], payload['design'],
            trusted_root=payload['trusted_root'], baseline_root=payload['baseline_root'],
            deadline=payload['measurement_deadline'])
    if operation == 'slot_plate_surface':
        from src.evaluator.l1_slot_plate_surface import inspect_slot_plate_surface
        entered()
        return inspect_slot_plate_surface(payload['scene'], payload['design'], trusted_root=payload['trusted_root'],
                                          deadline=payload['measurement_deadline'])
    if operation == 'washer_changed_area':
        from src.evaluator.l1_area_diagnostics import measure
        entered()
        return measure(payload)
    if operation == 'swept_bar':
        from src.evaluator.l1_sweep_measurements import inspect_sweep
        entered()
        return inspect_sweep(payload['scene'], payload['design'], trusted_root=payload['trusted_root'],
                             assets_root=payload['assets_root'])
    if operation == 'washer_edit':
        from src.evaluator.l1_washer_edit import inspect_washer
        entered()
        return inspect_washer(payload['scene'], payload['baseline'], payload['design'],
                              trusted_root=payload['trusted_root'], material_scope=payload['material_scope'])
    if operation == 'machined_sleeve':
        from src.evaluator.l1_sleeve import inspect_sleeve
        entered()
        return inspect_sleeve(payload['scene'], payload['design'], trusted_root=payload['trusted_root'])
    if operation == 'file_io':
        from src.evaluator.l1_file_io import execute_file_io
        entered()
        return execute_file_io(payload['action'], payload['arguments'])
    if operation == 'solid_clearance':
        from src.evaluator.l1_separation import compare_solid_clearance
        arguments = dict(payload['arguments'])
        arguments['trusted_root'] = Path(arguments['trusted_root'])
        entered()
        return compare_solid_clearance(payload['left'], payload['right'], **arguments)
    if operation == "rigid_shape":
        from src.evaluator.l1_rigid_shape import compare_rigid_shape
        arguments = dict(payload['arguments'])
        arguments['trusted_root'] = Path(arguments['trusted_root'])
        entered()
        return compare_rigid_shape(payload['left'], payload['right'], **arguments)
    if operation == "compiled_material_fields":
        from src.evaluator.l1_field_comparison import compare_compiled_material_fields
        entered()
        return compare_compiled_material_fields(payload["left"], payload["right"], **payload["arguments"])
    if operation == "score":
        from src.evaluator.l1 import score_l1
        from src.evaluator.reporting import efficiency_metrics, human_score, vlm_score
        from src.evaluator.spec import EvalSpec
        spec = EvalSpec.from_dict(payload["spec"])
        entered()
        report = score_l1(spec, payload["evidence"])
        harness = payload["evidence"].get("harness", {})
        report["auxiliary_errors"] = []
        try:
            if "vlm_ratings" in harness:
                report["S_vlm"] = vlm_score(harness["vlm_ratings"], harness.get("vlm_importance"))
            if "human" in harness:
                report["S_human"] = human_score(**harness["human"])
            if "efficiency" in harness:
                report["efficiency"] = efficiency_metrics(final_score=report["S_core"], **harness["efficiency"])
        except (TypeError, ValueError) as error:
            report["auxiliary_errors"].append(f"Auxiliary evidence: {error}")
        return report
    if operation == "reproduction_sequence":
        from src.evaluator.l1_reproduction import compare_sequence
        entered()
        return compare_sequence(payload["frames"], expected_frames=tuple(payload["expected_frames"]), context=payload["context"])
    if operation not in {"geometry_scene", "reproduction_frame", "state_return", "bore_sections"}:
        raise ValueError("Unsupported compute operation")
    from src.evaluator.l1_geometry import GeometryConfig, L1GeometryEvaluator
    config = dict(payload["config"])
    # The outer watchdog must also terminate any nested volume worker.
    config["volume_new_session"] = False
    evaluator = L1GeometryEvaluator(GeometryConfig(**config))
    arguments = dict(payload["arguments"])
    if arguments.get("output") is not None:
        arguments["output"] = Path(arguments["output"])
    entered()
    if operation == "bore_sections":
        return evaluator.measure_bore_record(payload["record"], **arguments)
    if operation == "state_return":
        from src.evaluator.l1_state_return import compare_state_return
        return compare_state_return(payload["sequence"], evaluator, **arguments)
    geometry = evaluator.compare_scene_records(payload["left"], payload["right"], **arguments)
    if operation == "geometry_scene":
        return geometry
    from src.evaluator.l1_reproduction import compare_frame
    return compare_frame(
        payload["left"], payload["right"], geometry,
        frame=payload["frame"], material_tolerance=payload["material_tolerance"],
        geometry_config={**evaluator.worker_configuration(), "surface_tolerance_m": arguments.get("tolerance_m", evaluator.config.surface_tolerance_m)},
        material_scope=payload.get("material_scope", "native_constant_principled"),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    # Bootstrap only this checkout, never candidate-controlled PYTHONPATH/cwd.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    limit = 64 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
    if args.request.stat().st_size > limit:
        raise ValueError("Oversized compute request")
    request = json.loads(args.request.read_bytes())
    if set(request) != {"protocol", "operation", "payload", "deadline"} or request["protocol"] != "l1-compute-v1":
        raise ValueError("Invalid compute request")
    if time.monotonic() >= request["deadline"]:
        return 2
    def entered():
        # Written after numerical imports/configuration, immediately before
        # calling the actual operation. A startup timeout has no such marker.
        args.result.with_name("started.json").write_text(json.dumps({
            "pid": os.getpid(), "process_group": os.getpgrp(),
            "operation": request["operation"], "entered_monotonic": time.monotonic(),
        }))

    result = dispatch(request["operation"], request["payload"], entered)
    if time.monotonic() >= request["deadline"]:
        return 2
    content = json.dumps({
        "protocol": "l1-compute-v1", "operation": request["operation"], "result": result,
    }, ensure_ascii=False, allow_nan=False).encode()
    if len(content) > limit:
        raise ValueError("Oversized compute response")
    temporary = args.result.with_suffix(".tmp")
    temporary.write_bytes(content)
    temporary.replace(args.result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
