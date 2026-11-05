"""Continuous geometric waterline checks for Brief2Scene harbour scenes.

The check uses the evaluated hull, deck and water triangles in world metres.
It measures the local water surface by downward intersections at the hull
footprint centre.  The score records continuous violations for hull
submergence, hull emergence and deck clearance.  No buoyancy model or scene
registration is inferred.
"""

import math
import numpy as np

from .continuous_numeric import line_intersections
from .continuous_sceneedit_surface import join


def _surface_level(water, xy, ceiling):
    vertices, triangles = water
    hits = line_intersections(vertices, triangles, [float(xy[0]), float(xy[1]), float(ceiling)], [0., 0., -1.])
    if not len(hits):
        return None
    return float(ceiling - hits[0])


def _probe_xy(points, water):
    """Choose the centre of the hull/water footprint overlap."""
    water_points = water[0][water[1]].reshape(-1, 3)
    lower = np.maximum(points[:, :2].min(axis=0), water_points[:, :2].min(axis=0))
    upper = np.minimum(points[:, :2].max(axis=0), water_points[:, :2].max(axis=0))
    if np.any(upper <= lower):
        return None
    return (lower + upper) / 2.


def _scale(points):
    span = float(np.ptp(points[:, 2]))
    # The contract has no nominal hull height.  One percent of the observed
    # vertical span is the declared half-scale, with a one millimetre floor
    # for a nearly flat but nondegenerate hull.
    return max(0.01 * span, 1e-3), span


def _violation(value, lower=None, upper=None, half_scale=1.):
    error = max(0., (lower - value) if lower is not None else 0.,
                (value - upper) if upper is not None else 0.)
    return {
        'actual_m': float(value),
        'lower_m': None if lower is None else float(lower),
        'upper_m': None if upper is None else float(upper),
        'absolute_error_m': float(error),
        'half_scale_m': float(half_scale),
        'normalized_error': float(error / half_scale),
    }


def measure(check, roles, evidence):
    params = check['params']
    hulls = roles.get(params['hull_role'], [])
    decks = roles.get(params['deck_role'], [])
    waters = roles.get(params['water_role'], [])
    if not hulls or not decks or not waters:
        return {
            'status': 'measured', 'quantities': [{
                'status': 'absent',
                'reason': 'Required hull, deck or water surface is absent',
                'normalized_errors': [1e6],
            }],
            'evidence': evidence,
            'native_check': check,
            'registration': 'none',
        }
    water = join([item['mesh'] for item in waters])
    rows = []
    for role, entities in ((params['hull_role'], hulls), (params['deck_role'], decks)):
        for entity in entities:
            vertices, triangles = entity['mesh']
            if not len(triangles):
                rows.append({'status': 'absent', 'entity': entity['id'],
                             'reason': 'Required entity has no surface triangles',
                             'normalized_errors': [1e6]})
                continue
            points = vertices[triangles].reshape(-1, 3)
            centre = _probe_xy(points, water)
            if centre is None:
                rows.append({'status': 'absent', 'entity': entity['id'],
                             'reason': 'Entity has no footprint overlap with the evaluated water surface',
                             'normalized_errors': [1e6]})
                continue
            ceiling = max(float(points[:, 2].max()), float(water[0][water[1]][:, :, 2].max())) + 1.
            water_z = _surface_level(water, centre, ceiling)
            if water_z is None or not math.isfinite(water_z):
                rows.append({'status': 'absent', 'entity': entity['id'],
                             'reason': 'No local water surface intersection',
                             'normalized_errors': [1e6]})
                continue
            low = float(points[:, 2].min() - water_z)
            high = float(points[:, 2].max() - water_z)
            half_scale, vertical_span = _scale(points)
            if role == params['hull_role']:
                # The hull must cross the water plane: its bottom is below
                # water and its top is above water.
                observations = [
                    _violation(-low, lower=1e-6, half_scale=half_scale),
                    _violation(high, lower=1e-6, half_scale=half_scale),
                ]
                requirements = ['submerged_depth_m', 'emerged_height_m']
            else:
                observations = [_violation(low, lower=1e-6, half_scale=half_scale)]
                requirements = ['deck_clearance_m']
            rows.append({
                'status': 'measured', 'entity': entity['id'], 'role': role,
                'water_surface_z_m': float(water_z),
                'bottom_above_water_m': low,
                'top_above_water_m': high,
                'vertical_span_m': vertical_span,
                'half_scale_m': half_scale,
                'requirements': requirements,
                'observations': observations,
                'normalized_errors': [x['normalized_error'] for x in observations],
            })
    return {
        'status': 'measured',
        'quantities': rows,
        'evidence': evidence,
        'native_check': check,
        'coordinate_space': 'world_metres',
        'registration': 'none',
        'scope': 'Local water-plane crossing for hull and positive deck clearance from complete evaluated surfaces',
        'scale_policy': 'One percent of each observed entity vertical span, lower bounded by 0.001 m',
        'limitations': 'Geometric water-plane check only; no buoyancy, mass or physical-stability inference.',
    }
