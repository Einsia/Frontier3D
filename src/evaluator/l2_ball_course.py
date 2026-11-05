"""Per-lane static ball clearance and surface continuity on complete geometry.

The route uses a conservative vertical cylinder containing the published ball,
not a rolling-physics simulation. Finite raster and seam probe limits are public.
"""
import numpy as np
from scipy.ndimage import distance_transform_edt

from .l2_brief_relations import course_assignments, boundary
from .l2_brief_route import build_grid, reachable
from .l2_surface_relief import VerticalSurface
from .metrics import MissingEvidence, _register


PARAMETERS = ('lane_role ball_role cup_role obstacle_role contact_tolerance_m parallel_tolerance_degrees '
              'end_fraction obstacle_min_progress ball_diameter_m cell_size max_step max_slope surface_epsilon '
              'seam_directions seam_samples seam_max_jump_m')


def seam_check(lane, cup, p):
    origin, radial = boundary(cup, p['seam_directions'])
    fractions = np.linspace(.9, 1.15, p['seam_samples'])
    xy = origin + radial[:, None, :] * fractions[None, :, None]
    top = VerticalSurface(np.concatenate([lane, cup])).top(xy.reshape(-1, 2)).reshape(xy.shape[:2])
    finite = np.isfinite(top).all(axis=1)
    step = np.linalg.norm(np.diff(xy, axis=1), axis=2)
    connected = finite & (np.abs(np.diff(top, axis=1)) <= p['seam_max_jump_m'] + p['max_slope'] * step).all(axis=1)
    return bool(connected.all()), {'connected_directions': int(connected.sum()), 'directions': len(radial),
        'samples_per_direction': len(fractions), 'scope': 'Finite radial band across the convex footprint rim; no general shell/volume proof'}


@_register('l2_ball_course', PARAMETERS)
def ball_course(check, evidence, spec):
    p = check.params; assignments, errors = course_assignments(evidence, p)
    if errors:
        return 0., {'errors': errors, 'lanes': []}
    rows = []
    for row in assignments:
        lane, cup = row['surface'], row['cups'][0][1]
        seam, seam_details = seam_check(lane, cup, p)
        objects = {name: {**obj, 'role': None} for name, obj in evidence['scene']['objects'].items()}
        # Select one lane and its cup; another lane or the construction base
        # cannot provide an unrequested detour. The moving ball is not an obstacle.
        for name, _ in row['balls'][0][0]['members']:
            objects.pop(name)
        members = row['lane']['members'] + row['cups'][0][0]['members']
        for name, _ in members:
            objects[name]['role'] = '__measured_ball_course'
            objects[name]['entity'] = '__measured_ball_course'
        selected = {**evidence, 'scene': {**evidence['scene'], 'objects': objects}}
        parameters = {'road_role': '__measured_ball_course', 'clearance_height': p['ball_diameter_m'],
            'surface_epsilon': p['surface_epsilon'], 'max_step': p['max_step'], 'max_slope': p['max_slope'],
            'max_snap': p['cell_size'] * 2}
        floor, free, origin = build_grid(selected, parameters, p['cell_size'])
        distance = distance_transform_edt(free) * p['cell_size']; radius = p['ball_diameter_m'] / 2
        safe = free & (distance - p['cell_size'] * np.sqrt(2) >= radius * .99)
        optimistic = free & (distance + p['cell_size'] * np.sqrt(2) >= radius * .99)
        # Start at the actual ball's ground contact. Goal points are the real cup
        # rim itself, not an arbitrary endpoint beyond an obstacle.
        ball_xy = row['ball_point'][:2]
        ground = VerticalSurface(lane).top([ball_xy])[0]
        start_point = np.array([*ball_xy, ground]); start = [{'low': start_point, 'high': start_point}]
        cup_origin, radial = boundary(cup, p['seam_directions'])
        goal_xy = cup_origin + radial * .98
        z = VerticalSurface(np.concatenate([lane, cup])).top(goal_xy)
        goal = [{'low': np.array([*xy, height]), 'high': np.array([*xy, height])}
                for xy, height in zip(goal_xy, z) if np.isfinite(height)]
        passed = seam and reachable(safe, floor, start, goal, origin, p['cell_size'], parameters)
        uncertain = seam and not passed and reachable(optimistic, floor, start, goal, origin, p['cell_size'], parameters)
        rows.append({'lane': row['lane']['id'], 'passed': bool(passed), 'seam': seam_details,
            'ball': row['balls'][0][0]['id'], 'cup': row['cups'][0][0]['id'],
            'resolution_limited': bool(uncertain), 'road_cells': int(np.isfinite(floor).sum()),
            'free_cells': int(free.sum()), 'goal_rim_samples': len(goal)})
    if any(r['resolution_limited'] for r in rows):
        raise MissingEvidence('Ball-course clearance lies inside the published grid uncertainty')
    return float(all(r['passed'] for r in rows)), {'lanes': rows,
        'ball_diameter_m': p['ball_diameter_m'], 'cell_size_m': p['cell_size'],
        'width_uncertainty_m': 2 * np.sqrt(2) * p['cell_size'],
        'scope': 'Each actual ball to its own cup rim, using only its lane/cup and a conservative ball-containing cylinder; finite seam/raster checks, not rolling physics',
        'threshold_status': 'published_pilot_pending_calibration'}


def validate(check):
    from .l2_brief_relations import validate as validate_relations
    validate_relations(check)
    p = check.params
    for key in ('ball_diameter_m', 'cell_size', 'max_step', 'max_slope', 'surface_epsilon', 'seam_max_jump_m'):
        if type(p[key]) not in (int, float) or not np.isfinite(p[key]) or p[key] <= 0:
            raise ValueError('Positive finite course parameter required: ' + key)
    if p['cell_size'] > p['ball_diameter_m'] / 4:
        raise ValueError('Grid cannot resolve ball clearance')
    for key in ('seam_directions', 'seam_samples'):
        if type(p[key]) is not int or not 8 <= p[key] <= 128:
            raise ValueError('Bounded course seam resolution required')
