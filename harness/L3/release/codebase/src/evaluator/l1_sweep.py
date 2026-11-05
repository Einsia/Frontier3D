"""Continuous surface bounds for Text014's case-bound polynomial sweep.

The reference is exported from the specified OCC construction, not a sampled
candidate or a fitted shape. Subdivided Bernstein control hulls bound its
replacement by planar polygon boundaries. Complete candidate triangles are then bounded in
both directions; sparse sample agreement alone never earns a pass.
"""
from __future__ import annotations

from itertools import pairwise

import numpy as np
import shapely
from shapely.errors import GEOSException

from .l1_protected_surface import near_planar_cover
from .l1_revolution import (
    EPSILON_M,
    convex_patch_neighbors,
    triangle_to_mesh_upper,
)
from .l1_surface import SurfaceMesh, surface_distances

PROTOCOL = 'l1-polynomial-sweep-bounds-v1'
REFERENCE_PROTOCOL = 'l1-sweep-polynomial-reference-v1'
GUARD = 8*EPSILON_M


def validate_reference(reference):
    if (not isinstance(reference, dict) or reference.get('protocol') != REFERENCE_PROTOCOL
            or reference.get('units') != 'metres'):
        raise ValueError('Expected evaluator-owned polynomial sweep reference in metres')
    depth = reference.get('depth_m')
    if type(depth) not in (int, float) or not np.isfinite(depth) or depth <= GUARD:
        raise ValueError('Invalid sweep depth')
    strips = reference.get('strips_xz_m')
    if not isinstance(strips, list) or not 1 <= len(strips) <= 64:
        raise ValueError('Expected 1–64 polynomial sweep spans')
    result = []
    for strip in strips:
        values = np.asarray(strip, dtype=float)
        if (values.ndim != 3 or values.shape[0] != 2 or values.shape[2] != 2
                or not 2 <= values.shape[1] <= 17 or not np.isfinite(values).all()):
            raise ValueError('Sweep span requires two degree 1–16 XZ Bernstein curves')
        if result and np.max(np.linalg.norm(values[:, 0]-result[-1][:, -1], axis=-1)) > EPSILON_M:
            raise ValueError('Sweep boundary curves are discontinuous')
        result.append(values)
    return result, float(depth)


def split_strip(strip):
    """Exact de Casteljau bisection of both same-parameter boundary curves."""
    work = strip.copy()
    left, right = [work[:, 0]], [work[:, -1]]
    while work.shape[1] > 1:
        work = (work[:, :-1]+work[:, 1:])/2
        left.append(work[:, 0])
        right.append(work[:, -1])
    return np.stack(left, axis=1), np.stack(right[::-1], axis=1)


def chord_bound(strip):
    """Same-parameter curve/chord distance bounded by all coefficient errors."""
    t = np.linspace(0, 1, strip.shape[1])[None, :, None]
    linear = (1-t)*strip[:, :1]+t*strip[:, -1:]
    return float(np.linalg.norm(strip-linear, axis=-1).max())


def reference_mesh(reference, *, error_m, max_segments=8192, max_depth=20):
    strips, depth = validate_reference(reference)
    if (type(error_m) not in (int, float) or not np.isfinite(error_m) or error_m <= 2*GUARD
            or type(max_segments) is not int or max_segments <= 0
            or type(max_depth) is not int or not 0 <= max_depth <= 30):
        raise ValueError('Invalid sweep reference approximation budget')
    pending = [(span, 0) for span in strips[::-1]]
    leaves = []
    while pending:
        span, level = pending.pop()
        bound = chord_bound(span)
        if bound+GUARD < error_m:
            leaves.append((span, bound))
        elif level >= max_depth:
            raise ValueError('Unresolved polynomial span at reference depth limit')
        else:
            a, b = split_strip(span)
            pending.extend([(b, level+1), (a, level+1)])
        if len(pending)+len(leaves) > max_segments:
            raise ValueError('Sweep reference segment budget exhausted')
    # The planar broad faces are trimmed domains, NOT unions of corresponding
    # across-width ruled quads: such rulings can fold at the tight bend even
    # when the boundary is simple. Triangulate the actual simple boundary.
    # The same-parameter curve/chord homotopy stays within `bound` of either
    # boundary. Winding cannot change outside that tube, so the two filled
    # planar domains have the same two-sided Hausdorff error bound.
    left = [span[0, 0] for span, _ in leaves]+[leaves[-1][0][0, -1]]
    right = [span[1, 0] for span, _ in leaves]+[leaves[-1][0][1, -1]]
    polygon = shapely.Polygon(left+right[::-1])
    if not polygon.is_valid or polygon.area <= 1e-18:
        raise ValueError('Reference polygon is not a valid simple planar domain')
    polygon = shapely.orient_polygons(polygon)
    faces = list(shapely.constrained_delaunay_triangles(polygon).geoms)
    if not faces or not shapely.union_all(faces).equals(polygon):
        raise ValueError('Reference planar triangles do not cover exactly the bounded domain')
    # Equal curve endpoints are welded on a fixed 1e-14 m grid; GUARD covers
    # this as well as the <=1e-9 m source join discrepancy.
    vertices, triangles, lookup = [], [], {}

    def vertex(xz, y):
        xyz = tuple(np.round([xz[0], y, xz[1]], 14))
        if xyz not in lookup:
            lookup[xyz] = len(vertices)
            vertices.append(xyz)
        return lookup[xyz]

    boundary = list(polygon.exterior.coords)
    for a, b in pairwise(boundary):
        al, ah, bl, bh = vertex(a, -depth/2), vertex(a, depth/2), vertex(b, -depth/2), vertex(b, depth/2)
        triangles.extend([(al, ah, bh), (al, bh, bl)])
    for face in faces:
        points = list(shapely.orient_polygons(face).exterior.coords)[:-1]
        if len(points) != 3:
            raise ValueError('Unexpected non-triangle reference face')
        triangles.append(tuple(vertex(p, -depth/2) for p in points))
        triangles.append(tuple(vertex(p, depth/2) for p in points[::-1]))
    mesh = SurfaceMesh(vertices, np.asarray(triangles))
    signed_volume = np.einsum('ij,ij->i', mesh.xyz[:, 0], np.cross(mesh.xyz[:, 1], mesh.xyz[:, 2])).sum()/6
    if signed_volume < 0:
        mesh = SurfaceMesh(mesh.vertices, mesh.triangles[:, ::-1])
    return mesh, {'method': 'Bernstein boundary/chord hull, winding-preserving planar fill and constrained triangulation',
        'continuous_hausdorff_bound_m': max(bound for _, bound in leaves)+GUARD,
        'segments': len(leaves), 'triangles': len(mesh.triangles), 'planar_area_m2': polygon.area,
        'guard_m': GUARD, 'scope': 'Both full reference surface directions, not tessellation settings or sampled maxima'}


def bisect_triangles(triangles):
    """Split the actual longest edge; avoid four-way growth in thin strips."""
    lengths = np.linalg.norm(np.roll(triangles, -1, axis=1)-triangles, axis=-1)
    starts = np.argmax(lengths, axis=1)
    rows = np.arange(len(triangles))
    a, b, c = [triangles[rows, (starts+i) % 3] for i in range(3)]
    middle = (a+b)/2
    return np.concatenate([np.stack([a, middle, c], axis=1), np.stack([middle, b, c], axis=1)])


def directed_sweep_bound(source, target, *, tolerance_m, approximation_m, max_patches, max_depth=24):
    """Complete triangle bounds, with full planar unions for the broad faces."""
    pending, processed, proved, witnessed, union_proofs = source, 0, 0., 0., 0
    patches, planar_cache = convex_patch_neighbors(target), {}
    summary = {'status': 'not_measurable', 'continuous_upper_bound_m': None}

    def result(**fields):
        return {**summary, 'processed_patches': processed, 'witness_lower_bound_m': witnessed,
                'planar_union_proofs': union_proofs, **fields}

    for depth in range(max_depth+1):
        remaining = []
        for start in range(0, len(pending), 256):
            batch = pending[start:start+256]
            if processed+len(batch) > max_patches:
                return result(reason='Sweep subdivision patch budget exhausted')
            processed += len(batch)
            upper = triangle_to_mesh_upper(batch, target, patches)+approximation_m
            centers = batch.mean(axis=1)
            radii = np.linalg.norm(batch-centers[:, None], axis=2).max(axis=1)
            tiny = (radii < (tolerance_m-approximation_m)/2) & (upper >= tolerance_m-EPSILON_M)
            if tiny.any():
                upper[tiny] = np.minimum(upper[tiny], surface_distances(centers[tiny], target)+radii[tiny]+approximation_m)
            # A face can cross many triangulation seams without differing
            # geometrically. The union proof retains holes and uses actual
            # target triangles, not the convex hull of the whole broad face.
            planar = np.ptp(batch[..., 1], axis=1) <= EPSILON_M
            for index in np.flatnonzero(planar & (upper >= tolerance_m-EPSILON_M)):
                covered, _ = near_planar_cover(batch[index], target, tolerance_m-approximation_m, cache=planar_cache)
                if covered:
                    error = (tolerance_m-approximation_m-32*EPSILON_M)*np.sqrt(2)/3+EPSILON_M
                    upper[index] = approximation_m+error
                    union_proofs += 1
            accepted = upper < tolerance_m-EPSILON_M
            if accepted.any():
                proved = max(proved, float(upper[accepted].max()))
            if (~accepted).any():
                unresolved = batch[~accepted]
                selected = np.argsort(upper[~accepted])[-4:]
                points = np.concatenate([unresolved[selected].reshape(-1, 3), unresolved[selected].mean(axis=1)])
                witnessed = max(witnessed, float(np.maximum(surface_distances(points, target)-approximation_m, 0.).max()))
                if witnessed > tolerance_m+EPSILON_M:
                    return result(status='failed', reason='Actual surface-distance witness exceeds tolerance')
                remaining.append(unresolved)
        if not remaining:
            return result(status='passed', continuous_upper_bound_m=proved, depth=depth)
        pending = np.concatenate(remaining)
        if depth == max_depth or processed+2*len(pending) > max_patches:
            return result(reason='Unresolved sweep patches at subdivision/depth budget')
        pending = bisect_triangles(pending)
    raise AssertionError('Unreachable sweep subdivision state')


def compare_sweep(mesh, reference, tolerance_m, *, max_patches=262144, max_segments=8192):
    if (type(tolerance_m) not in (int, float) or not np.isfinite(tolerance_m)
            or tolerance_m <= 64*GUARD or type(max_patches) is not int or max_patches <= 0):
        raise ValueError('Invalid sweep comparison tolerance or patch budget')
    try:
        target, approximation = reference_mesh(reference, error_m=tolerance_m/16, max_segments=max_segments)
    except (ValueError, GEOSException) as error:
        return {'protocol': PROTOCOL, 'status': 'not_measurable', 'passed': False, 'reason': str(error)}
    bound = approximation['continuous_hausdorff_bound_m']
    forward = directed_sweep_bound(mesh.xyz, target, tolerance_m=tolerance_m,
                                  approximation_m=bound, max_patches=max_patches)
    reverse = directed_sweep_bound(target.xyz, mesh, tolerance_m=tolerance_m,
                                  approximation_m=bound, max_patches=max_patches)
    statuses = {forward['status'], reverse['status']}
    status = 'failed' if 'failed' in statuses else 'passed' if statuses == {'passed'} else 'not_measurable'
    return {'protocol': PROTOCOL, 'status': status, 'passed': status == 'passed',
        'coordinate_space': 'world_metres', 'alignment': 'None; fixed public world datum and scale',
        'tolerance_m': tolerance_m, 'reference_approximation': approximation,
        'candidate_to_reference': forward, 'reference_to_candidate': reverse,
        'limitations': ['Floating-point conservative bounds with explicit guard, not exact arithmetic.',
            'Solid validity, independent section dimensions, editable delivery and materials require separate checks.',
            'Only the authored nonrational planar corrected-Frenet sweep is supported; no candidate-fitted reference.']}
