"""Inner/outer plane sections of a finite allowed-edit cylinder.

The source geometry is never tessellated by a many-sided subtraction prism.
Inscribed/circumscribed radial polygons enclose the analytic circular domain;
axial caps are kept independent. All shapes remain in the original world
frame. These are guarded floating-point bounds, not exact CAD arithmetic.
"""
from __future__ import annotations

import numpy as np
import shapely

from .l1_protected_surface import split_polygon
from .l1_revolution import EPSILON_M

GUARD = 4*EPSILON_M
SIDES = 2048


def overlay_area_guard(*geometries):
    """Area-arithmetic allowance, separate from metric boundary uncertainty.

    Distance and cylinder sets already include GUARD metres of geometric
    padding. Padding every original triangle perimeter *again* introduces a
    tessellation-dependent physical strip unrelated to overlay roundoff.
    Polygon shoelace arithmetic instead scales with coordinate products and
    vertex count. Retain a wide operation allowance and fail closed at huge
    scale/complexity; this does not claim exact-arithmetic GEOS predicates.
    """
    coordinates = [shapely.get_coordinates(g) for g in geometries]
    count = sum(len(c) for c in coordinates)
    if count == 0:
        return 0.
    scale = max(float(np.abs(c).max()) for c in coordinates if len(c))
    operations = 512*count
    error = operations*np.finfo(float).eps
    if error >= .01 or not np.isfinite(scale*scale):
        return np.inf
    return float(error/(1-error)*max(scale*scale, np.finfo(float).tiny))


def frame(triangle, hint=None):
    triangle = np.asarray(triangle, dtype=float)
    normal = np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])
    norm = np.linalg.norm(normal)
    if not np.isfinite(norm) or norm <= 1e-24:
        return None
    if hint is not None:
        hn, ho, origin, basis, _ = hint
        # Descendants mathematically remain in their original triangle's
        # plane. Reuse that frame only after checking every computed vertex.
        # This sub-nanometre projection error fits inside the unchanged 4 nm
        # geometric guards; it is not an alignment of the candidate model.
        if np.max(np.abs((triangle-origin) @ hn)) <= EPSILON_M:
            return hn, ho, origin, basis, float(norm/2)
    normal /= norm
    if normal[np.argmax(np.abs(normal))] < 0:
        normal = -normal
    axis = np.eye(3)[np.argmin(np.abs(normal))]
    first = np.cross(axis, normal)
    first /= np.linalg.norm(first)
    basis = np.column_stack((first, np.cross(normal, first), normal))
    offset = float(triangle[0] @ normal)
    return normal, offset, normal*offset, basis, float(norm/2)


def _section(normal, offset, origin, basis, center_xy, radius, span, *, outer):
    radius = radius+GUARD if outer else max(0., radius-GUARD)
    low, high = (span[0]-GUARD, span[1]+GUARD) if outer else (span[0]+GUARD, span[1]-GUARD)
    if radius == 0 or low >= high:
        return shapely.GeometryCollection()
    if normal[2] == 0:
        # A vertical plane cuts the circular cylinder in a rectangle (or an
        # empty/tangent set). This is not the object's bounding box.
        direction = np.array([-normal[1], normal[0]])
        distance = offset-normal[:2] @ center_xy
        if abs(distance) > radius:
            return shapely.GeometryCollection()
        center = np.asarray(center_xy)+distance*normal[:2]
        reach = np.sqrt(max(0., radius*radius-distance*distance))
        if reach == 0:
            return shapely.GeometryCollection()
        left, right = center-reach*direction, center+reach*direction
        points = np.array([[*left, low], [*right, low], [*right, high], [*left, high]])
    elif abs(normal[2]) >= 1e-6:
        # Radial XY circle polygons map affinely into this plane. Affine
        # maps preserve set containment, so their ellipses remain enclosures.
        angles = np.arange(SIDES)*2*np.pi/SIDES
        radial = radius/np.cos(np.pi/SIDES) if outer else radius
        xy = np.asarray(center_xy)+radial*np.column_stack((np.cos(angles), np.sin(angles)))
        z = (offset-xy @ normal[:2])/normal[2]
        points = np.column_stack((xy, z))
        for vector, value in ((np.array([0., 0., 1.]), high), (np.array([0., 0., -1.]), -low)):
            if len(points) < 3:
                return shapely.GeometryCollection()
            points, _ = split_polygon(points, vector, value)
    else:
        # Near-vertical affine maps can be ill-conditioned. Leave a genuine
        # unknown rather than substituting a different plane or cylinder.
        return None
    # The final cap clip can empty the polygon too, not just the first one.
    if len(points) < 3:
        return shapely.GeometryCollection()
    polygon = shapely.Polygon(((points-origin) @ basis)[:, :2])
    return polygon if polygon.is_valid else None


def allowed_regions(plane, region, *, cache=None):
    normal, offset, origin, basis, _ = plane
    center_xy, radius, span = region['center_xy'], region['radius'], region['span']
    key = (*normal.tolist(), offset, *center_xy, radius, *span)
    if cache is not None and key in cache:
        return cache[key]
    inner, outer = [_section(normal, offset, origin, basis, center_xy, radius, span, outer=value)
                    for value in (False, True)]
    result = None if inner is None or outer is None else (inner, outer)
    if cache is not None and len(cache) < 512:
        cache[key] = result
    return result


def protected_domain_bounds(triangle, region, *, cache=None, plane_hint=None):
    plane = frame(triangle, plane_hint)
    if plane is None:
        return None
    regions = allowed_regions(plane, region, cache=cache)
    if regions is None:
        return None
    _, _, origin, basis, total = plane
    polygon = shapely.Polygon(((triangle-origin) @ basis)[:, :2])
    if polygon.area <= 1e-24 or not .5 <= total/polygon.area <= 2:
        return None
    area_scale = total/polygon.area
    inner, outer = regions
    certain = polygon.difference(outer)
    possible = polygon.difference(inner)
    area_guard = overlay_area_guard(polygon, inner, outer, certain, possible)
    if not np.isfinite(area_guard):
        return None
    lower = max(0., float(certain.area)-area_guard)*area_scale
    upper = 0. if possible.is_empty else min(total, (float(possible.area)+area_guard)*area_scale)
    return [lower, upper]
