"""Code013 complete actual socket shoulder/end annuli and independent depth.

Select entire coplanar triangle unions, not points near the nominal shoulder.
Only flat X-normal ring representations are currently supported; absent or
ambiguous rings stay unmeasured. Full shape and preservation are separate.
"""
from __future__ import annotations

import copy
import time

import numpy as np
import shapely

from .l1_capsule_corridor import GUARD
from .l1_sections import circle_boundary
from .l1_sleeve import interval_check, unavailable, verdict
from .l1_t_joint_paths import validate_design


def _annuli(mesh, design, deadline):
    xyz = mesh.xyz
    normal = np.cross(xyz[:, 1]-xyz[:, 0], xyz[:, 2]-xyz[:, 0])
    center = np.array([0., design['branch_z_m']])
    distance = np.linalg.norm(xyz[..., 1:]-center, axis=-1)
    t = design['dimension_tolerance_m']
    selected = ((np.ptp(xyz[..., 0], axis=1) <= GUARD) & (normal[:, 0] > 0)
        & (xyz[..., 0].min(axis=1) > design['main_outer_radius_m']+4*t)
        & (distance.max(axis=1) < design['branch_outer_radius_m']+4*t))
    ids = np.flatnonzero(selected)
    groups = []
    for index in ids[np.argsort(xyz[ids, :, 0].mean(axis=1))]:
        if not groups or abs(float(xyz[index, :, 0].mean()-xyz[groups[-1][0], :, 0].mean())) > GUARD:
            groups.append([int(index)])
        else:
            groups[-1].append(int(index))
    rings = []
    for group in groups:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError('Socket plane union deadline exhausted')
        triangles = xyz[group]
        shape = shapely.union_all(shapely.polygons(triangles[..., 1:]))
        if shape.geom_type != 'Polygon' or not shape.is_valid or len(shape.interiors) != 1:
            continue
        if not shapely.Polygon(shape.interiors[0]).contains(shapely.Point(center)):
            continue
        rings.append({'source_triangle_ids': group, 'area_m2': float(shape.area),
            'x_interval_m': [float(triangles[..., 0].min()), float(triangles[..., 0].max())],
            'outer': circle_boundary(np.asarray(shape.exterior.coords)[:-1]),
            'inner': circle_boundary(np.asarray(shape.interiors[0].coords)[:-1])})
    return rings


def _ring_dimensions(ring, outer_radius, inner_radius, center, tolerance):
    checks = {}
    for side, radius in [('outer', outer_radius), ('inner', inner_radius)]:
        circle = ring[side]
        checks[side+'_diameter'] = interval_check(2*circle['min_boundary_radius_m'],
            2*circle['max_boundary_radius_m'], 2*radius, tolerance)
        distance = float(np.linalg.norm(np.asarray(circle['center_plane_m'])-center))
        checks[side+'_center'] = interval_check(distance, distance, 0., tolerance)
    displacement = float(np.linalg.norm(np.asarray(ring['outer']['center_plane_m'])-ring['inner']['center_plane_m']))
    checks['concentric_boundaries'] = interval_check(displacement, displacement, 0., tolerance)
    low, high = ring['x_interval_m']
    checks['flat_plane'] = {'status': 'passed' if high-low <= 2*GUARD else 'not_measurable',
                            'passed': high-low <= 2*GUARD, 'x_interval_m': [low, high]}
    return verdict(**checks)


def measure_t_joint_socket(mesh, design, *, solid_validated, deadline=None, max_triangles=262144):
    validate_design(design)
    if (type(solid_validated) is not bool or type(max_triangles) is not int or max_triangles <= 0
            or deadline is not None and (type(deadline) not in (float, int) or not np.isfinite(deadline))):
        raise ValueError('Invalid trusted solid or socket measurement budget')
    report = {'protocol': 'l1-t-joint-socket-v1', 'design': copy.deepcopy(design),
              'full_task_verified': False, 'formal_score_eligible': False,
              'scope': 'Complete flat shoulder/end annuli, independent end X and relative recess depth; not full walls or preservation'}
    if not solid_validated:
        return {**report, **unavailable('Trusted closed oriented connected solid required')}
    if len(mesh.triangles) > max_triangles or deadline is not None and time.monotonic() >= deadline:
        return {**report, **unavailable('Socket measurement budget exhausted')}
    try:
        rings = _annuli(mesh, design, deadline)
    except (TimeoutError, ValueError) as error:
        return {**report, **unavailable(str(error))}
    if len(rings) != 2:
        return {**report, **unavailable('Exactly two complete flat socket/end annuli could not be identified'),
                'annular_groups': len(rings)}
    shoulder, end = sorted(rings, key=lambda r: sum(r['x_interval_m']))
    t, center = design['dimension_tolerance_m'], np.array([0., design['branch_z_m']])
    depth_low = end['x_interval_m'][0]-shoulder['x_interval_m'][1]
    depth_high = end['x_interval_m'][1]-shoulder['x_interval_m'][0]
    centers = [np.asarray(ring[side]['center_plane_m']) for ring in rings for side in ('outer', 'inner')]
    offset = max(float(np.linalg.norm(a-b)) for a in centers for b in centers)
    checks = {
        'end_dimensions': _ring_dimensions(end, design['branch_outer_radius_m'], design['socket_radius_m'], center, t),
        'shoulder_dimensions': _ring_dimensions(shoulder, design['socket_radius_m'], design['branch_inner_radius_m'], center, t),
        'branch_end_x': interval_check(*end['x_interval_m'], design['branch_end_x_m'], t),
        'socket_depth': interval_check(depth_low, depth_high, design['socket_depth_m'], t),
        'all_rings_coaxial': interval_check(offset, offset, 0., t),
    }
    if deadline is not None and time.monotonic() >= deadline:
        return {**report, **unavailable('Socket result missed measurement deadline')}
    return {**report, **verdict(**checks), 'shoulder': shoulder, 'end': end,
            'method': 'Union of all selected coplanar triangles with complete exterior/interior closed boundaries'}
