"""L1 mechanical sections and bore corridors in original metre coordinates.

Section loops come from actual triangle/plane intersections. Full axial
corridor clearance examines every triangle; it is not inferred from the
presence of radii at a few sampled heights.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from .l1_surface import SurfaceMesh
from .l1_volume_math import winding_classification


def axis_frame(axis) -> np.ndarray:
    axis = np.asarray(axis, dtype=float)
    if axis.shape != (3,) or not np.isfinite(axis).all() or not np.any(axis):
        raise ValueError("A finite nonzero axis is required")
    scaled = axis / np.max(np.abs(axis))
    w = scaled / np.linalg.norm(scaled)
    seed = np.eye(3)[int(np.argmin(np.abs(w)))]
    u = np.cross(seed, w)
    u /= np.linalg.norm(u)
    return np.column_stack((u, np.cross(w, u), w))


def _center(value) -> np.ndarray:
    point = np.asarray(value, dtype=float)
    if point.shape != (3,) or not np.isfinite(point).all():
        raise ValueError("Center must contain three finite metre coordinates")
    return point


def _area(points: np.ndarray) -> float:
    other = np.roll(points, -1, axis=0)
    return float(np.sum(points[:, 0] * other[:, 1] - points[:, 1] * other[:, 0]) / 2)


def _contains_origin(points: np.ndarray) -> bool:
    ends = np.roll(points, -1, axis=0)
    crosses = (points[:, 1] > 0) != (ends[:, 1] > 0)
    p, q = points[crosses], ends[crosses]
    intersections = p[:, 0] - p[:, 1] * (q[:, 0] - p[:, 0]) / (q[:, 1] - p[:, 1])
    return bool(np.count_nonzero(intersections > 0) % 2)


def section_loops(
    mesh: SurfaceMesh, center, axis, offset: float, *, epsilon_m=1e-9
) -> dict:
    frame, center = axis_frame(axis), _center(center)
    if not np.isfinite(offset) or not np.isfinite(epsilon_m) or epsilon_m <= 0:
        raise ValueError("Invalid section precision or offset")
    coordinates = (mesh.vertices - center) @ frame
    requested = float(offset)
    # Avoid ambiguous coplanar faces/vertex stars. Record the perturbation;
    # never silently normalize geometry or move an individual part.
    for _ in range(8):
        if np.min(np.abs(coordinates[:, 2] - offset)) > 2 * epsilon_m:
            break
        offset += 4 * epsilon_m
    else:
        return {
            "status": "not_measurable",
            "reason": "No nondegenerate nearby section plane",
        }
    xyz = coordinates[mesh.triangles]
    distances = xyz[:, :, 2] - offset
    crosses = (distances.min(axis=1) < 0) & (distances.max(axis=1) > 0)
    segments = []
    for triangle, d in zip(xyz[crosses], distances[crosses], strict=True):
        points = []
        for i in range(3):
            j = (i + 1) % 3
            if (d[i] < 0) != (d[j] < 0):
                points.append(
                    (triangle[i] + d[i] / (d[i] - d[j]) * (triangle[j] - triangle[i]))[
                        :2
                    ]
                )
        if len(points) != 2:
            return {
                "status": "not_measurable",
                "reason": "Ambiguous triangle-plane intersection",
            }
        normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
        tangent = np.array([-normal[1], normal[0]])
        if np.dot(points[1] - points[0], tangent) < 0:
            points.reverse()
        segments.append(points)
    if not segments:
        return {
            "status": "ok",
            "requested_offset_m": requested,
            "offset_m": float(offset),
            "loops": [],
        }
    endpoints = np.asarray(segments).reshape(-1, 2)
    parent = np.arange(len(endpoints))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return int(i)

    for i, j in sorted(cKDTree(endpoints).query_pairs(epsilon_m)):
        a, b = find(i), find(j)
        parent[max(a, b)] = min(a, b)
    edges, incoming = {}, {}
    for i in range(0, len(endpoints), 2):
        a, b = find(i), find(i + 1)
        if a == b:
            continue
        if a in edges or b in incoming:
            return {
                "status": "not_measurable",
                "reason": "Branched or duplicate section boundary",
            }
        edges[a], incoming[b] = b, a
    if set(edges) != set(incoming):
        return {"status": "not_measurable", "reason": "Open section boundary"}
    remaining = set(edges)
    loops = []
    while remaining:
        start = min(remaining)
        current, path = start, []
        while current in remaining:
            remaining.remove(current)
            path.append(endpoints[current])
            current = edges[current]
        if current != start or len(path) < 3:
            return {"status": "not_measurable", "reason": "Invalid section cycle"}
        polygon = np.asarray(path)
        signed_area = _area(polygon)
        loops.append(
            {
                "points_m": polygon.tolist(),
                "signed_area_m2": signed_area,
                "kind": "cavity" if signed_area < 0 else "outer",
            }
        )
    return {
        "status": "ok",
        "requested_offset_m": requested,
        "offset_m": float(offset),
        "loops": loops,
        "basis_world": frame.tolist(),
        "center_world_m": center.tolist(),
        "epsilon_m": epsilon_m,
    }


def circle_boundary(points) -> dict:
    points = np.asarray(points, dtype=float)
    if (
        points.ndim != 2
        or points.shape[1:] != (2,)
        or len(points) < 3
        or not np.isfinite(points).all()
    ):
        raise ValueError("Circle fit requires a finite closed polygon")
    origin = points.mean(axis=0)
    local = points - origin
    matrix = np.column_stack((2 * local, np.ones(len(local))))
    fitted, _, rank, _ = np.linalg.lstsq(
        matrix, np.square(local).sum(axis=1), rcond=None
    )
    if rank != 3:
        raise ValueError("Collinear circle fit")
    center = origin + fitted[:2]
    radius2 = float(fitted[2] + fitted[:2] @ fitted[:2])
    if radius2 <= 0:
        raise ValueError("Nonpositive fitted radius")
    radii = np.linalg.norm(points - center, axis=1)
    ends = np.roll(points, -1, axis=0)
    edges = ends - points
    length2 = np.einsum("ij,ij->i", edges, edges)
    if np.any(length2 == 0):
        raise ValueError("Duplicate consecutive section points")
    t = np.clip(np.einsum("ij,ij->i", center - points, edges) / length2, 0, 1)
    min_radius = float(
        np.linalg.norm(points + t[:, None] * edges - center, axis=1).min()
    )
    max_radius = float(radii.max())
    radius = float(np.sqrt(radius2))
    return {
        "center_plane_m": center.tolist(),
        "radius_m": radius,
        "min_boundary_radius_m": min_radius,
        "max_boundary_radius_m": max_radius,
        "max_circular_deviation_m": max(radius - min_radius, max_radius - radius),
        "boundary_vertices": len(points),
    }


def _clip_height(
    polygon: list[np.ndarray], height: float, above: bool
) -> list[np.ndarray]:
    result = []
    for i, p in enumerate(polygon):
        q = polygon[(i + 1) % len(polygon)]
        dp, dq = p[2] - height, q[2] - height
        pin, qin = (dp >= 0, dq >= 0) if above else (dp <= 0, dq <= 0)
        if pin:
            result.append(p)
        if pin != qin:
            result.append(p + dp / (dp - dq) * (q - p))
    return result


def _projected_radial_min(polygon: list[np.ndarray]) -> float:
    points = np.asarray(polygon)[:, :2]
    if len(points) == 1:
        return float(np.linalg.norm(points[0]))
    ends = np.roll(points, -1, axis=0)
    edges = ends - points
    crosses = edges[:, 0] * (-points[:, 1]) - edges[:, 1] * (-points[:, 0])
    # The clipped triangle is convex. A nondegenerate projected polygon
    # containing the axis has zero radial distance, regardless of its height.
    if abs(_area(points)) > 1e-24 and (np.all(crosses >= 0) or np.all(crosses <= 0)):
        return 0.0
    lengths = np.einsum("ij,ij->i", edges, edges)
    t = np.divide(
        -np.einsum("ij,ij->i", points, edges),
        lengths,
        out=np.zeros(len(points)),
        where=lengths > 0,
    )
    closest = points + np.clip(t, 0, 1)[:, None] * edges
    return float(np.linalg.norm(closest, axis=1).min())


def axial_corridor(
    mesh: SurfaceMesh, center, axis, span_m, radius_m: float, *, epsilon_m=1e-9
) -> dict:
    """Test the entire open cylinder, catching caps between any section layers.

    This is only a boundary-intrusion test, even with cavity sections. An
    enclosing cavity loop may contain a solid island. Solid occupancy must be
    checked separately on a validated solid before declaring an empty bore.
    """
    center, frame = _center(center), axis_frame(axis)
    span = np.asarray(span_m, dtype=float)
    if (
        span.shape != (2,)
        or not np.isfinite(span).all()
        or span[0] >= span[1]
        or not np.isfinite(radius_m)
        or not np.isfinite(epsilon_m)
        or radius_m <= epsilon_m
        or epsilon_m <= 0
    ):
        raise ValueError("Invalid axial corridor dimensions")
    guard = max(float(epsilon_m), 128 * np.finfo(float).eps * max(
        1., float(np.abs(mesh.vertices).max()), float(np.abs(center).max())))
    if radius_m <= 2 * guard or span[1] - span[0] <= 2 * guard:
        raise ValueError("Axial corridor is smaller than its numerical guard")
    xyz = (mesh.xyz - center) @ frame
    candidates = np.flatnonzero(
        (xyz[:, :, 2].max(axis=1) >= span[0] - guard)
        & (xyz[:, :, 2].min(axis=1) <= span[1] + guard)
    )
    intrusions, minimum, guarded_minimum, count = [], None, None, 0
    for index in candidates:
        guarded = _clip_height(list(xyz[index]), span[0] - guard, True)
        if guarded:
            guarded = _clip_height(guarded, span[1] + guard, False)
        if guarded:
            distance = _projected_radial_min(guarded)
            guarded_minimum = distance if guarded_minimum is None else min(guarded_minimum, distance)
        polygon = _clip_height(list(xyz[index]), span[0], True)
        if polygon:
            polygon = _clip_height(polygon, span[1], False)
        if not polygon:
            continue
        distance = _projected_radial_min(polygon)
        minimum = distance if minimum is None else min(minimum, distance)
        if distance < radius_m - guard:
            count += 1
            if len(intrusions) < 32:
                intrusions.append(int(index))
    clear = False if count else True if guarded_minimum is None or guarded_minimum > radius_m + guard else None
    return {
        "method": "all_triangle_axial_cylinder_clip_v2",
        "status": "not_measurable" if clear is None else "ok",
        "center_world_m": center.tolist(),
        "axis_world": frame[:, 2].tolist(),
        "span_m": span.tolist(),
        "radius_m": radius_m,
        "boundary_clear": clear,
        "intruding_triangles": count,
        "examples": intrusions,
        "minimum_boundary_radius_m": minimum,
        "guarded_minimum_boundary_radius_m": guarded_minimum,
        "epsilon_m": epsilon_m,
        "numerical_guard_m": guard,
        "triangles_considered": len(candidates),
        "requires_cavity_section_evidence": True,
        "requires_valid_solid_occupancy": True,
    }


def corridor_occupancy(mesh: SurfaceMesh, center, axis, span_m, corridor: dict, *, solid_validated: bool) -> dict:
    """Classify a connected finite cylinder only after its boundary is clear.

    On a validated solid, occupancy is constant in a connected region without
    boundary crossings. One interior winding query then distinguishes outside
    from complete containment. This is NOT sparse sampling used to rule out
    a cap: every potentially intersecting triangle was tested above.
    """
    if type(solid_validated) is not bool:
        raise ValueError("solid_validated must be a trusted validation boolean")
    report = {"method": "guarded_boundary_and_solid_winding_v1", "status": "not_measurable",
              "empty": None, "classification": "unknown", "solid_validated": solid_validated,
              "validation_source": "caller_trusted_inspector_not_a_candidate_declaration",
              "winding_probe": None}
    if not solid_validated:
        report["reason"] = "Validated closed connected consistently oriented solid required"
        return report
    if corridor["boundary_clear"] is None:
        report["reason"] = "Boundary lies in the numerical guard band"
        return report
    if corridor["boundary_clear"] is False:
        report.update(status="ok", empty=False, classification="boundary_intrusion")
        return report
    center, frame = _center(center), axis_frame(axis)
    midpoint = float(span_m[0] / 2 + span_m[1] / 2)
    # Translate both mesh and query by the same origin; do not align a part.
    point = frame[:, 2] * midpoint
    guard = corridor["numerical_guard_m"]
    inside = int(winding_classification(mesh.vertices - center, mesh.triangles,
                                       point[None], epsilon_m=guard)[0])
    report["winding_probe"] = {"point_world_m": (center + point).tolist(), "classification": inside,
                               "tolerance": 1e-5, "epsilon_m": guard}
    if inside == -1:
        report["reason"] = "Ambiguous solid winding classification"
    else:
        report.update(status="ok", empty=inside == 0,
                      classification="outside_solid" if inside == 0 else "contained_in_solid")
    return report


def measure_bore(
    mesh: SurfaceMesh,
    center,
    axis,
    span_m,
    radius_m: float,
    tolerance_m: float,
    *,
    fractions=(0.125, 0.375, 0.625, 0.875),
    epsilon_m=1e-9,
    solid_validated=False,
) -> dict:
    center, frame = _center(center), axis_frame(axis)
    span = np.asarray(span_m, dtype=float)
    if (
        span.shape != (2,)
        or not np.isfinite(span).all()
        or span[0] >= span[1]
        or not np.isfinite(radius_m)
        or not np.isfinite(tolerance_m)
        or not 0 < tolerance_m < radius_m
        or len(fractions) < 2
        or any(not np.isfinite(f) or not 0 < f < 1 for f in fractions)
        or len(set(fractions)) != len(fractions)
    ):
        raise ValueError("Invalid bore sampling or dimensions")
    layers, centers, offsets = [], [], []
    for fraction in fractions:
        offset = float(span[0] + fraction * (span[1] - span[0]))
        section = section_loops(mesh, center, axis, offset, epsilon_m=epsilon_m)
        if section["status"] != "ok":
            layers.append(
                {
                    "status": "not_measurable",
                    "reason": section["reason"],
                    "offset_m": offset,
                }
            )
            continue
        cavities = [
            {
                **circle_boundary(loop["points_m"]),
                "requested_axis_in_cavity": _contains_origin(
                    np.asarray(loop["points_m"])
                ),
            }
            for loop in section["loops"]
            if loop["kind"] == "cavity"
        ]
        if not cavities:
            layers.append(
                {
                    "status": "failed",
                    "reason": "No closed cavity boundary in section",
                    "offset_m": section["offset_m"],
                }
            )
            continue
        measured = min(
            cavities, key=lambda item: np.linalg.norm(item["center_plane_m"])
        )
        local = np.array([*measured["center_plane_m"], section["offset_m"]])
        world = center + frame @ local
        measured.update(
            status="ok",
            offset_m=section["offset_m"],
            center_world_m=world.tolist(),
            max_radius_error_m=max(
                abs(measured["min_boundary_radius_m"] - radius_m),
                abs(measured["max_boundary_radius_m"] - radius_m),
            ),
        )
        layers.append(measured)
        centers.append(world)
        offsets.append(section["offset_m"])
    corridor = axial_corridor(
        mesh, center, axis, span, radius_m - tolerance_m, epsilon_m=epsilon_m
    )
    occupancy = corridor_occupancy(mesh, center, axis, span, corridor, solid_validated=solid_validated)
    complete = len(centers) == len(fractions)
    measurable = occupancy["status"] == "ok" and not any(l["status"] == "not_measurable" for l in layers)
    axis_fit = None
    if len(centers) >= 2:
        values = np.asarray(centers)
        mid = float(np.mean(offsets))
        design = np.column_stack((np.asarray(offsets) - mid, np.ones(len(offsets))))
        fit, _, _, _ = np.linalg.lstsq(design, values, rcond=None)
        direction = fit[0] / np.linalg.norm(fit[0])
        residuals = np.linalg.norm(values - design @ fit, axis=1)
        axis_fit = {
            "point_world_m": fit[1].tolist(),
            "direction_world": direction.tolist(),
            "angle_to_requested_axis_deg": float(
                np.degrees(np.arccos(np.clip(direction @ frame[:, 2], -1, 1)))
            ),
            "max_centerline_residual_m": float(residuals.max()),
        }
    return {
        "method": "validated_solid_sections_and_full_axial_corridor_v2",
        "hard_gate": False,
        "coordinate_space": "world_metres",
        "center_world_m": center.tolist(),
        "requested_axis_world": frame[:, 2].tolist(),
        "span_m": span.tolist(),
        "expected_radius_m": float(radius_m),
        "radius_tolerance_m": float(tolerance_m),
        "section_fractions": [float(f) for f in fractions],
        "epsilon_m": float(epsilon_m),
        "status": "ok" if measurable else "not_measurable",
        "reason": None if measurable else occupancy.get("reason", "Ambiguous section boundary"),
        "layers": layers,
        "axis_fit": axis_fit,
        "corridor": corridor,
        "occupancy": occupancy,
        "all_sections_measured": complete,
        "radius_within_tolerance": complete
        and all(l["max_radius_error_m"] <= tolerance_m + epsilon_m for l in layers),
        "through_corridor": None if not measurable else complete
        and occupancy["empty"] is True and all(l["requested_axis_in_cavity"] for l in layers),
        "max_center_offset_m": max(
            (
                float(np.linalg.norm(l["center_plane_m"]))
                for l in layers
                if l["status"] == "ok"
            ),
            default=None,
        ),
        "limitations": [
            "Section circularity is measured in requested planes; axis tilt is reported separately.",
            "The corridor uses the requested center/axis and radius minus physical tolerance.",
            "Solid validation is a trusted inspector precondition, not independently re-audited here.",
            "Floating-point mesh evidence; guard-band contact is not measurable, not an exact CAD certificate.",
            "Caller must bind the role and full physical thickness; an empty arbitrary cylinder is not a task pass.",
        ],
    }
