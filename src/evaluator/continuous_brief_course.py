"""Continuous mini-golf correspondence and obstacle placement in world metres."""
import math
import numpy as np
from scipy.optimize import linear_sum_assignment
from shapely.geometry import MultiPoint, Point

from .continuous_brief_numeric import actual_entities, interval_error, missing
from .continuous_brief_relations import surface, fractional, quantity
from .l2_brief_relations import long_axis, boundary
from .l2_surface_relief import VerticalSurface


SUPPORTED = {'l2_course_correspondence', 'l2_course_obstacle_placement'}


def center(triangles):
    return (triangles.min((0, 1))+triangles.max((0, 1)))/2


def support_points(part, lane, tolerance, cup=False):
    """Measure assigned contact on actual complete lane triangles."""
    if cup:
        origin, radial = boundary(surface(part))
        points = origin+1.15*radial
        # Cups may be subtracted into the lane. Their relation is measured at
        # the surrounding lane rim; cup depth is an independent public item.
        top = lane['index'].top(points)
        probes = [{'xy_m': xy.tolist(), 'height_m': float(z) if np.isfinite(z) else None,
                   'score': float(np.isfinite(z))} for xy, z in zip(points, top)]
    else:
        triangles = surface(part); low = float(triangles[:, :, 2].min())
        points = np.unique(triangles.reshape(-1, 3), axis=0)
        points = points[points[:, 2] <= low+1e-7]
        top = lane['index'].top(points[:, :2]); probes = []
        for point, height in zip(points, top):
            if not np.isfinite(height):
                probes.append({'point_world_m': point.tolist(), 'height_m': None, 'score': 0.})
            else:
                observation = interval_error(float(point[2]-height), -tolerance, tolerance, half_scale=tolerance)
                probes.append({'point_world_m': point.tolist(), 'height_m': float(height),
                    'observations': [observation], 'score': 2.**-observation['normalized_error']})
    return math.fsum(p['score'] for p in probes)/len(probes), probes


def assign(roles, p):
    """One-to-one correspondence by measured geometry, retaining failed matches.

    Assignment nominates which pair to measure. It never turns a spatially
    incorrect or distant match into compliance and never moves any geometry.
    """
    selected, _ = actual_entities(roles.get(p['lane_role'], []), volumetric=False)
    rows = []
    for entity in selected:
        triangles = surface(entity)
        rows.append({'entity': entity, 'surface': triangles, 'frame': long_axis(triangles),
                     'index': VerticalSurface(triangles),
                     'footprint': MultiPoint(triangles[:, :, :2].reshape(-1, 2)).convex_hull})
    selections = {}
    for key, slot in [('ball_role', 'ball'), ('cup_role', 'cup'), ('obstacle_role', 'obstacle')]:
        entities, _ = actual_entities(roles.get(p[key], []), volumetric=False)
        selections[slot] = len(entities)
        if not entities or not rows:
            continue
        costs = np.zeros((len(entities), len(rows))); probes = {}
        for i, entity in enumerate(entities):
            xy = center(surface(entity))[:2]
            for j, row in enumerate(rows):
                q, observed = support_points(entity, row, p['contact_tolerance_m'], cup=slot == 'cup')
                distance = float(row['footprint'].distance(Point(xy)))
                # The distance term separates geometrically disjoint lanes
                # even when neither lane provides the required contact.
                costs[i, j] = distance/p['contact_tolerance_m']+(1-q)
                probes[i, j] = q, observed, distance
        left, right = linear_sum_assignment(costs)
        for i, j in zip(left, right):
            q, observed, distance = probes[i, j]
            rows[j][slot] = {'entity': entities[i], 'contact_score': q, 'probes': observed,
                             'footprint_distance_m': distance}
    return rows, selections


def travel_frame(row):
    if 'ball' not in row or 'cup' not in row:
        return None
    origin, half_length, _, axis, _ = row['frame']
    ball = center(surface(row['ball']['entity']))
    cup = center(surface(row['cup']['entity']))
    travel = float((cup[:2]-ball[:2])@axis)
    if abs(travel) <= 1e-7:
        return None
    direction = axis*(1 if travel > 0 else -1)
    start = origin-direction*half_length
    return direction, start, 2*half_length, ball, cup


def correspondence(roles, p):
    rows, selections = assign(roles, p); quantities = []
    for slot, count in [('lane',len(rows)), *selections.items()]:
        quantities.append(quantity([interval_error(count,3,3,half_scale=1.)], kind='one_per_lane_count', role=slot))
    if not rows:
        return [missing('Required course lanes absent')]
    for index in range(max(3, len(rows))):
        if index >= len(rows):
            quantities.extend([missing('Required lane contact absent') for _ in range(3)])
            quantities.append(missing('Required lane positions absent')); continue
        row = rows[index]; identity = row['entity']['id']
        for slot in ('ball', 'cup', 'obstacle'):
            if slot not in row:
                quantities.append(missing('Required '+slot+' absent on this lane', lane=identity)); continue
            match = row[slot]
            quantities.append(fractional(match['contact_score'], lane=identity, role=slot,
                entity=match['entity']['id'], probes=match['probes'],
                footprint_distance_m=match['footprint_distance_m']))
        frame = travel_frame(row)
        if frame is None:
            quantities.append(missing('Distinct ball and cup endpoints absent', lane=identity)); continue
        direction, start, length, ball, cup = frame
        b = float((ball[:2]-start)@direction/length); c = float((cup[:2]-start)@direction/length)
        observations = [interval_error(b, 0., p['end_fraction'], half_scale=p['end_fraction']),
                        interval_error(c, 1-p['end_fraction'], 1., half_scale=p['end_fraction'])]
        if 'obstacle' in row:
            position = center(surface(row['obstacle']['entity']))
            progress = float((position[:2]-ball[:2])@direction/((cup[:2]-ball[:2])@direction))
            observations.append(interval_error(progress,p['obstacle_min_progress'],1.,
                half_scale=1-p['obstacle_min_progress']))
        quantities.append(quantity(observations, lane=identity, kind='opposite_ends_and_obstacle_progress'))
    # Every actual pair is included; missing lanes are already fixed-population
    # zeros above. Directional sign is irrelevant to geometric parallelism.
    for i, first in enumerate(rows):
        for second in rows[i+1:]:
            cosine = min(1.,abs(float(first['frame'][3]@second['frame'][3])))
            degrees = math.degrees(math.acos(cosine))
            quantities.append(quantity([interval_error(degrees,0.,p['parallel_tolerance_degrees'],
                half_scale=p['parallel_tolerance_degrees'])], kind='lane_parallelism',
                lanes=[first['entity']['id'],second['entity']['id']]))
    return quantities


def placement(roles, p):
    rows, _ = assign(roles,p)
    frames = [(row,travel_frame(row)) for row in rows]
    frames = [(row,frame) for row,frame in frames if frame is not None]
    if len(frames) != 3:
        return [missing('Three lanes with distinct observed start and cup endpoints required')]
    # Choose the first geometric travel axis only as an orientation convention.
    # Orientation disagreement is separately measured in correspondence.
    direction = frames[0][1][0]; left = np.array([-direction[1],direction[0]])
    ordered = sorted(frames,key=lambda item:float(item[0]['frame'][0]@left),reverse=True)
    quantities = []
    for role, target in [(p['windmill_role'],ordered[0][0]),(p['castle_role'],ordered[1][0])]:
        entities, _ = actual_entities(roles.get(role,[]),volumetric=False)
        quantities.append(quantity([interval_error(len(entities),1,1,half_scale=1.)],role=role,kind='obstacle_count'))
        if not entities:
            quantities.append(missing('Specified obstacle absent',role=role)); continue
        for entity in entities:
            q, probes = support_points(entity,target,p['contact_tolerance_m'])
            quantities.append(fractional(q,role=role,entity=entity['id'],
                required_lane=target['entity']['id'],probes=probes,
                lane_order_left_to_right=[r['entity']['id'] for r,_ in ordered]))
    return quantities


def measure(check, roles, minimum_entities, evidence):
    p=check['params'];metric=check['metric']
    if metric=='l2_course_correspondence': rows=correspondence(roles,p)
    elif metric=='l2_course_obstacle_placement': rows=placement(roles,p)
    else: raise ValueError('Unsupported continuous course measurement: '+metric)
    return {'status':'measured','quantities':rows,'evidence':evidence,'native_check':check,
        'coordinate_space':'world_metres','registration':'none',
        'scope':'Complete lane and role geometry; fixed one-to-one entity matching and continuous public position/contact errors'}
