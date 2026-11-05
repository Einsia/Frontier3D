"""Conservative source-triangle complement of finite polygonal edit prisms.

Inner masks are safe to exclude for a PASS; outer masks may only be excluded
to establish a FAIL witness. Actual source planes are retained, with no model
alignment or area-based dropping of small positive-area surface fragments.
"""
from __future__ import annotations

import time

import numpy as np
import shapely
from shapely.affinity import affine_transform

from .l1_protected_surface import split_polygon

GUARD = 8e-9
CLIP_ERROR_M = 1e-9


def _polygons(geometry):
    if geometry.geom_type == 'Polygon':
        if not geometry.is_empty:
            yield geometry
    elif hasattr(geometry, 'geoms'):
        for part in geometry.geoms:
            yield from _polygons(part)


def _lines(geometry):
    if geometry.geom_type == 'LineString':
        if not geometry.is_empty:
            yield geometry
    elif hasattr(geometry, 'geoms'):
        for part in geometry.geoms:
            yield from _lines(part)


def triangle_complement(triangle, regions, *, envelope, _mask_cache=None):
    """Return actual world triangles outside an inner/outer mask, or unknown."""
    if envelope not in {'inner', 'outer'}:
        raise ValueError('Select explicit inner or outer allowed-region enclosure')
    triangle = np.asarray(triangle, dtype=float)
    if triangle.shape != (3, 3) or not np.isfinite(triangle).all():
        raise ValueError('Expected finite world triangle')
    normal = np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])
    norm = float(np.linalg.norm(normal))
    if norm <= 1e-24:
        raise ValueError('Degenerate source plane')
    normal /= norm
    # Use the actual source plane even for near-vertical faces produced by
    # retriangulation. Bound the small XY drift explicitly, never align it.
    vertical_like = abs(normal[2]) < 1e-7
    origin = triangle[0]
    if normal[0] == 0 and normal[1] == 0:
        # Preserve world XY exactly for horizontal caps. Rotating a very thin
        # clipped cap into its first-edge frame can create degenerate long
        # triangles inside a removed region through cancellation alone.
        origin = np.array([0., 0., origin[2]])
        u, v = np.array([1., 0., 0.]), np.array([0., 1., 0.])
    elif vertical_like:
        u = np.array([-normal[1], normal[0], 0.])
        u /= np.linalg.norm(u)
        v = np.cross(normal, u)
    else:
        u = triangle[1]-triangle[0]
        u /= np.linalg.norm(u)
        v = np.cross(normal, u)
    basis = np.column_stack((u, v))
    uv = (triangle-origin) @ basis
    xy_drift = float(np.max(np.abs(uv[:, 1]))*np.linalg.norm(v[:2])) if vertical_like else 0.
    if xy_drift > CLIP_ERROR_M:
        return None
    source = shapely.Polygon(uv)
    cache = {} if _mask_cache is None else _mask_cache
    cache_key = (envelope, float(origin[2])) if normal[0] == normal[1] == 0 else None
    mask_parts = []
    for row in ([] if cache_key in cache else regions):
        low, high = row[envelope+'_span_m']
        footprint = row[envelope]
        if footprint.is_empty or low >= high or triangle[:, 2].max() < low or triangle[:, 2].min() > high:
            continue
        if vertical_like:
            if xy_drift > 0:
                # A 2 nm inscribed expansion contains the <=1 nm drift disk;
                # contraction is correspondingly conservative for PASS.
                footprint = footprint.buffer((-1 if envelope == 'inner' else 1)*2*CLIP_ERROR_M)
            lo, hi = float(uv[:, 0].min())-GUARD, float(uv[:, 0].max())+GUARD
            segment = shapely.LineString([origin[:2]+lo*u[:2], origin[:2]+hi*u[:2]])
            for line in _lines(footprint.intersection(segment)):
                coordinates = (np.asarray(line.coords)-origin[:2]) @ u[:2]
                mask_parts.append(shapely.box(float(coordinates.min()), (low-origin[2])/v[2],
                                             float(coordinates.max()), (high-origin[2])/v[2]))
        else:
            inverse = np.linalg.inv(basis[:2])
            shift = -inverse @ origin[:2]
            coefficients = [*inverse[0], *inverse[1], *shift]
            transformed = affine_transform(footprint, coefficients)
            # Clip the MASK to its Z slab, not to the source triangle first.
            # Otherwise eroding that clipped mask incorrectly makes a source
            # edge inside the allowed volume appear protected.
            if not np.any(basis[2]):
                mask_parts.append(transformed)
                continue
            xmin, ymin, xmax, ymax = transformed.bounds
            clipped = np.array([[xmin-GUARD, ymin-GUARD], [xmax+GUARD, ymin-GUARD],
                                [xmax+GUARD, ymax+GUARD], [xmin-GUARD, ymax+GUARD]])
            for n, offset in ((basis[2], high-origin[2]), (-basis[2], origin[2]-low)):
                if len(clipped) < 3:
                    break
                clipped, _ = split_polygon(clipped, n, offset)
            if len(clipped) >= 3:
                mask_parts.append(transformed.intersection(shapely.Polygon(clipped)))
    if cache_key in cache:
        allowed, allowed_interior, allowed_neighbourhood = cache[cache_key]
    else:
        allowed = shapely.union_all(mask_parts)
        allowed_interior = allowed.buffer(-2*CLIP_ERROR_M)
        allowed_neighbourhood = allowed.buffer(CLIP_ERROR_M, quad_segs=4)
        shapely.prepare(allowed)
        shapely.prepare(allowed_interior)
        if cache_key is not None:
            cache[cache_key] = allowed, allowed_interior, allowed_neighbourhood
    if allowed.covers(source):
        return []
    if not allowed.intersects(source):
        return [triangle.copy()]
    remaining = source.difference(allowed)
    if not remaining.is_valid:
        return None
    triangles, all_faces = [], []
    remaining_neighbourhood = remaining.buffer(CLIP_ERROR_M, quad_segs=4)
    shapely.prepare(remaining_neighbourhood)
    for polygon in _polygons(remaining):
        faces = list(shapely.constrained_delaunay_triangles(polygon).geoms)
        if not faces:
            return None
        for face in faces:
            if allowed.covers(face) and allowed.covers(face.boundary):
                continue
            # Some triangulators emit a collinear/near-collinear long face
            # across the removed region. A polygon union can silently erase
            # it, while the raw 3D triangle would later create a false witness.
            # Reject that output face geometrically, then certify COMPLETE
            # source coverage below. No small-area threshold is involved.
            if (allowed_interior.intersects(face)
                    or allowed_interior.intersects(face.boundary)):
                continue
            if not remaining_neighbourhood.covers(face.boundary):
                return None
            all_faces.append(face)
            points = np.asarray(face.exterior.coords)[:-1]
            if points.shape != (3, 2):
                return None
            triangles.append(origin+points @ basis.T)
    # Boolean/triangulation roundoff can leave extremely thin long slivers.
    # NEVER discard them by area. Certify a continuous distance enclosure:
    # inscribed round buffers are subsets of the 1 nm Euclidean neighbourhood.
    # The mask reserves 8 nm, so proximity to its inner mask remains allowed;
    # proximity to a returned face is charged to the final distance bound.
    faces_union = shapely.union_all(all_faces)
    covered = shapely.union_all([faces_union.buffer(CLIP_ERROR_M, quad_segs=4), allowed_neighbourhood])
    if (not covered.covers(source)
            or (not faces_union.is_empty
                and not remaining_neighbourhood.covers(faces_union))):
        return None
    if envelope == 'outer' and not faces_union.intersection(allowed.buffer(-CLIP_ERROR_M)).is_empty:
        return None
    return triangles


def clip_protected(mesh, regions, *, envelope, deadline, max_triangles=262144):
    if (type(deadline) not in (int, float) or not np.isfinite(deadline)
            or type(max_triangles) is not int or max_triangles <= 0):
        raise ValueError('Invalid prism clipping budget')
    if envelope not in {'inner', 'outer'}:
        raise ValueError('Select explicit mask enclosure')
    triangles, cache = [], {}
    for index, source in enumerate(mesh.xyz):
        if time.monotonic() >= deadline:
            return None, {'status': 'not_measurable', 'reason': 'Protected clipping deadline exhausted', 'source_processed': index}
        pieces = triangle_complement(source, regions, envelope=envelope, _mask_cache=cache)
        if pieces is None:
            return None, {'status': 'not_measurable', 'reason': 'Unresolved actual source-plane clipping', 'source_processed': index}
        triangles.extend(pieces)
        if len(triangles) > max_triangles:
            return None, {'status': 'not_measurable', 'reason': 'Protected clipping triangle budget exhausted', 'source_processed': index}
    if time.monotonic() >= deadline:
        return None, {'status': 'not_measurable', 'reason': 'Clipping result missed deadline'}
    values = np.asarray(triangles).reshape(-1, 3, 3)
    area = float(np.linalg.norm(np.cross(values[:, 1]-values[:, 0], values[:, 2]-values[:, 0]), axis=1).sum()/2)
    return values, {'status': 'measured', 'source_triangles': len(mesh.triangles), 'clipped_triangles': len(values),
                    'clipped_area_m2': area, 'allowed_enclosure': envelope,
                    'surface_approximation_m': CLIP_ERROR_M,
                    'coverage': 'Complete source covered by returned-face or guarded-mask distance neighbourhood; no area cutoff'}
