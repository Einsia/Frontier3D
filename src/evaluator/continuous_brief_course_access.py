"""Continuous geometric ball and visitor access on the public mini-golf task."""
import math
import numpy as np
from shapely import get_coordinates
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .continuous_brief_course import assign, travel_frame, center
from .continuous_brief_relations import surface, fractional, geometric_score, quantity
from .continuous_brief_numeric import interval_error, missing
from .continuous_brief_route_regions import measure as route
from .continuous_sceneedit_surface import join
from .l2_brief_relations import boundary
from .l2_course_access import clip_surface, clip_polygon
from .l2_surface_relief import VerticalSurface


SUPPORTED = {'l2_ball_course', 'l2_course_visitor_route'}


def mesh(triangles):
    return triangles.reshape(-1, 3), np.arange(triangles.size//3).reshape(-1, 3)


def member_ids(entity):
    return {o['geometry']['path'] for o in entity.get('objects', [])} or {entity['id']}


def score(row):
    if row['status'] == 'absent': return 0.
    return math.fsum(2.**-e for e in row['normalized_errors'])/len(row['normalized_errors'])


def seam(lane, cup, p):
    origin, radial = boundary(cup, p['seam_directions'])
    fractions = np.linspace(.9, 1.15, p['seam_samples'])
    xy = origin+radial[:, None, :]*fractions[None, :, None]
    heights = VerticalSurface(np.concatenate([lane, cup])).top(xy.reshape(-1, 2)).reshape(xy.shape[:2])
    steps = np.linalg.norm(np.diff(xy, axis=1), axis=2); rows = []
    for coordinates, z, distances in zip(xy, heights, steps):
        observations = [interval_error(float(abs(b-a)), 0., float(p['seam_max_jump_m']+p['max_slope']*d),
            half_scale=p['seam_max_jump_m']) for a, b, d in zip(z[:-1], z[1:], distances)
            if np.isfinite(a) and np.isfinite(b)]
        q = geometric_score(observations) if len(observations) == len(z)-1 else 0.
        rows.append({'points_world_xy_m': coordinates.tolist(),
            'heights_m': [float(v) if np.isfinite(v) else None for v in z],
            'observations': observations, 'score': q})
    return math.fsum(r['score'] for r in rows)/len(rows), rows


def ball_routes(roles, scene_objects, p, evidence):
    lanes, _ = assign(roles, p); quantities = []
    for index in range(max(3, len(lanes))):
        if index >= len(lanes):
            quantities.append(missing('Required lane absent')); continue
        lane = lanes[index]; identity = lane['entity']['id']
        if 'ball' not in lane or 'cup' not in lane:
            quantities.append(missing('Actual ball or cup absent', lane=identity)); continue
        ball, cup = lane['ball']['entity'], lane['cup']['entity']
        floor = join([lane['entity']['mesh'], cup['mesh']])
        excluded = member_ids(lane['entity']) | member_ids(cup) | member_ids(ball)
        obstacles = [(name, item) for name, item in scene_objects if name not in excluded]
        start = center(surface(ball))[:2]; ground = lane['index'].top([start])[0]
        origin, radial = boundary(surface(cup), p['seam_directions']); goal_xy = origin+.98*radial
        top = VerticalSurface(floor[0][floor[1]]).top(goal_xy)
        goals = [[*xy, float(z)] for xy, z in zip(goal_xy, top) if np.isfinite(z)]
        terminals = [{'start_points': [[*start, float(ground)]] if np.isfinite(ground) else [], 'goal_points': goals}]
        parameters = {**p, 'min_width': p['ball_diameter_m'], 'clearance_height': p['ball_diameter_m'],
                      'max_snap': 2*p['cell_size']}
        measured = route(floor, obstacles, terminals, parameters, evidence)
        seam_value, probes = seam(lane['surface'], surface(cup), p)
        route_value = score(measured['quantities'][0])
        quantities.append(fractional(min(route_value, seam_value), lane=identity,
            route=measured, seam_directions=probes, route_score=route_value, seam_score=seam_value,
            combination='minimum_of_required_route_width_and_mean_directional_seam_continuity'))
    return quantities


def projection(triangles):
    return unary_union([Polygon(t[:, :2]) for t in triangles if Polygon(t[:, :2]).area > 1e-12])


def intrusion(path, lane, p):
    frame = travel_frame(lane)
    if frame is None: return missing('Actual start-to-cup direction absent')
    direction, start, _, _, _ = frame; limit = float(start@direction+p['seam_overlap_m'])
    pieces = []
    for triangle in path:
        clipped = clip_polygon(triangle[:, :2], -direction, -limit)
        if len(clipped) >= 3 and Polygon(clipped).area > 1e-12: pieces.append(Polygon(clipped))
    overlap = unary_union(pieces).intersection(projection(lane['surface']))
    penetration = 0.
    if overlap.area > 1e-12:
        penetration = max(0., float((get_coordinates(overlap)@direction).max()-limit))
    return quantity([interval_error(penetration, 0., 0., half_scale=max(p['seam_overlap_m'],p['surface_epsilon']))],
        lane=lane['entity']['id'], kind='visitor_path_intrusion_beyond_start_seam',
        actual_overlap_area_m2=float(overlap.area), actual_penetration_m=penetration,
        allowed_seam_overlap_m=p['seam_overlap_m'])


def visitor_routes(roles, scene_objects, p, evidence):
    lanes, _ = assign(roles, p); paths = roles.get(p['visitor_role'], [])
    if not paths: return [missing('Required visitor path absent')]
    path_mesh = join([e['mesh'] for e in paths]); floor_meshes = [path_mesh]
    excluded = set().union(*(member_ids(e) for e in paths))
    starts, outside = [], []
    for index in range(max(3, len(lanes))):
        if index >= len(lanes):
            starts.append([]); outside.append(missing('Required lane start absent')); continue
        lane = lanes[index]; frame = travel_frame(lane)
        if frame is None:
            starts.append([]); outside.append(missing('Required actual lane endpoints absent')); continue
        direction, start, length, ball, _ = frame
        padding = p['min_width']/2+2*math.sqrt(2)*p['cell_size']
        strip = clip_surface(lane['surface'], np.array([*direction, 0.]),
            float(start@direction+length*p['end_fraction']+padding))
        if len(strip): floor_meshes.append(mesh(strip))
        ground = lane['index'].top([ball[:2]])[0]
        starts.append([[*ball[:2], float(ground)]] if np.isfinite(ground) else [])
        excluded |= member_ids(lane['ball']['entity'])
        outside.append(intrusion(path_mesh[0][path_mesh[1]], lane, p))
    terminals = [{'start_points': starts[i], 'goal_points': starts[j], 'lane_indices': [i,j]}
                 for i in range(len(starts)) for j in range(i+1,len(starts))]
    parameters = {**p, 'max_snap': 2*p['cell_size']}
    measured = route(join(floor_meshes), [(name,item) for name,item in scene_objects if name not in excluded],
                     terminals, parameters, evidence)
    quantities = [fractional(score(value), kind='actual_start_pair_width',
        lane_indices=terminal['lane_indices'], route_quantity=value, route_parameters=parameters)
        for terminal,value in zip(terminals,measured['quantities'])]
    # Preserve the shared complete-floor replay evidence once rather than
    # duplicating its arrays for every start pair.
    quantities[0]['route_evidence'] = measured
    return quantities+outside


def measure(check, roles, minimum_entities, scene_objects, evidence):
    metric = check['metric']; p = check['params']
    if metric == 'l2_ball_course': rows = ball_routes(roles, scene_objects, p, evidence)
    elif metric == 'l2_course_visitor_route': rows = visitor_routes(roles, scene_objects, p, evidence)
    else: raise ValueError('Unsupported continuous course access: '+metric)
    return {'status': 'measured', 'quantities': rows, 'evidence': evidence, 'native_check': check,
        'registration': 'none', 'coordinate_space': 'world_metres',
        'scope': 'Fixed actual lane/ball/cup/path populations and complete scene triangles; geometric clearance and continuity'}
