"""L2 closed-boundary intersection and winding predicates.

Adapted from the repository's validated L1 predicates and copied under the L2
runtime hash boundary. No import of changing L1 implementation modules.
"""
import numpy as np


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


def winding_classification(
    vertices, triangles, points, *, tolerance=1e-5, epsilon_m=1e-9
) -> np.ndarray:
    vertices, points = (
        np.asarray(vertices, dtype=float),
        np.asarray(points, dtype=float),
    )
    triangles = np.asarray(triangles)
    if (
        vertices.ndim != 2
        or vertices.shape[1:] != (3,)
        or not np.isfinite(vertices).all()
        or points.ndim != 2
        or points.shape[1:] != (3,)
        or not np.isfinite(points).all()
        or triangles.ndim != 2
        or triangles.shape[1:] != (3,)
        or triangles.dtype.kind not in "iu"
        or not len(triangles)
        or not len(vertices)
        or (triangles < 0).any()
        or (triangles >= len(vertices)).any()
        or not np.isfinite(tolerance)
        or not 0 < tolerance < 0.5
        or not np.isfinite(epsilon_m)
        or epsilon_m <= 0
    ):
        raise ValueError(
            "Winding requires finite vertices, triangle indices and points"
        )
    xyz = vertices[triangles]
    normals = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
    normal_lengths = np.linalg.norm(normals, axis=1)
    if np.any(normal_lengths <= 1e-18):
        raise ValueError("Degenerate triangles cannot classify solid occupancy")
    result = np.full(len(points), -1, dtype=np.int8)
    outside = np.any(
        (points < vertices.min(axis=0) - epsilon_m)
        | (points > vertices.max(axis=0) + epsilon_m),
        axis=1,
    )
    result[outside] = 0
    indices = np.flatnonzero(~outside)
    batch = max(1, min(64, 200000 // len(triangles)))
    for start in range(0, len(indices), batch):
        subset = indices[start : start + batch]
        delta = xyz[None, :, :, :] - points[subset, None, None, :]
        a, b, c = delta[:, :, 0], delta[:, :, 1], delta[:, :, 2]
        la, lb, lc = (
            np.linalg.norm(a, axis=2),
            np.linalg.norm(b, axis=2),
            np.linalg.norm(c, axis=2),
        )
        numerator = np.einsum("ijk,ijk->ij", a, np.cross(b, c))
        denominator = (
            la * lb * lc
            + np.einsum("ijk,ijk->ij", a, b) * lc
            + np.einsum("ijk,ijk->ij", b, c) * la
            + np.einsum("ijk,ijk->ij", c, a) * lb
        )
        winding = np.abs(np.arctan2(numerator, denominator).sum(axis=1) / (2 * np.pi))
        result[subset[winding <= tolerance]] = 0
        result[subset[np.abs(winding - 1) <= tolerance]] = 1
        near_plane = np.abs(numerator) <= epsilon_m * normal_lengths[None, :]
        if near_plane.any():
            inside_triangle = near_plane.copy()
            for p, q in ((a, b), (b, c), (c, a)):
                side = np.einsum("ijk,jk->ij", np.cross(q - p, -p), normals)
                slack = (
                    epsilon_m * normal_lengths[None, :] * np.linalg.norm(q - p, axis=2)
                )
                inside_triangle &= side >= -slack
            result[subset[inside_triangle.any(axis=1)]] = -1
    return result
