"""Continuous terrain, depression, diameter and camera measurements.

All intersections use complete world-space triangles. Public finite sampling
grids/rings and visibility tolerances are retained; no geometry is registered.
"""
import math
import numpy as np
from scipy.spatial import ConvexHull, QhullError
from scipy.spatial.distance import cdist
from .continuous_brief_numeric import actual_entities, interval_error, missing, population
from .continuous_sceneedit_surface import join
from .l2_surface_relief import VerticalSurface, footprint, plane


def triangles(mesh):
    v, f = mesh
    return np.asarray(v, float)[f]


def vertical(mesh):
    surface = triangles(mesh)
    if not len(surface): return None
    a, b = surface[:, 1]-surface[:, 0], surface[:, 2]-surface[:, 0]
    if not np.any(np.abs(a[:, 0]*b[:, 1]-a[:, 1]*b[:, 0]) > 1e-14): return None
    return VerticalSurface(surface)


def tops(index, xy, ceiling=None):
    return np.full(len(xy), np.nan) if index is None else index.top(xy, ceiling)


def values(array):
    return [float(x) if np.isfinite(x) else None for x in np.asarray(array).ravel()]


def quantity(observations, **fields):
    return {'status': 'measured', 'observations': observations,
            'normalized_errors': [max(o['normalized_error'] for o in observations)], **fields}


def diameter(mesh):
    points = np.unique(triangles(mesh).reshape(-1, 3), axis=0)
    if not len(points): return None
    try: hull = points[ConvexHull(points).vertices]
    except QhullError: hull = points
    if len(hull) > 20_000: raise ValueError('Exact diameter exceeds 20,000 hull-point capacity')
    best = (-1., None)
    for start in range(0, len(hull), 256):
        distances = cdist(hull[start:start+256], hull)
        a, b = np.unravel_index(np.argmax(distances), distances.shape)
        if distances[a, b] > best[0]: best = float(distances[a, b]), [hull[start+a].tolist(), hull[b].tolist()]
    return {'diameter_m': best[0], 'witness_world_m': best[1], 'surface_vertices': len(points), 'hull_vertices': len(hull)}


def diameter_range(selected, p):
    rows = [{'entity': e['id'], **diameter(e['mesh'])} for e in selected]
    if not rows: return [missing('Required rock population absent')]
    observed = [interval_error(r['diameter_m'], p['lower'], p['upper'], p['relative_tolerance']) for r in rows]
    result = [{'status': 'measured', 'observations': observed, 'entities': rows,
               'normalized_errors': [o['normalized_error'] for o in observed], 'quantity': 'diameters_in_range'}]
    if p['require_endpoints']:
        ds = [r['diameter_m'] for r in rows]
        for label, actual, target in [('smallest', min(ds), p['lower']), ('largest', max(ds), p['upper'])]:
            result.append(quantity([interval_error(actual, target, target, p['relative_tolerance'])], quantity=label))
    return result


def depression(entity, support, visible, p):
    if entity is None: return missing('Required reviewed crater absent')
    own = vertical(entity['mesh'])
    if support is None or own is None: return missing('Actual crater floor or surrounding ground absent', entity=entity['id'])
    center, radii, rotation = footprint(triangles(entity['mesh']))
    angles = np.arange(p['directions'])*(2*np.pi/p['directions'])
    directions = np.column_stack((np.cos(angles), np.sin(angles)))
    square = directions/np.max(np.abs(directions), axis=1)[:, None]
    outer = center+(square*radii*p['outside_fraction'])@rotation.T
    outer_z = tops(support, outer)
    record = {'entity': entity['id'], 'outer_xy_m': outer.tolist(), 'outer_z_m': values(outer_z),
              'footprint_center_m': center.tolist(), 'footprint_radii_m': radii.tolist(),
              'footprint_basis': rotation.tolist()}
    if not np.isfinite(outer_z).all():
        return missing('Actual support ring has uncovered probes', **record)
    ground, residual = plane(outer, outer_z)
    inside = center+(directions*radii*p['inner_fraction'])@rotation.T
    inner = tops(own, inside); global_z = tops(visible, inside)
    rim_xy = np.concatenate([center+(directions*radii*f)@rotation.T for f in p['rim_fractions']])
    rim_z = tops(own, rim_xy).reshape(len(p['rim_fractions']), -1)
    rim_ground = ground(rim_xy).reshape(rim_z.shape)
    rim = np.where(np.isfinite(rim_z), rim_z-rim_ground, -np.inf).max(axis=0)
    depth = ground(inside)-inner; below_rim = depth+rim
    exposed = np.isfinite(inner)&np.isfinite(global_z)&(np.abs(inner-global_z) <= p['occlusion_tolerance_m'])
    rows = []; errors = []
    for i in range(p['directions']):
        row = {'direction': i, 'inner_xy_m': inside[i].tolist(), 'own_z_m': values(inner[i:i+1])[0],
               'scene_z_m': values(global_z[i:i+1])[0], 'exposed': bool(exposed[i])}
        if (exposed[i] and np.isfinite(rim[i]) and np.isfinite(depth[i])
                and np.isfinite(below_rim[i])):
            relief_half_scale = max(1e-3, 0.01*max(float(p['min_depth_m']), 1e-3))
            observations = [interval_error(float(x), lo, None, half_scale=relief_half_scale) for x, lo in
                [(depth[i], p['min_depth_m']), (below_rim[i], p['min_depth_m']), (rim[i], p['min_rim_height_m'])]]
            error = max(o['normalized_error'] for o in observations)
            row.update(observations=observations, normalized_error=error); errors.append(error)
        else: row.update(absent_reason='Exposed inner floor or actual rim is absent', normalized_error=None)
        rows.append(row)
    required = math.ceil(p['required_fraction']*p['directions'])
    record.update(directions=rows, required_directions=required, available_directions=len(errors),
        rim_xy_m=rim_xy.tolist(), rim_z_m=values(rim_z), local_ground_inner_m=ground(inside).tolist(),
        local_ground_rim_m=values(rim_ground), surrounding_plane_residual_m=values(residual),
        aggregation='Required-fraction order statistic of worst depth/rim error per exposed direction')
    if len(errors) < required: return missing('Too few exposed floor/rim directions for the public fraction', **record)
    return {'status': 'measured', 'normalized_errors': [sorted(errors)[required-1]], **record}


def terrain(mesh, visible, p):
    own = vertical(mesh)
    if own is None: return missing('Exposed terrain surface absent')
    center, radii, rotation = footprint(triangles(mesh))
    axis = (np.arange(p['grid_size'])+.5)/p['grid_size']*2-1
    x, y = np.meshgrid(axis, axis); local = np.column_stack((x.ravel(), y.ravel()))
    xy = center+(local*radii)@rotation.T
    z, global_z = tops(own, xy), tops(visible, xy)
    finite = np.isfinite(z)&np.isfinite(global_z)&(np.abs(z-global_z) <= 1e-5)
    record = {'grid_size': p['grid_size'], 'xy_world_m': xy.tolist(), 'terrain_z_m': values(z),
              'scene_z_m': values(global_z), 'exposed': finite.tolist(), 'coverage': float(finite.mean()),
              'occlusion_tolerance_m': 1e-5}
    if finite.sum() < 3: return missing('Fewer than three exposed terrain samples', **record)
    _, residual = plane(xy[finite], z[finite]); rms = float(np.sqrt(np.mean(residual**2)))
    quadrants = []
    for sx, sy in ((-1,-1), (-1,1), (1,-1), (1,1)):
        mask = (local[finite, 0]*sx > 0)&(local[finite, 1]*sy > 0)
        if mask.sum() < 3: value = 0.
        else:
            _, local_residual = plane(xy[finite][mask], z[finite][mask])
            value = float(np.sqrt(np.mean(local_residual**2)))
        quadrants.append(value)
    required_rms = sorted(quadrants, reverse=True)[p['required_quadrants']-1]
    observations = [interval_error(value, minimum, None) for value, minimum in
        [(record['coverage'], p['min_coverage']), (rms, p['min_rms_m']), (required_rms, p['min_quadrant_rms_m'])]]
    return quantity(observations, **record, plane_removed_rms_m=rms, quadrant_plane_removed_rms_m=quadrants,
                    required_quadrants=p['required_quadrants'], aggregation='Worst required coverage/global/local relief error')


def measure(check, roles, minimum_entities, scene_mesh, camera_location, evidence):
    p = check['params']; metric = check['metric']; selection = []
    if 'role' in p:
        selected, selection = actual_entities(roles.get(p['role'], []), volumetric=metric == 'l2_brief_diameter_range')
    if metric == 'l2_brief_diameter_range': quantities = diameter_range(selected, p)
    elif metric == 'l2_brief_camera_ground':
        support = vertical(join([e['mesh'] for e in roles.get(p['support_role'], [])]))
        if camera_location is None: quantities = [missing('Required saved render camera absent')]
        else:
            location = np.asarray(camera_location, float)
            ground = tops(support, location[None, :2], location[2]+1e-6)[0]
            if not np.isfinite(ground): quantities = [missing('Actual ground beneath the camera absent', camera_world_m=location.tolist())]
            else: quantities = [quantity([interval_error(float(location[2]-ground), p['lower'], p['upper'], p['relative_tolerance'])],
                                          camera_world_m=location.tolist(), ground_height_m=float(ground))]
    elif metric == 'l2_surface_depression':
        support = vertical(join([e['mesh'] for e in roles.get(p['support_role'], [])])); visible = vertical(scene_mesh)
        quantities = [depression(e, support, visible, p) for e in population(selected, minimum_entities[p['role']])]
    elif metric == 'l2_terrain_relief':
        quantities = [terrain(join([e['mesh'] for e in selected]), vertical(scene_mesh), p)]
    else: raise ValueError('Unimplemented continuous relief quantity: '+metric)
    return {'status': 'measured', 'quantities': quantities, 'evidence': evidence, 'native_check': check,
        'entity_selection': selection, 'coordinate_space': 'world_metres', 'registration': 'none',
        'scope': 'Complete surface intersections at public probes, exact diameters and saved camera coordinates',
        'limitations': 'Finite rings/grid do not certify unobserved terrain; local planes remove terrain tilt only.'}
