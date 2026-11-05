"""Public geometric layout and per-course matching, without semantic labels as proof."""
import numpy as np
from scipy.spatial import ConvexHull

from .l2_reference_numeric import groups
from .l2_surface_relief import footprint, VerticalSurface
from .metrics import MissingEvidence, _register


def center(surface):
    return (surface.min((0, 1)) + surface.max((0, 1))) / 2


def long_axis(surface):
    mid, radii, axes = footprint(surface)
    index = int(np.argmax(radii))
    if radii[index] < 1.5 * radii[1 - index]:
        raise MissingEvidence('A dominant longitudinal geometry axis is required')
    return mid, radii[index], radii[1 - index], axes[:, index], axes[:, 1 - index]


def boundary(surface, count=32):
    """Radial intersections with the full horizontal convex footprint."""
    xy = np.unique(surface[:, :, :2].reshape(-1, 2), axis=0)
    hull = ConvexHull(xy); origin = xy[hull.vertices].mean(axis=0)
    angle = np.arange(count) * (2 * np.pi / count)
    directions = np.column_stack((np.cos(angle), np.sin(angle)))
    coefficients = hull.equations[:, :2]; offset = coefficients @ origin + hull.equations[:, 2]
    denominator = directions @ coefficients.T
    distance = np.divide(-offset[None, :], denominator, out=np.full_like(denominator, np.inf), where=denominator > 1e-12).min(axis=1)
    return origin, directions * distance[:, None]


@_register('l2_side_layout', 'role axis_role per_side rows_per_side row_tolerance_m')
def side_layout(check, evidence, spec):
    p = check.params; axis_surface = np.concatenate([s for _, s in groups(evidence, p['axis_role'])])
    origin, _, width, longitudinal, transverse = long_axis(axis_surface)
    sides = {-1: [], 1: []}; crossing = []
    for entity, surface in groups(evidence, p['role']):
        points = surface[:, :, :2].reshape(-1, 2) - origin
        side_positions = points @ transverse
        side = -1 if side_positions.max() <= -width + 1e-8 else 1 if side_positions.min() >= width - 1e-8 else 0
        if not side:
            crossing.append(entity['id']); continue
        extent = points @ longitudinal
        sides[side].append({'entity': entity['id'], 'along_axis_m': float((extent.min() + extent.max()) / 2)})
    result = []; passed = not crossing
    for side in (-1, 1):
        entities = sorted(sides[side], key=lambda r: r['along_axis_m']); rows = []
        for entity in entities:
            if not rows or entity['along_axis_m'] - rows[-1][0]['along_axis_m'] > p['row_tolerance_m']:
                rows.append([])
            rows[-1].append(entity)
        valid = len(entities) == p['per_side'] and (not p['rows_per_side'] or len(rows) == p['rows_per_side'])
        passed &= valid
        result.append({'side': side, 'entities': entities, 'row_count': len(rows),
                       'row_sizes': [len(r) for r in rows], 'passed': valid})
    return float(passed), {'sides': result, 'entities_crossing_axis_region': crossing,
        'scope': 'Complete geometric side intervals and bounded longitudinal row bands; no house/grave semantics or equal spacing requirement',
        'threshold_status': 'published_pilot_pending_calibration'}


def course_assignments(evidence, p):
    lanes = groups(evidence, p['lane_role']); rows = []; errors = []
    if len(lanes) != 3:
        return [], ['Exactly three geometric lanes required']
    indexes = [VerticalSurface(s) for _, s in lanes]
    frames = [long_axis(s) for _, s in lanes]
    for index, (entity, surface) in enumerate(lanes):
        rows.append({'lane': entity, 'surface': surface, 'frame': frames[index], 'index': indexes[index],
                     'balls': [], 'cups': [], 'obstacles': []})
    for role_key, target in [('ball_role', 'balls'), ('cup_role', 'cups'), ('obstacle_role', 'obstacles')]:
        for entity, surface in groups(evidence, p[role_key]):
            point = center(surface)
            if target == 'cups':
                origin, radial = boundary(surface)
                observations = origin + radial * 1.15
                matches = [i for i, index in enumerate(indexes) if np.isfinite(index.top(observations)).all()]
            else:
                heights = [float(index.top([point[:2]])[0]) for index in indexes]
                matches = [i for i, height in enumerate(heights) if np.isfinite(height)
                           and abs(float(surface[:, :, 2].min()) - height) <= p['contact_tolerance_m']]
            if len(matches) != 1:
                errors.append(p[role_key] + ':' + entity['id'] + ' has no unique geometric lane')
            else:
                rows[matches[0]][target].append((entity, surface))
    for row in rows:
        for key in ('balls', 'cups', 'obstacles'):
            if len(row[key]) != 1:
                errors.append(row['lane']['id'] + ' requires exactly one ' + key)
    axes = [frame[3] for frame in frames]
    for other in axes[1:]:
        if abs(float(axes[0] @ other)) < np.cos(np.radians(p['parallel_tolerance_degrees'])):
            errors.append('Lane longitudinal directions are not parallel')
    if errors:
        return rows, errors
    for row in rows:
        origin, length, _, axis, _ = row['frame']
        ball = center(row['balls'][0][1]); cup = center(row['cups'][0][1]); obstacle = center(row['obstacles'][0][1])
        b, c = float((ball[:2] - origin) @ axis), float((cup[:2] - origin) @ axis)
        if b * c >= 0 or min(abs(b), abs(c)) < length * (1 - 2 * p['end_fraction']):
            errors.append(row['lane']['id'] + ' ball and cup must occupy opposite end regions')
        travel = c - b
        progress = float(((obstacle[:2] - origin) @ axis - b) / travel) if abs(travel) > 1e-8 else -1
        if not p['obstacle_min_progress'] <= progress <= 1:
            errors.append(row['lane']['id'] + ' obstacle is not near the cup end')
        row['ball_point'] = ball; row['cup_point'] = cup; row['obstacle_progress'] = progress
    return rows, errors


@_register('l2_course_correspondence', 'lane_role ball_role cup_role obstacle_role contact_tolerance_m parallel_tolerance_degrees end_fraction obstacle_min_progress')
def correspondence(check, evidence, spec):
    rows, errors = course_assignments(evidence, check.params)
    details = [{'lane': r['lane']['id'], **{key: [g['id'] for g, _ in r[key]] for key in ('balls', 'cups', 'obstacles')},
                'obstacle_progress': r.get('obstacle_progress')} for r in rows]
    return float(not errors), {'lanes': details, 'errors': errors,
        'scope': 'Geometric one-to-one lane assignment, parallel directions, end regions and obstacle position; no object-name matching or text semantics',
        'threshold_status': 'published_pilot_pending_calibration'}


def validate(check):
    p = check.params
    for key, value in p.items():
        if key.endswith('_role') or key == 'role':
            if not isinstance(value, str) or not value:
                raise ValueError('Nonempty relation role required')
    if check.metric == 'l2_side_layout':
        if type(p['per_side']) is not int or p['per_side'] < 1 or type(p['rows_per_side']) is not int or p['rows_per_side'] < 0:
            raise ValueError('Integer side and row counts required')
        if p['rows_per_side'] > p['per_side']:
            raise ValueError('Cannot have more nonempty rows than entities')
        limits = {'row_tolerance_m': (1e-5, 5)}
    else:
        limits = {'contact_tolerance_m': (1e-5, .1), 'parallel_tolerance_degrees': (.01, 10),
                  'end_fraction': (.01, .3), 'obstacle_min_progress': (.5, .95)}
    for key, (low, high) in limits.items():
        if type(p[key]) not in (int, float) or not np.isfinite(p[key]) or not low <= p[key] <= high:
            raise ValueError('Invalid relation parameter: ' + key)
