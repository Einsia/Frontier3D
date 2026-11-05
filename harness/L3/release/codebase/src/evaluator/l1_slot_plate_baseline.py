"""Public Code014 initial slots, measured from trusted actual section geometry.

Only the evaluator's initial mesh may enter here. This is not a candidate
recognizer and never authorizes fitting arbitrary candidate damage into a mask.
"""
from __future__ import annotations

import time

import numpy as np
import shapely

from .l1_prism_mask import GUARD
from .l1_sections import section_loops

BOX = [[-.040, -.0225, 0.], [.040, .0225, .008]]
RADIUS = .004
HALF_LENGTH = .020
ROWS = (-.011, .011)
# The authoritative 96-sided source's maximum chord error is 2.142 microns.
# Five microns also permits the independent 64-sided analytic test fixture;
# this does not relax the candidate's 50-micron protected-distance threshold.
REPRESENTATION_LIMIT_M = 5e-6


def initial_parameters(mesh, *, solid_validated, deadline):
    if solid_validated is not True:
        raise ValueError('Trusted public initial solid is required')
    if type(deadline) not in (int, float) or not np.isfinite(deadline):
        raise ValueError('Finite public initial measurement deadline required')
    if time.monotonic() >= deadline:
        raise TimeoutError('No public initial section budget')
    bounds = np.array([mesh.vertices.min(axis=0), mesh.vertices.max(axis=0)])
    if np.max(np.abs(bounds-np.asarray(BOX))) > 2*GUARD:
        raise ValueError('Public initial world bounds disagree with Code014 source design')
    # Original source is a straight extrusion with vertices only at both ends.
    # Arbitrary layered/sloped baselines cannot be certified by one section.
    zs = mesh.vertices[:, 2]
    if np.max(np.minimum(np.abs(zs-bounds[0, 2]), np.abs(zs-bounds[1, 2]))) > 2*GUARD:
        raise ValueError('Unsupported non-extruded public initial representation')
    normals = np.cross(mesh.xyz[:, 1]-mesh.xyz[:, 0], mesh.xyz[:, 2]-mesh.xyz[:, 0])
    walls = np.ptp(mesh.xyz[:, :, 2], axis=1) > 2*GUARD
    if np.any(np.abs(normals[walls, 2]) > 1e-7*np.linalg.norm(normals[walls], axis=1)):
        raise ValueError('Public initial has unsupported nonvertical walls')
    section = section_loops(mesh, (0., 0., 0.), (0., 0., 1.), float(bounds[:, 2].mean()))
    if section['status'] != 'ok':
        raise ValueError('Public initial section is not measurable')
    cavities = []
    outer = []
    for row in section['loops']:
        xy = np.asarray(row['points_m']) @ np.asarray(section['basis_world'])[:, :2].T
        polygon = shapely.Polygon(xy[:, :2])
        if not polygon.is_valid:
            raise ValueError('Invalid public initial section polygon')
        (cavities if row['kind'] == 'cavity' else outer).append(polygon)
    if len(cavities) != 2 or len(outer) != 1:
        raise ValueError('Public initial must have exactly two slot cavities')
    rectangle = shapely.box(BOX[0][0], BOX[0][1], BOX[1][0], BOX[1][1]).boundary
    if (not outer[0].boundary.buffer(2*GUARD).covers(rectangle)
            or not rectangle.buffer(2*GUARD).covers(outer[0].boundary)):
        raise ValueError('Public initial exterior differs from its rectangular source')
    rows = []
    used = set()
    for y in ROWS:
        matches = [i for i, p in enumerate(cavities) if p.contains(shapely.Point(0., y))]
        if len(matches) != 1 or matches[0] in used:
            raise ValueError('Public initial slots cannot be matched uniquely')
        used.add(matches[0])
        polygon = cavities[matches[0]]
        axis = shapely.LineString([[-HALF_LENGTH, y], [HALF_LENGTH, y]])
        points = shapely.points(np.asarray(polygon.exterior.coords))
        low = min(float(polygon.boundary.distance(axis)), RADIUS)
        high = max(float(np.max(shapely.distance(points, axis))), RADIUS)
        if low < RADIUS-REPRESENTATION_LIMIT_M or high > RADIUS+2*GUARD:
            raise ValueError('Public initial slot representation differs from its source design')
        rows.append({'kind': 'slot', 'center_xy_m': [0., y], 'radius_m': RADIUS,
            'half_length_m': HALF_LENGTH, 'boundary_radius_interval_m': [low, high]})
    if time.monotonic() >= deadline:
        raise TimeoutError('Public initial section measurement exceeded deadline')
    return {'box_bounds_m': bounds.tolist(), 'slots': rows,
        'representation': 'Actual complete mid-section edge ranges around public fixed capsule axes',
        'representation_limit_m': REPRESENTATION_LIMIT_M}
