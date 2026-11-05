"""Code014 complete horizontal annular shoulders and independent dimensions.

Patch boundaries/union come from actual triangles, never an AABB or a few
section heights. Unrecognised/noisy nonplanar patches stay unmeasured; the
complete surface check separately tests the remaining shape.
"""
from __future__ import annotations

import time

import numpy as np
import shapely

from .l1_capsule_corridor import GUARD
from .l1_sections import circle_boundary
from .l1_sleeve import interval_check, unavailable, verdict
from .l1_slot_plate_sections import validate_design


def _shoulder(mesh, center, design, deadline):
    t = design['dimension_tolerance_m']
    top, bottom = float(mesh.vertices[:, 2].max()), float(mesh.vertices[:, 2].min())
    xyz = mesh.xyz
    normals = np.cross(xyz[:, 1]-xyz[:, 0], xyz[:, 2]-xyz[:, 0])
    radius = np.linalg.norm(xyz[..., :2]-center, axis=-1)
    selected = ((np.ptp(xyz[..., 2], axis=1) <= GUARD)
        & (normals[:, 2] > 0) & (radius.max(axis=1) < design['counterbore_radius_m']+4*t)
        & (xyz[..., 2].min(axis=1) > bottom+4*t) & (xyz[..., 2].max(axis=1) < top-4*t))
    ids = np.flatnonzero(selected)
    if not len(ids):
        return unavailable('No measurable complete horizontal counterbore shoulder')
    heights = xyz[ids, :, 2].mean(axis=1)
    order = np.argsort(heights)
    groups = []
    for index in ids[order]:
        if not groups or abs(float(xyz[index, :, 2].mean())-float(xyz[groups[-1][0], :, 2].mean())) > GUARD:
            groups.append([int(index)])
        else:
            groups[-1].append(int(index))
    annuli = []
    for group in groups:
        if deadline is not None and time.monotonic() >= deadline:
            return unavailable('Shoulder union deadline exhausted')
        triangles = xyz[group]
        union = shapely.union_all(shapely.polygons(triangles[..., :2]))
        if union.geom_type != 'Polygon' or not union.is_valid or len(union.interiors) != 1:
            continue
        if not shapely.Polygon(union.interiors[0]).contains(shapely.Point(center)):
            continue
        outer = circle_boundary(np.asarray(union.exterior.coords)[:-1])
        inner = circle_boundary(np.asarray(union.interiors[0].coords)[:-1])
        checks = {}
        for label, curve, expected in [('inner', inner, design['hole_radius_m']),
                                       ('outer', outer, design['counterbore_radius_m'])]:
            checks[label+'_diameter'] = interval_check(2*curve['min_boundary_radius_m'],
                2*curve['max_boundary_radius_m'], 2*expected, t)
            for axis in (0, 1):
                value = curve['center_plane_m'][axis]
                checks[label+'_center_'+str(axis)] = interval_check(value, value, center[axis], t)
        offset = float(np.linalg.norm(np.asarray(outer['center_plane_m'])-inner['center_plane_m']))
        checks['coaxial_centers'] = interval_check(offset, offset, 0., t)
        z_min, z_max = float(triangles[..., 2].min()), float(triangles[..., 2].max())
        checks['depth'] = interval_check(top-z_max, top-z_min, design['counterbore_depth_m'], t)
        checks['flat_horizontal_patch'] = {'status': 'passed' if z_max-z_min <= 2*GUARD else 'not_measurable',
            'passed': z_max-z_min <= 2*GUARD, 'height_range_m': [z_min, z_max],
            'scope': 'All actual patch vertices; affine faces stay in this height interval'}
        annuli.append({**verdict(**checks), 'z_m': (z_min+z_max)/2, 'triangles': len(group),
            'area_m2': float(union.area), 'inner_circle': inner, 'outer_circle': outer,
            'source_triangle_ids': group, 'top_datum_m': top,
            'method': 'Complete actual coplanar triangle union with one annular hole'})
    if len(annuli) != 1:
        return {**unavailable('A unique complete annular shoulder cannot be established'),
                'horizontal_groups': len(groups), 'annular_groups': len(annuli)}
    if deadline is not None and time.monotonic() >= deadline:
        return unavailable('Shoulder result missed measurement deadline')
    return annuli[0]


def measure_shoulders(mesh, design, *, solid_validated, deadline=None):
    validate_design(design)
    if type(solid_validated) is not bool:
        raise ValueError('Trusted solid validation must be boolean')
    if deadline is not None and (type(deadline) not in (int, float) or not np.isfinite(deadline)):
        raise ValueError('Invalid shoulder measurement deadline')
    results = {}
    datum = (mesh.vertices[:, :2].min(axis=0)+mesh.vertices[:, :2].max(axis=0))/2
    for i, center in enumerate(design['hole_centers_xy_m']):
        if not solid_validated:
            results[str(i)] = unavailable('Trusted solid validation required')
        elif deadline is not None and time.monotonic() >= deadline:
            results[str(i)] = unavailable('Shoulder measurement deadline exhausted')
        else:
            results[str(i)] = _shoulder(mesh, np.asarray(center)+datum, design, deadline)
    return {**verdict(**results), 'protocol': 'l1-slot-plate-shoulders-v1',
            'plate_center_xy_m': datum.tolist(),
            'scope': 'Actual annular planes and independent relative positions/depth/diameters, not whole-body preservation'}
