"""Triangle-level L1 solid validation, independent of Blender and object names.

Broad-phase pairs are supplied by the worker's BVH; this module performs the
double-precision narrow phase. Topological shared points/edges are allowed,
but an overlap extending beyond that shared simplex is a self-intersection.
"""

from __future__ import annotations

from typing import Any

import numpy as np

GEOMETRY_POLICY = {
    "version": "l1-mesh-v1",
    "weld_m": 1e-9,
    "intersection_epsilon_m": 1e-9,
    "degenerate_area_m2": 1e-18,
    "max_triangles": 200000,
    "max_intersection_pairs": 2000000,
}


def validate_geometry_policy(value: Any) -> None:
    # Freeze precision and resource limits with the protocol, not per candidate.
    if value != GEOMETRY_POLICY or any(
        type(value[k]) is not type(v) for k, v in GEOMETRY_POLICY.items()
    ):
        raise ValueError("L1 geometry policy must exactly match l1-mesh-v1")


def _section(
    triangle: np.ndarray, distances: np.ndarray, epsilon: float
) -> list[np.ndarray]:
    points = [p for p, d in zip(triangle, distances, strict=True) if abs(d) <= epsilon]
    for index in range(3):
        other = (index + 1) % 3
        a, b = distances[index], distances[other]
        if (a < -epsilon and b > epsilon) or (a > epsilon and b < -epsilon):
            points.append(
                triangle[index] + a / (a - b) * (triangle[other] - triangle[index])
            )
    return points


def _cross2(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def _coplanar_overlap(
    a: np.ndarray, b: np.ndarray, normal: np.ndarray, epsilon: float
) -> list[np.ndarray]:
    axes = [i for i in range(3) if i != int(np.argmax(np.abs(normal)))]
    orientation = _cross2(b[1, axes] - b[0, axes], b[2, axes] - b[0, axes])
    sign = 1 if orientation >= 0 else -1
    polygon = list(a)
    for i in range(3):
        start, end = b[i, axes], b[(i + 1) % 3, axes]
        edge = end - start
        length = float(np.linalg.norm(edge))
        if not length:
            return []

        def distance(point, edge=edge, start=start, length=length):
            return sign * _cross2(edge, point[axes] - start) / length

        clipped = []
        for j, p in enumerate(polygon):
            q = polygon[(j + 1) % len(polygon)]
            dp, dq = distance(p), distance(q)
            pin, qin = dp >= -epsilon, dq >= -epsilon
            if pin:
                clipped.append(p)
            if pin != qin and abs(dp - dq) > np.finfo(float).tiny:
                # Clip at the mathematical edge, not a displaced epsilon edge.
                t = min(1.0, max(0.0, dp / (dp - dq)))
                clipped.append(p + t * (q - p))
        polygon = clipped
        if not polygon:
            break
    return polygon


def triangle_intersection(
    a: np.ndarray, b: np.ndarray, epsilon: float
) -> list[np.ndarray]:
    """Intersection endpoints/polygon; coplanar contact is handled explicitly."""
    na, nb = np.cross(a[1] - a[0], a[2] - a[0]), np.cross(b[1] - b[0], b[2] - b[0])
    la, lb = float(np.linalg.norm(na)), float(np.linalg.norm(nb))
    if not la or not lb:
        return []  # Degenerate triangles are independently invalid, not solids.
    na, nb = na / la, nb / lb
    da, db = (a - b[0]) @ nb, (b - a[0]) @ na
    if any(np.all(d > epsilon) or np.all(d < -epsilon) for d in (da, db)):
        return []
    direction = np.cross(na, nb)
    norm = float(np.linalg.norm(direction))
    if norm <= 64 * np.finfo(float).eps:
        return (
            _coplanar_overlap(a, b, na, epsilon)
            if np.max(np.abs(da)) <= epsilon
            else []
        )
    pa, pb = _section(a, da, epsilon), _section(b, db, epsilon)
    if not pa or not pb:
        return []
    direction /= norm
    # Use a local origin to avoid cancellation for globally translated scenes.
    origin = pa[0]
    ta = [float((p - origin) @ direction) for p in pa]
    tb = [float((p - origin) @ direction) for p in pb]
    low, high = max(min(ta), min(tb)), min(max(ta), max(tb))
    if low > high + epsilon:
        return []
    return [origin + low * direction, origin + high * direction]


def improper_intersection(
    vertices: np.ndarray, left: np.ndarray, right: np.ndarray, epsilon: float
) -> bool:
    shared = sorted(set(left) & set(right))
    if len(shared) == 3:
        return True  # Duplicate geometric faces, including reversed duplicates.
    a, b = vertices[left], vertices[right]
    if len(shared) == 2:
        # Non-coplanar neighboring triangles can meet only on their common edge.
        normal = np.cross(a[1] - a[0], a[2] - a[0])
        norm = float(np.linalg.norm(normal))
        remaining = next(i for i in right if i not in shared)
        if norm and abs(float((vertices[remaining] - a[0]) @ normal)) > epsilon * norm:
            return False
    points = triangle_intersection(a, b, epsilon)
    if not points:
        return False
    if not shared:
        return True
    start = vertices[shared[0]]
    for point in points:
        if len(shared) == 1:
            distance = float(np.linalg.norm(point - start))
        else:
            edge = vertices[shared[1]] - start
            length2 = float(edge @ edge)
            t = (
                min(1.0, max(0.0, float((point - start) @ edge) / length2))
                if length2
                else 0
            )
            distance = float(np.linalg.norm(point - start - t * edge))
        if distance > 4 * epsilon:
            return True
    return False


def intersection_audit(
    vertices, triangles, pairs, epsilon: float, max_pairs: int
) -> dict:
    vertices = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int64)
    candidates = sorted({(min(i, j), max(i, j)) for i, j in pairs if i != j})
    if len(candidates) > max_pairs:
        return {
            "status": "not_measurable",
            "reason": "self-intersection pair budget exceeded",
            "candidate_pairs": len(candidates),
            "intersecting_pairs": None,
            "examples": [],
        }
    hits = []
    count = 0
    for i, j in candidates:
        if improper_intersection(vertices, triangles[i], triangles[j], epsilon):
            count += 1
            if len(hits) < 32:
                hits.append([i, j])
    return {
        "status": "ok",
        "candidate_pairs": len(candidates),
        "intersecting_pairs": count,
        "examples": hits,
        "epsilon_m": epsilon,
        "allowed_shared_boundary_slack_m": 4 * epsilon,
        "method": "triangle_plane_clip_shared_simplex_v1",
    }


def triangulated_volume(vertices, triangles) -> float:
    vertices = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int64)
    if not len(triangles):
        return 0.0
    origin = vertices.mean(axis=0)
    points = vertices[triangles] - origin
    return float(
        np.einsum("ij,ij->i", points[:, 0], np.cross(points[:, 1], points[:, 2])).sum()
        / 6
    )


def solid_validity(facts: dict, intersections: dict) -> dict:
    reasons = []
    for field, expected, reason in (
        ("closed", True, "open_or_nonmanifold"),
        ("components", 1, "disconnected"),
        ("inconsistent_edges", 0, "inconsistent_winding"),
        ("nonmanifold_vertices", 0, "nonmanifold_vertices"),
        ("degenerate_faces", 0, "degenerate_faces"),
        ("loose_vertices", 0, "loose_vertices"),
        ("loose_edges", 0, "loose_edges"),
    ):
        if facts.get(field) != expected:
            reasons.append(reason)
    signed = facts["signed_volume_integral_m3"]
    if not np.isfinite(signed):
        reasons.append("nonfinite_volume_integral")
    elif signed <= 0:
        reasons.append("nonpositive_outward_volume")
    if intersections["status"] != "ok":
        reasons.append("self_intersection_unmeasured")
    elif intersections["intersecting_pairs"]:
        reasons.append("self_intersection")
    valid = not reasons
    return {
        "valid_solid": valid,
        "volume_reliable": valid,
        "solid_volume_m3": signed if valid else None,
        "invalid_reasons": reasons,
    }
