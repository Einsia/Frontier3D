"""Versioned L1 tolerance decisions and one-to-one dimension *proxy* matching."""

# Malformed external measurements use the evaluator's ValueError convention.
# ruff: noqa: TRY004

from __future__ import annotations

from typing import Any

import numpy as np


def _reject_booleans(value: Any) -> None:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("Boolean values are not numeric measurements")
    if isinstance(value, (list, tuple)):
        for item in value:
            _reject_booleans(item)


def tolerance_measurement(
    actual: Any, expected: Any, tolerance: float
) -> tuple[float, dict]:
    """A tolerance is an allowed interval, not the endpoint of a quality penalty.

    The slack is eight float64 arithmetic ULP-scale units, NOT a physical
    serialization allowance. Blender/mesh uncertainty needs separate calibration.
    Scores outside the interval decay using the worst axis, so an arbitrarily
    long vector cannot dilute an invalid component.
    """
    _reject_booleans(actual)
    _reject_booleans(expected)
    left, right = np.asarray(actual), np.asarray(expected)
    if left.dtype.kind not in "iuf" or right.dtype.kind not in "iuf":
        raise ValueError(
            "Measurement and target must contain numbers, not coerced strings or booleans"
        )
    left, right = left.astype(float), right.astype(float)
    if left.shape != right.shape or not left.size:
        raise ValueError("Measurement and target shapes differ or are empty")
    if not np.isfinite(left).all() or not np.isfinite(right).all():
        raise ValueError("Non-finite tolerance measurement")
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not np.isfinite(tolerance)
        or tolerance <= 0
    ):
        raise ValueError("Tolerance must be positive and finite")
    with np.errstate(over="ignore"):
        errors = np.abs(left - right)
    if not np.isfinite(errors).all():
        raise ValueError("Tolerance error calculation overflowed")
    slack = (
        8
        * np.finfo(float).eps
        * np.maximum(np.maximum(np.abs(left), np.abs(right)), tolerance)
    )
    outcomes = errors <= tolerance + slack
    passed = bool(outcomes.all())
    score = 1.0 if passed else max(0.0, min(1.0, 2.0 - float(errors.max()) / tolerance))
    return score, {
        "actual": left.tolist(),
        "expected": right.tolist(),
        "absolute_error": errors.tolist(),
        "max_absolute_error": float(errors.max()),
        "tolerance": tolerance,
        "numerical_slack": slack.tolist(),
        "per_component_passed": outcomes.tolist(),
        "within_tolerance": passed,
        "scoring": "tolerance_plateau_worst_error_v1",
    }


def match_dimension_proxies(
    objects: dict, parts: list[dict], tolerances: dict
) -> tuple[float, dict]:
    """Maximum bipartite matching of dimension-compatible roles, without names.

    These are AABB proxies, not semantic/feature proof. Returned evidence states
    that limitation; a separate required feature check must reject a solid fake
    bushing. Augmenting paths avoid greedy/order-dependent false missing parts.
    """
    candidates = []
    for name, item in objects.items():
        if item.get("type") != "MESH" or not item.get("visible_render", True):
            continue
        value = item.get("dimensions")
        if value is None:
            raise ValueError(f"Missing dimensions for delivery mesh {name}")
        dims = np.asarray(value)
        if (
            dims.shape != (3,)
            or dims.dtype.kind not in "iuf"
            or not np.isfinite(dims).all()
            or (dims < 0).any()
        ):
            raise ValueError("Invalid evaluated mesh dimension proxy")
        candidates.append((name, np.sort(dims.astype(float))))
    candidates.sort(key=lambda item: (tuple(item[1]), item[0]))
    slots: list[tuple[int, np.ndarray, float]] = []
    for index, part in enumerate(parts):
        target = np.sort(np.asarray(part["dimensions"], dtype=float))
        tolerance = part["tolerance"]
        if isinstance(tolerance, str):
            tolerance = tolerances[tolerance]
        slots.extend((index, target, tolerance) for _ in range(part["count"]))
    adjacency = []
    measures = {}
    for slot, (_, target, tolerance) in enumerate(slots):
        edges = []
        for candidate, (_, dims) in enumerate(candidates):
            _, measured = tolerance_measurement(dims, target, tolerance)
            measures[slot, candidate] = measured
            if measured["within_tolerance"]:
                edges.append(candidate)
        edges.sort(key=lambda index: measures[slot, index]["max_absolute_error"])
        adjacency.append(edges)
    owners: dict[int, int] = {}

    def augment(slot: int, visited: set[int]) -> bool:
        for candidate in adjacency[slot]:
            if candidate in visited:
                continue
            visited.add(candidate)
            if candidate not in owners or augment(owners[candidate], visited):
                owners[candidate] = slot
                return True
        return False

    for slot in sorted(range(len(slots)), key=lambda index: len(adjacency[index])):
        augment(slot, set())
    assigned = {slot: candidate for candidate, slot in owners.items()}
    roles = {}
    for index, part in enumerate(parts):
        matches = [
            {"object": candidates[assigned[slot]][0], **measures[slot, assigned[slot]]}
            for slot, (role, _, _) in enumerate(slots)
            if role == index and slot in assigned
        ]
        roles[part.get("id", str(index))] = {
            "expected_count": part["count"],
            "matched_count": len(matches),
            "matches": matches,
            "passed": len(matches) == part["count"],
        }
    extras = [name for index, (name, _) in enumerate(candidates) if index not in owners]
    return len(assigned) / len(slots), {
        "roles": roles,
        "matched_parts": len(assigned),
        "expected_parts": len(slots),
        "unmatched_meshes": extras,
        "unmatched_slots": len(slots) - len(assigned),
        "within_tolerance": len(assigned) == len(slots) and not extras,
        "method": "maximum_bipartite_dimension_proxy_v1",
        "limitations": [
            "Sorted world AABB dimensions do not prove hole features, orientation or semantic identity."
        ],
    }
