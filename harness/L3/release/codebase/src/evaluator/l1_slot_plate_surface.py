"""Code014 constrained-parameter complete plate surface, not sparse sections.

Parameters are measured from the actual trusted mesh and individually checked
against public dimensions. A layered box/capsule/counterbore reference then
tests the whole remaining surface, with a circular chord approximation bound.
Protected-world surfaces and global passage independence remain separate.
"""
from __future__ import annotations

import copy
import time
from itertools import pairwise
from pathlib import Path

import numpy as np
import shapely

from .l1_capsule_corridor import GUARD
from .l1_polyhedral_bounds import compare_polyhedral
from .l1_sleeve import interval_check, unavailable, verdict
from .l1_slot_plate_sections import measure_layer, validate_design
from .l1_slot_plate_shoulders import measure_shoulders
from .l1_surface import SurfaceMesh, load_surface


def measure_parameters(mesh, design, *, solid_validated, deadline):
    validate_design(design)
    shoulders = measure_shoulders(mesh, design, solid_validated=solid_validated, deadline=deadline)
    bottom, h = float(mesh.vertices[:, 2].min()), float(mesh.vertices[:, 2].max())
    z = h-design['counterbore_depth_m']
    layers = {}
    for upper, height in ((False, (bottom+z)/2), (True, (z+h)/2)):
        key = 'upper' if upper else 'lower'
        if not solid_validated or time.monotonic() >= deadline:
            layers[key] = unavailable('Trusted solid or remaining section budget missing')
        else:
            layers[key] = measure_layer(mesh, design, height, upper)
    lower, upper = mesh.vertices.min(axis=0), mesh.vertices.max(axis=0)
    half = np.asarray(design['box_size_m'])/2
    bounds = {}
    expected = np.array([[-half[0], -half[1], 0.], [half[0], half[1], 2*half[2]]])
    for side, values in enumerate((lower, upper)):
        for axis in range(3):
            bounds[str(side)+'_'+str(axis)] = interval_check(float(values[axis]), float(values[axis]),
                float(expected[side, axis]), design['preservation_tolerance_m'])
    checks = verdict(shoulders=shoulders, sections=verdict(**layers), box_extrema=verdict(**bounds))
    checks['scope'] = 'Independent measured parameters and box extrema, not protected full surfaces'
    if not checks['passed'] or time.monotonic() >= deadline:
        return checks, None
    low, high = (layers[name]['measurements'] for name in ('lower', 'upper'))
    parameters = {'box_bounds_m': [lower.tolist(), upper.tolist()],
        'slots': [copy.deepcopy(low['slot_'+str(i)]['measured_profile']) for i in range(2)],
        'bores': [{'lower': copy.deepcopy(low['hole_'+str(i)]['measured_profile']),
                   'upper': copy.deepcopy(high['hole_'+str(i)]['measured_profile']),
                   'shoulder_z_m': shoulders['measurements'][str(i)]['z_m']} for i in range(2)]}
    return checks, parameters


def reference_surface(parameters, *, error_m):
    """Analytic layered shape approximated by complete polygonal face domains."""
    if type(error_m) not in (float, int) or not np.isfinite(error_m) or error_m <= 4*GUARD:
        raise ValueError('Invalid reference approximation precision')
    bounds = np.asarray(parameters['box_bounds_m'], dtype=float)
    if bounds.shape != (2, 3) or not np.isfinite(bounds).all() or np.any(bounds[1]-bounds[0] <= 4*GUARD):
        raise ValueError('Invalid reference box bounds')
    if len(parameters['slots']) != 2 or len(parameters['bores']) != 2:
        raise ValueError('Reference needs exactly two slots and two counterbores')
    definitions = parameters['slots']+[b[k] for b in parameters['bores'] for k in ('lower', 'upper')]
    max_radius = max(p['radius_m'] for p in definitions)
    quad_segments = 16
    while max_radius*(1-np.cos(np.pi/(4*quad_segments)))+GUARD >= error_m:
        quad_segments *= 2
        if quad_segments > 256:
            raise ValueError('Reference tessellation exceeds its bounded resource policy')
    approximation = max_radius*(1-np.cos(np.pi/(4*quad_segments)))+GUARD

    def footprint(profile):
        center = np.asarray(profile['center_xy_m'], dtype=float)
        radius = profile['radius_m']
        if center.shape != (2,) or not np.isfinite(center).all() or not np.isfinite(radius) or radius <= GUARD:
            raise ValueError('Invalid measured reference profile')
        if profile['kind'] == 'circle':
            axis = shapely.Point(center)
        elif profile['kind'] == 'slot' and np.isfinite(profile['half_length_m']) and profile['half_length_m'] > GUARD:
            a = profile['half_length_m']
            axis = shapely.LineString([center+[-a, 0.], center+[a, 0.]])
        else:
            raise ValueError('Unsupported measured reference profile')
        return shapely.orient_polygons(axis.buffer(radius, quad_segs=quad_segments))

    box = shapely.orient_polygons(shapely.box(bounds[0, 0], bounds[0, 1], bounds[1, 0], bounds[1, 1]))
    slots = [footprint(p) for p in parameters['slots']]
    bores = [(footprint(b['lower']), footprint(b['upper']), b['shoulder_z_m']) for b in parameters['bores']]
    all_holes = slots+[b[1] for b in bores]
    if (any(not box.contains(p) for p in all_holes)
            or any(all_holes[i].intersects(all_holes[j]) for i in range(4) for j in range(i))
            or any(not high.contains(low) or not bounds[0, 2] < z < bounds[1, 2] for low, high, z in bores)):
        raise ValueError('Measured reference has intersecting or invalid passage domains')
    vertices, triangles, lookup = [], [], {}

    def vertex(xy, z):
        xyz = tuple(np.round([*xy, z], 14))
        if xyz not in lookup:
            lookup[xyz] = len(vertices)
            vertices.append(xyz)
        return lookup[xyz]

    def wall(polygon, z0, z1, reverse):
        for a, b in pairwise(polygon.exterior.coords):
            al, bl, ah, bh = vertex(a, z0), vertex(b, z0), vertex(a, z1), vertex(b, z1)
            faces = [(al, bl, bh), (al, bh, ah)]
            triangles.extend(face[::-1] if reverse else face for face in faces)

    def horizontal(polygon, z, reverse):
        if polygon.geom_type != 'Polygon' or not polygon.is_valid:
            raise ValueError('Reference plane is not a single valid domain')
        faces = list(shapely.constrained_delaunay_triangles(polygon).geoms)
        if not faces or not shapely.union_all(faces).equals(polygon):
            raise ValueError('Reference triangles do not cover the complete face domain')
        for face in faces:
            xy = list(shapely.orient_polygons(face).exterior.coords)[:-1]
            if len(xy) != 3:
                raise ValueError('Unexpected reference triangulation')
            triangle = tuple(vertex(p, z) for p in xy)
            triangles.append(triangle[::-1] if reverse else triangle)

    bottom, top = bounds[:, 2]
    wall(box, bottom, top, False)
    for slot in slots:
        wall(slot, bottom, top, True)
    for low, high, z in bores:
        wall(low, bottom, z, True)
        wall(high, z, top, True)
        horizontal(high.difference(low), z, False)
    horizontal(box.difference(shapely.union_all(slots+[b[0] for b in bores])), bottom, True)
    horizontal(box.difference(shapely.union_all(slots+[b[1] for b in bores])), top, False)
    mesh = SurfaceMesh(vertices, np.asarray(triangles))
    signed = float(np.einsum('ij,ij->i', mesh.xyz[:, 0], np.cross(mesh.xyz[:, 1], mesh.xyz[:, 2])).sum()/6)
    if signed <= 0:
        raise ValueError('Nonpositive oriented reference volume')
    return mesh, {'method': 'Layered actual constrained profiles, circular chord bound and complete planar domains',
        'continuous_hausdorff_bound_m': float(approximation), 'quad_segments': quad_segments,
        'triangles': len(mesh.triangles), 'signed_volume_m3': signed, 'numeric_guard_m': GUARD,
        'scope': 'Both entire reference surface directions; not an exact CAD arithmetic certificate'}


def measure_slot_plate_surface(mesh, design, *, solid_validated, deadline, max_patches=262144):
    if type(deadline) not in (int, float) or not np.isfinite(deadline):
        raise ValueError('Finite measurement deadline required')
    checks, parameters = measure_parameters(mesh, design, solid_validated=solid_validated, deadline=deadline)
    if parameters is None:
        surface = unavailable('Independently valid parameters required before shape reference construction')
        approximation = None
    elif time.monotonic() >= deadline:
        surface, approximation = unavailable('No budget remaining for complete surface'), None
    else:
        try:
            reference, approximation = reference_surface(parameters, error_m=design['dimension_tolerance_m']/16)
        except ValueError as error:
            surface, approximation = unavailable(str(error)), None
        else:
            surface = compare_polyhedral(mesh, reference, tolerance_m=design['dimension_tolerance_m'],
                approximation_m=approximation['continuous_hausdorff_bound_m'], deadline=deadline, max_patches=max_patches)
    return {**verdict(parameters=checks, surface=surface), 'protocol': 'l1-slot-plate-surface-v1',
        'design': copy.deepcopy(design), 'measured_parameters': parameters, 'reference_approximation': approximation,
        'full_task_verified': False,
        'pending': ['0.05 mm complete protected-world surfaces and allowed difference mask',
                    'Global passage independence, effective material preservation and every-seed scoring integration']}


def inspect_slot_plate_surface(scene, design, *, trusted_root, deadline):
    """Trusted inspector data only; independent compute job, not score activation."""
    objects = scene.get('objects', {})
    meshes = [(name, row) for name, row in objects.items()
              if row.get('type') == 'MESH' and row.get('entity_scope') == 'delivery_geometry']
    if len(meshes) != 1 or any(r.get('entity_scope') == 'unsupported_delivery_geometry' for r in objects.values()):
        raise ValueError('Expected one editable plate mesh')
    name, row = meshes[0]
    valid = (row.get('valid_solid') is True and row.get('closed') is True
             and row.get('components') == 1 and row.get('editable') is True)
    mesh = load_surface(row['mesh_payload'], Path(trusted_root))
    result = measure_slot_plate_surface(mesh, design, solid_validated=valid, deadline=deadline)
    result['source'] = {'object': name, 'trusted_solid': valid, 'mesh_payload': copy.deepcopy(row['mesh_payload'])}
    return result
