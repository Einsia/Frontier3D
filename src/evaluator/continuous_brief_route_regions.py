"""Continuous bottleneck widths between fixed sets of actual surface points."""
import math
import numpy as np
from scipy.ndimage import binary_propagation, distance_transform_edt
from shapely.geometry import MultiPoint
from shapely.ops import unary_union

from .continuous_brief_planar_route import (
    planar_surface, blockers, polygons, edge_capsules, coordinates, PRECISION, ARC_SEGMENTS,
)
from .continuous_brief_heightfield_route import evidence_scene, array_sha
from .l2_brief_route import build_grid


def width_score(width, uncertainty, required):
    allowed, scale = .99*required, .01*required
    low, high = max(0., width-uncertainty), width+uncertainty
    errors = [max(allowed-value, 0.)/scale for value in (low, high)]
    return {'status': 'measured', 'normalized_errors': [errors[0]],
        'actual_bottleneck_width_m': width, 'width_interval_m': [low, high],
        'allowed_width_m': allowed, 'half_scale_m': scale,
        'continuous_score_interval': [2.**-e for e in errors]}


def absent(reason):
    return {'status': 'absent', 'reason': reason, 'continuous_score_interval': [0., 0.]}


def points(value):
    result = np.asarray(value, float).reshape(-1, 3)
    return result[np.isfinite(result).all(axis=1)]


def planar(road, obstacles, terminals, p):
    domain, ground = planar_surface(road)
    occupied, objects = blockers(obstacles, domain, ground+p['surface_epsilon'], ground+p['clearance_height'])
    span = math.hypot(domain.bounds[2]-domain.bounds[0], domain.bounds[3]-domain.bounds[1])
    inflation = 1/math.cos(math.pi/(4*ARC_SEGMENTS))
    quantities = []
    for terminal in terminals:
        selected = []
        for key in ('start_points', 'goal_points'):
            xyz = points(terminal[key])
            xyz = xyz[np.abs(xyz[:, 2]-ground) <= p['max_step']+p['surface_epsilon']]
            selected.append(MultiPoint(xyz[:, :2]))
        if any(v.is_empty for v in selected):
            quantities.append(absent('Actual endpoint set cannot reach this floor height')); continue
        def connected(radius):
            r = max(PRECISION, radius*inflation)
            free = domain.difference(unary_union(edge_capsules(domain, r)))
            if not occupied.is_empty:
                free = free.difference(unary_union([occupied, *edge_capsules(occupied, r)]))
            return any(all(part.distance(cloud) <= p['max_snap'] for cloud in selected) for part in polygons(free))
        if not connected(0.):
            quantities.append(absent('Actual endpoint sets are disconnected')); continue
        low, high = 0., span/2
        for _ in range(64):
            if high-low <= PRECISION/2: break
            middle = (low+high)/2
            if connected(middle): low = middle
            else: high = middle
        error = 2*(high-low)+2*low*(inflation-1)+2*PRECISION
        # Inflated polygonal capsules give a conservative lower width. The
        # arc and bisection uncertainty therefore extends upward from it.
        row = width_score(2*low+error/2, error/2, p['min_width'])
        if np.ptp(row['continuous_score_interval']) > .001:
            raise ValueError('Planar route width has unresolved numerical uncertainty')
        quantities.append(row)
    return {'method': 'complete_planar_geometry', 'quantities': quantities,
        'road_domain': coordinates(domain), 'ground_height_m': ground,
        'blockers': objects, 'blocker_domain': coordinates(occupied)}


def endpoint_mask(floor, free, xyz, origin, cell, p):
    result = np.zeros(free.shape, bool)
    for point in points(xyz):
        low = np.maximum(0, np.floor((point[:2]-p['max_snap']-origin)/cell).astype(int))
        high = np.minimum(np.array(free.shape[::-1])-1, np.ceil((point[:2]+p['max_snap']-origin)/cell).astype(int))
        if np.any(high < low): continue
        x, y = np.meshgrid(np.arange(low[0], high[0]+1), np.arange(low[1], high[1]+1))
        xy = np.stack((x, y), axis=-1)*cell+origin+cell/2
        sl = np.s_[low[1]:high[1]+1, low[0]:high[0]+1]
        result[sl] |= ((np.linalg.norm(xy-point[:2], axis=-1) <= p['max_snap'])
            & (np.abs(floor[sl]-point[2]) <= p['max_step']+p['surface_epsilon']) & free[sl])
    return result


def grid_radius(floor, free, distances, start, goal, cell, p):
    if not start.any() or not goal.any(): return None
    step = p['max_step']+p['max_slope']*cell
    heights = np.where(free, floor, 0.)
    horizontal = np.abs(np.diff(heights, axis=1)) <= step
    vertical = np.abs(np.diff(heights, axis=0)) <= step
    def connected(radius):
        mask = free & (distances >= radius)
        graph = np.zeros((2*mask.shape[0]-1, 2*mask.shape[1]-1), bool)
        graph[::2, ::2] = mask
        graph[::2, 1::2] = mask[:, :-1] & mask[:, 1:] & horizontal
        graph[1::2, ::2] = mask[:-1, :] & mask[1:, :] & vertical
        seeds = np.zeros_like(graph); seeds[::2, ::2] = start & mask
        reached = binary_propagation(seeds, mask=graph)[::2, ::2]
        return bool(np.any(reached & goal))
    if not connected(0.): return None
    low = 0.; high = min(float(distances[start].max()), float(distances[goal].max()))+PRECISION
    for _ in range(64):
        if high-low <= PRECISION/2: break
        middle = (low+high)/2
        if connected(middle): low = middle
        else: high = middle
    return low


def heightfield(road, obstacles, terminals, p):
    scene = evidence_scene(road, obstacles); cell = p['cell_size']; rounds = []
    for _ in range(12):
        floor, free, origin = build_grid(scene, {**p, 'road_role': 'road'}, cell)
        distances = distance_transform_edt(free)*cell; quantities = []
        for terminal in terminals:
            a, b = [endpoint_mask(floor, free, terminal[k], origin, cell, p)
                    for k in ('start_points', 'goal_points')]
            radius = grid_radius(floor, free, distances, a, b, cell, p)
            quantities.append(absent('No connection on the complete public surface grid') if radius is None
                else width_score(2*radius, 2*math.sqrt(2)*cell+PRECISION, p['min_width']))
        rounds.append({'cell_size_m': cell, 'shape': list(floor.shape), 'origin_world_xy_m': origin.tolist(),
            'floor_sha256': array_sha(floor), 'free_sha256': array_sha(free),
            'distance_sha256': array_sha(distances), 'quantities': quantities})
        if all(np.ptp(q['continuous_score_interval']) <= .001 for q in quantities): break
        cell /= 2
    else: raise ValueError('Route width score remains unresolved after twelve refinements')
    return {'method': 'complete_heightfield_grid', 'quantities': quantities, 'grid_rounds': rounds,
        'limitations': 'Public four-neighbor finite grid; step/slope limits and cylinder clearance; no stacked-floor motion.'}


def measure(road, obstacles, terminals, p, evidence):
    if not len(road[1]):
        result = {'method': 'absent_surface', 'quantities': [absent('Required floor surface absent') for _ in terminals]}
    else:
        try: planar_surface(road)
        except ValueError: result = heightfield(road, obstacles, terminals, p)
        else: result = planar(road, obstacles, terminals, p)
    return {'status': 'measured', **result, 'terminals': terminals, 'parameters': p,
            'evidence': evidence, 'registration': 'none', 'coordinate_space': 'world_metres',
            'endpoint_policy': 'Any actual nominated start point to any actual nominated goal point; geometry remains fixed'}
