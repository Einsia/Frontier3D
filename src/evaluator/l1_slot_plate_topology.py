"""Complete Code014 wall connectivity and actual exterior port loops.

Four empty probe columns or a global Euler number cannot prove independent
passages. Here every non-exterior triangle belongs to an edge-connected wall
patch; ports and Euler topology are checked on each complete patch. Only an
observable planar exterior box (possibly with blind pockets) is supported.
"""
from __future__ import annotations

import time
from collections import defaultdict

import numpy as np
import shapely

from .l1_sleeve import boundary_cycles, boundary_edges, unavailable
from .l1_slot_plate_sections import profiles, validate_design


def _deadline(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError('Plate topology measurement deadline exhausted')


def _components(triangles, deadline):
    edges = defaultdict(list)
    parents = list(range(len(triangles)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for index, face in enumerate(triangles):
        if index % 256 == 0:
            _deadline(deadline)
        for i in range(3):
            edge = tuple(sorted((int(face[i]), int(face[(i+1) % 3]))))
            for other in edges[edge]:
                a, b = root(index), root(other)
                parents[max(a, b)] = min(a, b)
            edges[edge].append(index)
    if any(len(rows) > 2 for rows in edges.values()):
        raise ValueError('Nonmanifold actual wall edges')
    groups = defaultdict(list)
    for index in range(len(triangles)):
        groups[root(index)].append(index)
    return list(groups.values()), edges


def _exterior(mesh, bounds, guard, deadline):
    # The guard covers floating arithmetic only, never the 0.05 mm physical
    # preservation band. A buried cross-tunnel roof must not become exterior.
    distances = np.max(np.abs(mesh.xyz[None]-bounds[:, None, None, :]), axis=2)
    memberships = distances <= guard
    if np.any(memberships.sum(axis=(0, 2)) > 1):
        raise ValueError('Ambiguous exterior face at floating representation limit')
    exterior = memberships.any(axis=(0, 2))
    planes = []
    for side in (0, 1):
        for axis in range(3):
            _deadline(deadline)
            axes = [k for k in range(3) if k != axis]
            selected = memberships[side, :, axis]
            if not selected.any():
                raise ValueError('Actual exterior plane missing; nonplanar exterior needs another method')
            union = shapely.union_all(shapely.polygons(mesh.xyz[selected][:, :, axes]))
            if union.geom_type != 'Polygon' or not union.is_valid:
                raise ValueError('Exterior plane is not one valid connected face domain')
            rectangle = shapely.box(*bounds[0, axes], *bounds[1, axes]).boundary
            actual = shapely.LineString(union.exterior.coords)
            if (not actual.buffer(guard*4).covers(rectangle)
                    or not rectangle.buffer(guard*4).covers(actual)):
                raise ValueError('Exterior domain does not reach the actual box perimeter')
            planes.append({'axis': axis, 'side': side, 'position_m': float(bounds[side, axis]),
                'triangles': int(selected.sum()), 'boundary_holes': len(union.interiors)})
    return exterior, planes


def _port(mesh, loop, bounds, guard, design):
    xyz = mesh.vertices[loop]
    on_planes = [(axis, side) for axis in range(3) for side in (0, 1)
                 if np.max(np.abs(xyz[:, axis]-bounds[side, axis])) <= guard]
    if len(on_planes) != 1:
        raise ValueError('Patch boundary is not one unambiguous exterior port')
    axis, side = on_planes[0]
    axes = [k for k in range(3) if k != axis]
    polygon = shapely.Polygon(xyz[:, axes])
    if not polygon.is_valid or polygon.area <= 0:
        raise ValueError('Port loop is not a valid positive-area polygon')
    matches = []
    if axis == 2:
        datum = bounds[:, :2].mean(axis=0)
        for profile in profiles(design, bool(side), datum_xy=datum):
            point = shapely.Point(profile['center'])
            if polygon.boundary.distance(point) <= guard*4:
                raise ValueError('Required passage axis falls on a port boundary')
            if polygon.contains(point):
                matches.append(profile['id'])
    return {'axis': axis, 'side': side, 'matches': matches, 'vertices': len(loop),
            'area_m2': float(polygon.area), 'boundary_vertex_ids': [int(i) for i in loop]}


def measure_plate_topology(mesh, design, *, solid_validated, deadline, max_triangles=262144):
    validate_design(design)
    if (type(solid_validated) is not bool or type(deadline) not in (int, float) or not np.isfinite(deadline)
            or type(max_triangles) is not int or max_triangles <= 0):
        raise ValueError('Invalid plate topology validity/deadline/budget')
    report = {'protocol': 'l1-slot-plate-wall-topology-v1', 'full_task_verified': False,
        'scope': 'Complete actual wall components and exterior ports, not wall dimensions or material',
        'passages': {}, 'wall_components': []}
    if not solid_validated or len(mesh.triangles) > max_triangles:
        return {**report, **unavailable('Trusted solid or triangle budget unavailable')}
    try:
        _deadline(deadline)
        bounds = np.array([mesh.vertices.min(axis=0), mesh.vertices.max(axis=0)])
        guard = float(64*np.finfo(float).eps*max(.1, np.max(np.abs(bounds))))
        whole_groups, whole_edges = _components(mesh.triangles, deadline)
        if len(whole_groups) != 1 or any(len(rows) != 2 for rows in whole_edges.values()):
            raise ValueError('Source is not one closed edge-manifold surface')
        exterior, planes = _exterior(mesh, bounds, guard, deadline)
        wall_ids = np.flatnonzero(~exterior)
        if not len(wall_ids):
            return {**report, 'status': 'failed', 'passed': False, 'reason': 'No actual cavity walls'}
        groups, _ = _components(mesh.triangles[wall_ids], deadline)
        rows = []
        for index, group in enumerate(groups):
            _deadline(deadline)
            ids = wall_ids[group]
            faces = mesh.triangles[ids]
            loops = boundary_cycles(boundary_edges(faces))
            ports = [_port(mesh, loop, bounds, guard, design) for loop in loops]
            edges = {tuple(sorted((int(t[k]), int(t[(k+1) % 3])))) for t in faces for k in range(3)}
            rows.append({'component': index, 'source_triangle_ids': ids.tolist(), 'triangles': len(ids),
                'euler_characteristic': int(len(np.unique(faces))-len(edges)+len(faces)), 'ports': ports})
        actual_ports = defaultdict(int)
        for row in rows:
            for port in row['ports']:
                actual_ports[port['axis'], port['side']] += 1
        if any(actual_ports[p['axis'], p['side']] != p['boundary_holes'] for p in planes):
            raise ValueError('Complete wall boundaries do not match all exterior domain holes')
        report.update(wall_components=rows, exterior_planes=planes, numeric_plane_guard_m=guard,
            world_bounds_m=bounds.tolist(), source_surface_euler=int(len(np.unique(mesh.triangles))
                -len(whole_edges)+len(mesh.triangles)))
        conflicts = []
        for feature in ('slot_0', 'slot_1', 'hole_0', 'hole_1'):
            owners = [row for row in rows if any(feature in p['matches'] for p in row['ports'])]
            passed = (len(owners) == 1 and owners[0]['euler_characteristic'] == 0
                and len(owners[0]['ports']) == 2
                and sorted((p['axis'], p['side']) for p in owners[0]['ports']) == [(2, 0), (2, 1)]
                and all(p['matches'] == [feature] for p in owners[0]['ports']))
            report['passages'][feature] = {'passed': passed, 'status': 'passed' if passed else 'failed',
                'wall_components': [r['component'] for r in owners]}
        for row in rows:
            matches = {name for p in row['ports'] for name in p['matches']}
            if not matches and not (len(row['ports']) == 1 and row['euler_characteristic'] == 1):
                conflicts.append(row['component'])
            row['blind_external_pocket'] = not matches and len(row['ports']) == 1 and row['euler_characteristic'] == 1
        _deadline(deadline)
        passed = all(r['passed'] for r in report['passages'].values()) and not conflicts
        return {**report, 'status': 'passed' if passed else 'failed', 'passed': passed,
            'unexpected_nonblind_components': conflicts,
            'reason': 'Each requested passage needs its own annular wall and exactly one top/bottom port; blind pockets remain for geometry/preservation checks'}
    except (ValueError, TimeoutError) as error:
        return {**report, **unavailable(str(error))}
