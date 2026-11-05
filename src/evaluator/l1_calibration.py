"""Evidence-only calibration helpers for L1 geometric measurements.

Calibration data must be reviewed before it can become a task threshold.  The
functions here deliberately report observed error, convergence and boundary
behaviour; they never infer a physical tolerance from a noisy measurement and
never alter an EvalSpec.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

import numpy as np

from .l1_numeric import match_dimension_proxies, tolerance_measurement

CALIBRATION_PROTOCOL = "l1-calibration-v1"


def _positive(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite positive number")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def diameter_to_radius_tolerance(diameter_tolerance_m: float) -> dict[str, Any]:
    """Record the explicit physical conversion used by bore measurements."""
    diameter = _positive(diameter_tolerance_m, "diameter_tolerance_m")
    return {
        "protocol": CALIBRATION_PROTOCOL,
        "diameter_tolerance_m": diameter,
        "radius_tolerance_m": diameter / 2,
        "conversion": "radius_tolerance = diameter_tolerance / 2",
        "physical_slack_added": 0.0,
    }


def tolerance_boundary_calibration(
    expected: Any, tolerance: float, deltas: Iterable[float]
) -> dict[str, Any]:
    """Measure numerical boundary behaviour without changing the tolerance.

    ``deltas`` are explicit signed test offsets supplied by the maintainer.
    Float64 arithmetic slack is reported by :func:`tolerance_measurement`; it
    is not relabelled as mesh serialization or Blender solver uncertainty.
    """
    tolerance = _positive(tolerance, "tolerance")
    values = list(deltas)
    if not values or any(
        isinstance(value, bool) or not np.isfinite(value) for value in values
    ):
        raise ValueError("deltas must be a nonempty finite sequence")
    rows = []
    for delta in values:
        actual = np.asarray(expected, dtype=float) + float(delta)
        _, decision = tolerance_measurement(actual, expected, tolerance)
        rows.append(
            {
                "delta": float(delta),
                "within_tolerance": decision["within_tolerance"],
                "max_absolute_error": decision["max_absolute_error"],
                "numerical_slack": decision["numerical_slack"],
            }
        )
    return {
        "protocol": CALIBRATION_PROTOCOL,
        "kind": "tolerance_boundary",
        "expected": np.asarray(expected, dtype=float).tolist(),
        "tolerance": tolerance,
        "physical_serialization_slack": 0.0,
        "cases": rows,
        "status": "ok"
        if any(row["within_tolerance"] for row in rows)
        and any(not row["within_tolerance"] for row in rows)
        else "failed",
    }


def surface_convergence_calibration(
    reports: Iterable[dict[str, Any]], *, declared_tolerance_m: float
) -> dict[str, Any]:
    """Summarize observed surface convergence from existing reports.

    A report is accepted only when it has the frozen surface-comparison shape;
    no percentile or observed maximum is silently promoted to a task threshold.
    """
    declared = _positive(declared_tolerance_m, "declared_tolerance_m")
    cases = []
    for report in reports:
        if not isinstance(report, dict) or not isinstance(report.get("levels"), list):
            raise TypeError("Surface calibration reports require levels")
        levels = report["levels"]
        if not levels or any(
            not isinstance(row, dict)
            or not isinstance(row.get("sampled_max_m"), (int, float))
            or not math.isfinite(row["sampled_max_m"])
            for row in levels
        ):
            raise ValueError("Surface levels contain invalid sampled maxima")
        final = float(levels[-1]["sampled_max_m"])
        deltas = report.get("last_level_deltas")
        cases.append(
            {
                "sample_levels": [row.get("samples_per_direction") for row in levels],
                "final_sampled_max_m": final,
                "last_level_deltas": deltas,
                "converged": report.get("converged") is True,
                "within_declared_tolerance": final <= declared,
            }
        )
    if not cases:
        raise ValueError("At least one surface calibration report is required")
    return {
        "protocol": CALIBRATION_PROTOCOL,
        "kind": "surface_convergence",
        "declared_tolerance_m": declared,
        "cases": cases,
        "threshold_source": "caller_declared_only",
        "limitations": [
            "Sampled maxima are not continuous Hausdorff bounds.",
            "Observed repeatability does not establish a physical task tolerance.",
        ],
    }


def volume_bounds_calibration(
    reports: Iterable[dict[str, Any]], *, expected_intersection_m3: float | None = None
) -> dict[str, Any]:
    """Record Boolean-vs-grid discrepancies and bound widths."""
    expected = None
    if expected_intersection_m3 is not None:
        if isinstance(expected_intersection_m3, bool) or not math.isfinite(
            expected_intersection_m3
        ):
            raise ValueError("expected_intersection_m3 must be finite")
        if expected_intersection_m3 < 0:
            raise ValueError("expected_intersection_m3 cannot be negative")
        expected = float(expected_intersection_m3)
    cases = []
    for report in reports:
        if not isinstance(report, dict) or not isinstance(
            report.get("grid_bounds"), list
        ):
            raise TypeError("Volume calibration reports require grid_bounds")
        rows = report["grid_bounds"]
        if not rows:
            raise ValueError("Volume calibration requires at least one grid level")
        widths = []
        for row in rows:
            lower = row.get("intersection_lower_m3")
            upper = row.get("intersection_upper_m3")
            if (
                not isinstance(lower, (int, float))
                or not isinstance(upper, (int, float))
                or not math.isfinite(lower)
                or not math.isfinite(upper)
                or lower < 0
                or upper < lower
            ):
                raise ValueError("Invalid volume bound")
            widths.append(float(upper - lower))
        boolean = report.get("intersection_volume_m3")
        case = {
            "resolutions": [row.get("resolution") for row in rows],
            "bound_widths_m3": widths,
            "bounds_narrowing": report.get("bounds_narrowing") is True,
            "boolean_intersection_m3": boolean,
            "grid_contains_boolean": all(
                row["intersection_lower_m3"] <= boolean <= row["intersection_upper_m3"]
                for row in rows
            )
            if isinstance(boolean, (int, float)) and math.isfinite(boolean)
            else None,
            "expected_intersection_m3": expected,
            "boolean_absolute_error_m3": abs(float(boolean) - expected)
            if expected is not None and isinstance(boolean, (int, float))
            else None,
        }
        cases.append(case)
    if not cases:
        raise ValueError("At least one volume calibration report is required")
    return {
        "protocol": CALIBRATION_PROTOCOL,
        "kind": "volume_bounds",
        "cases": cases,
        "threshold_source": "caller_declared_only",
        "limitations": [
            "Grid bounds are finite-resolution diagnostics.",
            "Boolean solver guards are not calibrated physical penetration allowances.",
        ],
    }


def nonfinite_input_calibration(
    expected: Any, tolerance: float, values: Iterable[Any]
) -> dict[str, Any]:
    """Verify that malformed numeric inputs are rejected, never scored as zero."""
    tolerance = _positive(tolerance, "tolerance")
    values = list(values)
    if not values:
        raise ValueError("values must contain at least one malformed input")
    cases = []
    for value in values:
        rejected = False
        reason = None
        try:
            tolerance_measurement(value, expected, tolerance)
        except (TypeError, ValueError, OverflowError) as error:
            rejected = True
            reason = str(error)
        cases.append({"value": repr(value), "rejected": rejected, "reason": reason})
    return {
        "protocol": CALIBRATION_PROTOCOL,
        "kind": "nonfinite_input",
        "cases": cases,
        "status": "ok" if all(case["rejected"] for case in cases) else "failed",
        "threshold_source": "caller_declared_only",
    }


def matching_order_calibration(
    objects: dict[str, dict[str, Any]],
    parts: list[dict[str, Any]],
    tolerances: dict[str, float],
    orders: Iterable[Iterable[str]],
) -> dict[str, Any]:
    """Check that global dimension matching is stable under object iteration order."""
    if not isinstance(objects, dict) or not objects:
        raise ValueError("objects must be a nonempty object map")
    if not isinstance(parts, list) or not parts:
        raise ValueError("parts must be a nonempty list")
    names = set(objects)
    orders = [list(order) for order in orders]
    if not orders:
        raise ValueError("orders must contain at least one permutation")
    baseline = None
    rows = []
    for order in orders:
        if set(order) != names or len(order) != len(names):
            raise ValueError("Each order must be a permutation of object names")
        ordered = {name: objects[name] for name in order}
        _, details = match_dimension_proxies(ordered, parts, tolerances)
        signature = {
            role: {
                "matched_count": value["matched_count"],
                "passed": value["passed"],
                "max_errors": sorted(
                    match.get("max_absolute_error", float("inf"))
                    for match in value["matches"]
                ),
            }
            for role, value in sorted(details["roles"].items())
        }
        if baseline is None:
            baseline = signature
        rows.append(
            {
                "order": order,
                "within_tolerance": details["within_tolerance"],
                "signature": signature,
                "stable_with_baseline": signature == baseline,
            }
        )
    return {
        "protocol": CALIBRATION_PROTOCOL,
        "kind": "matching_order",
        "method": details["method"],
        "cases": rows,
        "status": "ok"
        if all(row["within_tolerance"] and row["stable_with_baseline"] for row in rows)
        else "failed",
        "threshold_source": "caller_declared_only",
    }


def edit_gate_calibration(
    cases: Iterable[dict[str, Any]], *, threshold: float = 0.8
) -> dict[str, Any]:
    """Record strict target/preserve gate behaviour without averaging away a failure."""
    threshold = _positive(threshold, "threshold")
    if threshold > 1:
        raise ValueError("threshold must be at most one")
    cases = list(cases)
    if not cases:
        raise ValueError("cases must contain at least one edit gate case")
    rows = []
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"target", "preserve"}:
            raise ValueError("Edit gate cases require target and preserve")
        target, preserve = case["target"], case["preserve"]
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for value in (target, preserve)
        ):
            raise ValueError("Edit gate scores must be finite values in [0, 1]")
        rows.append(
            {
                "target": float(target),
                "preserve": float(preserve),
                "target_passed": target >= threshold,
                "preserve_passed": preserve >= threshold,
                "within_gate": target >= threshold and preserve >= threshold,
            }
        )
    return {
        "protocol": CALIBRATION_PROTOCOL,
        "kind": "edit_dual_gate",
        "threshold": threshold,
        "cases": rows,
        "status": "ok",
        "threshold_source": "caller_declared_only",
        "scoring": "all_target_and_preserve_constraints_v1",
    }


def score_protocol_separation(
    legacy_report: dict[str, Any], current_report: dict[str, Any]
) -> dict[str, Any]:
    """Prove that legacy and current reports are labelled separately."""
    if not isinstance(legacy_report, dict) or not isinstance(current_report, dict):
        raise TypeError("legacy_report and current_report must be objects")
    legacy = legacy_report.get("score_policy")
    current = current_report.get("score_policy")
    if not isinstance(legacy, str) or not legacy or not isinstance(current, str) or not current:
        raise ValueError("Both reports need a nonempty score_policy")
    return {
        "protocol": CALIBRATION_PROTOCOL,
        "kind": "score_protocol_separation",
        "legacy_score_policy": legacy,
        "current_score_policy": current,
        "status": "ok" if legacy != current else "failed",
        "mixed": legacy == current,
    }


def numeric_policy_calibration(
    *,
    expected: Any,
    tolerance: float,
    deltas: Iterable[float],
    malformed_values: Iterable[Any],
    objects: dict[str, dict[str, Any]],
    parts: list[dict[str, Any]],
    tolerances: dict[str, float],
    orders: Iterable[Iterable[str]],
    edit_cases: Iterable[dict[str, Any]],
    legacy_report: dict[str, Any],
    current_report: dict[str, Any],
) -> dict[str, Any]:
    """Build a complete G04-A numeric calibration matrix.

    This is an evidence gate for the maintainer, not a threshold/weight
    inference mechanism.  ``freeze_eligible`` is intentionally false until a
    task-specific review supplies physical geometry calibration separately.
    """
    categories = {
        "tolerance_boundary": tolerance_boundary_calibration(
            expected, tolerance, deltas
        ),
        "nonfinite_input": nonfinite_input_calibration(
            expected, tolerance, malformed_values
        ),
        "matching_order": matching_order_calibration(
            objects, parts, tolerances, orders
        ),
        "edit_dual_gate": edit_gate_calibration(edit_cases),
        "score_protocol_separation": score_protocol_separation(
            legacy_report, current_report
        ),
    }
    statuses = [category.get("status") for category in categories.values()]
    return {
        "protocol": CALIBRATION_PROTOCOL,
        "kind": "numeric_policy_matrix",
        "status": "ok" if all(status == "ok" for status in statuses) else "failed",
        "categories": categories,
        "freeze_eligible": False,
        "threshold_source": "caller_declared_only",
        "weight_source": "maintainer_review_required",
        "limitations": [
            "Numeric policy acceptance does not calibrate mesh, Boolean, hole or interference uncertainty.",
            "No task score or EvalSpec is modified by this report.",
        ],
    }


__all__ = [
    "CALIBRATION_PROTOCOL",
    "diameter_to_radius_tolerance",
    "edit_gate_calibration",
    "matching_order_calibration",
    "nonfinite_input_calibration",
    "numeric_policy_calibration",
    "score_protocol_separation",
    "surface_convergence_calibration",
    "tolerance_boundary_calibration",
    "volume_bounds_calibration",
]
