"""Area enclosures for a triangle's distance to a complete triangle union.

Project every potentially nearby target face onto the source plane. Clipping
to a distance slab and OUTER polygonal disk offsets encloses its distance
neighbourhood. INNER offsets of actual target sub-polygons are contained in
that neighbourhood. Taking unions preserves holes and does not infer area
from sampled vertices. Floating-point guards are not exact CAD arithmetic.
"""
from __future__ import annotations

import numpy as np
import shapely
from shapely.errors import GEOSException

from .l1_cylinder_area import allowed_regions, frame, overlay_area_guard
from .l1_plane_prism import edge_inner_sections, triangle_prism_section
from .l1_protected_surface import split_polygon
from .l1_revolution import EPSILON_M

GUARD = 4*EPSILON_M
SEGMENTS = 16


def _projection(points):
    # A target face may project to a segment or a point, both of which have
    # a nonempty distance neighbourhood. Never discard zero-area projections.
    return shapely.convex_hull(shapely.MultiPoint(points[:, :2]))


def _slab(points, low, high):
    for normal, offset in ((np.array([0., 0., 1.]), high), (np.array([0., 0., -1.]), -low)):
        if len(points) == 0:
            break
        points, _ = split_polygon(points, normal, offset)
    return points


def triangle_area_bounds(triangle, target, tolerance, *, boxes=None, cache=None, visits=None,
                         allowed_region=None, domain_cache=None, plane_hint=None):
    """Return [certainly beyond tolerance, possibly beyond tolerance] in m².

    Every target triangle enters either the conservative box exclusion or the
    actual projected neighbourhood. Target faces are NOT convex-hulled with
    one another. Unsupported/ill-conditioned geometry yields no new bound.
    """
    triangle = np.asarray(triangle, dtype=float)
    if triangle.shape != (3, 3) or not np.isfinite(triangle).all() or tolerance <= 8*GUARD:
        return None
    plane = frame(triangle, plane_hint)
    if plane is None:
        return None
    normal, offset, origin, basis, total = plane
    polygon = shapely.Polygon(((triangle-origin) @ basis)[:, :2])
    if polygon.area <= 1e-24 or not .5 <= total/polygon.area <= 2:
        return None
    area_scale = total/polygon.area
    regions = allowed_regions(plane, allowed_region, cache=domain_cache) if allowed_region is not None else None
    if allowed_region is not None and regions is None:
        return None
    # Exact plane keys only: nearby but different planes must not inherit
    # another plane's proof. Cached envelopes use ALL target triangles in
    # the plane slab, not the first source triangle's local bounding box.
    key = (id(target), tolerance, *normal.tolist(), offset)
    cached = cache.get(key) if cache is not None else None
    if visits is not None:
        visits[key] = visits.get(key, 0)+1
    # Curved meshes can have a different plane for each pair of faces. Do
    # not build a whole-object slab union for every such one-off query.
    save = cache is not None and len(cache) < 512 and (visits is None or visits[key] >= 4)
    try:
        if cached is None:
            if save:
                heights = (target.xyz-origin) @ normal
                selected = (heights.min(axis=1) <= tolerance+GUARD) & (heights.max(axis=1) >= -tolerance-GUARD)
            else:
                low, high = boxes if boxes is not None else (target.xyz.min(axis=1), target.xyz.max(axis=1))
                gaps = np.maximum(np.maximum(low-triangle.max(axis=0), triangle.min(axis=0)-high), 0.)
                selected = np.linalg.norm(gaps, axis=1) <= tolerance+GUARD
            if not selected.any() and allowed_region is None:
                return {'bounds_m2': [total, total], 'target_faces': 0, 'outer_pieces': 0, 'inner_pieces': 0}
            faces = (target.xyz[selected]-origin) @ basis
            inside, outside = [], []
            limits_xy = np.asarray(polygon.bounds)
            for face in faces:
                clipped = _slab(face, -tolerance-GUARD, tolerance+GUARD)
                if not len(clipped):
                    continue
                if not save:
                    gap = np.maximum(np.maximum(clipped[:, :2].min(axis=0)-limits_xy[2:],
                                                 limits_xy[:2]-clipped[:, :2].max(axis=0)), 0.)
                    if np.linalg.norm(gap) > tolerance+GUARD:
                        continue
                heights = clipped[:, 2]
                minimum_height = 0. if heights.min() <= 0 <= heights.max() else float(np.abs(heights).min())
                # Circumscribed offset includes the complete 3D tube's
                # projection, not just projections of sampled close points.
                # GUARD is a Euclidean displacement allowance on the 3D
                # tube radius, already covering the <=1 nm source projection.
                # Do not apply the same displacement AGAIN to both height
                # and horizontal radius: for coplanar faces that doubles the
                # physical uncertainty strip without adding new evidence.
                outer_radius = np.sqrt(max(0., (tolerance+GUARD)**2-minimum_height**2))
                outer = _projection(clipped).buffer(outer_radius/np.cos(np.pi/(4*SEGMENTS)), quad_segs=SEGMENTS)
                outer, prism = triangle_prism_section(face, outer, tolerance)
                outside.append(outer)
                if not prism.is_empty:
                    inside.append(prism)
                # For constant height, one projected rounded face is enough.
                # Tilted faces use their normal prism, real finite edge
                # cylinders and vertex balls, not coarse height partitions.
                if np.ptp(face[:, 2]) <= EPSILON_M:
                    parts = [face]
                else:
                    inside.extend(edge_inner_sections(face, tolerance))
                    parts = []
                for part in parts:
                    if not len(part):
                        continue
                    maximum_height = float(np.abs(part[:, 2]).max())
                    if maximum_height >= tolerance-GUARD:
                        continue
                    inner_radius = np.sqrt((tolerance-GUARD)**2-maximum_height**2)
                    if inner_radius > 0:
                        inside.append(_projection(part).buffer(inner_radius, quad_segs=SEGMENTS))
            outer_union = shapely.union_all(outside, grid_size=0)
            inner_union = shapely.union_all(inside, grid_size=0)
            if not outer_union.is_valid or not inner_union.is_valid:
                return None
            cached = (outer_union, inner_union, int(selected.sum()), len(outside), len(inside), target)
            if save:
                cache[key] = cached
        outer_union, inner_union, count, nouter, ninner, _ = cached
        certain_change = polygon.difference(outer_union)
        possible_change = polygon.difference(inner_union)
        if regions is not None:
            # Joint intersection of actual protection and actual distance
            # exceedance. Do not add independently bounded marginal areas.
            allowed_inner, allowed_outer = regions
            certain_change = certain_change.difference(allowed_outer)
            possible_change = possible_change.difference(allowed_inner)
        area_guard = overlay_area_guard(polygon, outer_union, inner_union, certain_change, possible_change)
        if not np.isfinite(area_guard):
            return None
        lower = max(0., float(certain_change.area)-area_guard)*area_scale
        upper = 0. if possible_change.is_empty else min(total, (float(possible_change.area)+area_guard)*area_scale)
        if lower > upper:
            return None
        return {'bounds_m2': [lower, upper], 'target_faces': count,
                'outer_pieces': nouter, 'inner_pieces': ninner, 'area_arithmetic_guard_m2': area_guard}
    except GEOSException:
        return None
