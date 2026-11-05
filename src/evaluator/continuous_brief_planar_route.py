"""Continuous clearance of a complete route over a verified planar road surface.

This specializes the public 2.5D route query to its constant-height case. All
triangles, thin walls, closed-solid interiors and endpoint snapping are retained.
Nonplanar road envelopes require a separate height-field adapter.
"""
import json
import math
import numpy as np
from shapely.geometry import Polygon, MultiPoint, Point, LineString, mapping
from shapely.ops import unary_union
from shapely import make_valid
from .continuous_surface import triangle_areas, topology_defects
from .l2_cylindrical_components import section_segments, closed_loops

PRECISION = 1e-6
ARC_SEGMENTS = 128


def coordinates(shape):
    return json.loads(json.dumps(mapping(shape)))


def polygons(shape):
    if shape.geom_type == 'Polygon': return [shape]
    return [p for g in getattr(shape, 'geoms', []) for p in polygons(g)]


def planar_surface(mesh, precision=PRECISION):
    v, f = mesh; triangle_areas(v, f)
    if not len(f): raise ValueError('A nonempty road surface is required')
    xyz = v[f]; height = float(xyz[:, :, 2].max())
    top = xyz[np.max(np.abs(xyz[:, :, 2]-height), axis=1) <= precision]
    domain = unary_union([Polygon(t[:, :2]) for t in top if Polygon(t[:, :2]).area > precision**2]).normalize()
    projected = unary_union([Polygon(t[:, :2]) for t in xyz if Polygon(t[:, :2]).area > precision**2]).normalize()
    if domain.is_empty or projected.difference(domain.buffer(precision)).area > precision**2:
        raise ValueError('Road upper envelope is not one horizontal surface; height-field measurement required')
    return domain, height


def clip_height(points, height, keep_above):
    output = []; direction = 1 if keep_above else -1
    if not len(points): return np.empty((0, 3))
    for a, b in zip(points, np.roll(points, -1, axis=0)):
        da, db = direction*(a[2]-height), direction*(b[2]-height)
        if da >= 0: output.append(a)
        if (da < 0) != (db < 0): output.append(a+da/(da-db)*(b-a))
    return np.asarray(output).reshape(-1, 3)


def section_region(surface, height, precision):
    segments, _ = section_segments(surface, np.array([0., 0., 1.]), height, precision)
    loops = []
    for loop in closed_loops(segments[:, :, :2], precision):
        poly = Polygon(loop)
        loops.extend(polygons(poly if poly.is_valid else make_valid(poly)))
    loops.sort(key=lambda p: -p.area); region = Polygon()
    for i, poly in enumerate(loops):
        depth = sum(previous.covers(poly) for previous in loops[:i])
        region = region.difference(poly) if depth % 2 else region.union(poly)
    return region


def blockers(meshes, domain, low, high, precision=PRECISION):
    shapes = []; observations = []
    domain_bounds = domain.bounds
    for identity, mesh in meshes:
        v, f = mesh; triangle_areas(v, f)
        if not len(f): continue
        surface = v[f]; minimum = surface.min(axis=(0, 1)); maximum = surface.max(axis=(0, 1))
        if (maximum[2] <= low or minimum[2] >= high or maximum[0] < domain_bounds[0]
                or minimum[0] > domain_bounds[2] or maximum[1] < domain_bounds[1] or minimum[1] > domain_bounds[3]): continue
        pieces = []
        for triangle in surface[(surface[:, :, 2].max(axis=1) > low) & (surface[:, :, 2].min(axis=1) < high)]:
            clipped = clip_height(clip_height(triangle, low, True), high, False)
            if len(clipped) >= 2:
                # Convex hull of a clipped triangle is its exact XY projection;
                # vertical/thin faces intentionally remain blocking linework.
                shape = MultiPoint(clipped[:, :2]).convex_hull
                if not shape.is_empty: pieces.append(shape)
        topology = topology_defects(v, f, weld_m=precision)
        closed = topology['boundary_edges'] == 0 and topology['nonmanifold_edges'] == 0
        section_height = (max(low, float(minimum[2]))+min(high, float(maximum[2])))/2
        if closed:
            # A solid containing the entire height band has no cap in the
            # clipped surface. One interior section fills that occupied volume;
            # projected boundary surfaces cover all changes with height.
            pieces.append(section_region(surface, section_height, precision))
        occupied = unary_union(pieces).normalize()
        if occupied.is_empty: continue
        shapes.append(occupied)
        observations.append({'object': identity, 'closed_solid': closed, 'section_height_m': section_height if closed else None,
            'triangles': len(f), 'geometry': coordinates(occupied), 'boundary_edges': topology['boundary_edges'],
            'nonmanifold_edges': topology['nonmanifold_edges']})
    return unary_union(shapes).normalize(), observations


def endpoint(entity):
    v, f = entity['mesh']; triangle_areas(v, f)
    if not len(f): return None
    points = v[f].reshape(-1, 3)
    return (points.min(axis=0)+points.max(axis=0))/2


def edge_capsules(shape, radius):
    """Expand individual segments to avoid GEOS's narrow-hole collapse heuristic."""
    if shape.geom_type == 'Polygon':
        rings = [shape.exterior, *shape.interiors]
    elif shape.geom_type in ('LineString', 'LinearRing'): rings = [shape]
    elif shape.geom_type == 'Point': return [] if shape.is_empty else [shape.buffer(radius, quad_segs=ARC_SEGMENTS)]
    else: return [p for child in getattr(shape, 'geoms', []) for p in edge_capsules(child, radius)]
    result = []
    for ring in rings:
        coords = list(ring.coords)
        result.extend(LineString((a,b)).buffer(radius, quad_segs=ARC_SEGMENTS) for a,b in zip(coords, coords[1:]))
    return result


def connected(domain, occupied, start, goal, radius, snap):
    # Polygonal circular arcs are conservatively enlarged to cover the exact
    # radius. Their maximum radial error is included in the final interval.
    inflation = 1/math.cos(math.pi/(4*ARC_SEGMENTS))
    r = max(radius*inflation, PRECISION)
    free = domain.difference(unary_union(edge_capsules(domain, r)))
    if not occupied.is_empty: free = free.difference(unary_union([occupied, *edge_capsules(occupied, r)]))
    a, b = Point(start[:2]), Point(goal[:2])
    for part in polygons(free):
        if part.distance(a) <= snap and part.distance(b) <= snap:
            return True
    return False


def measure(road, obstacles, starts, goals, parameters, evidence):
    p = parameters; empty = lambda reason: {'status': 'absent', 'reason': reason, 'evidence': evidence}
    if not len(road[1]): return empty('No actual road surface')
    if not starts or not goals: return empty('Required endpoint surface patches are absent')
    domain, ground = planar_surface(road)
    low, high = ground+p['surface_epsilon'], ground+p['clearance_height']
    occupied, objects = blockers(obstacles, domain, low, high)
    start_points = [(s['id'], endpoint(s)) for s in starts]; goal_points = [(g['id'], endpoint(g)) for g in goals]
    span = math.hypot(domain.bounds[2]-domain.bounds[0], domain.bounds[3]-domain.bounds[1])
    quantities = []
    for start_id, start in start_points:
        for goal_id, goal in goal_points:
            row = {'start_entity': start_id, 'goal_entity': goal_id,
                   'start_world_m': None if start is None else start.tolist(), 'goal_world_m': None if goal is None else goal.tolist()}
            if start is None or goal is None:
                quantities.append({'status': 'absent', 'reason': 'Endpoint surface has no actual triangles', **row}); continue
            if max(abs(start[2]-ground), abs(goal[2]-ground)) > p['max_step']+p['surface_epsilon']:
                quantities.append({'status': 'absent', 'reason': 'Endpoint patch cannot snap to the road at the public height tolerance', **row}); continue
            if not connected(domain, occupied, start, goal, 0., p['max_snap']):
                quantities.append({'status': 'absent', 'reason': 'Complete projected obstacles or road gaps disconnect the endpoint patches', **row}); continue
            lower, upper = 0., span/2
            iterations = 0
            while upper-lower > PRECISION/2 and iterations < 64:
                middle = (lower+upper)/2
                if connected(domain, occupied, start, goal, middle, p['max_snap']): lower = middle
                else: upper = middle
                iterations += 1
            width = 2*lower
            error_bound = 2*(upper-lower)+width*(1/math.cos(math.pi/(4*ARC_SEGMENTS))-1)+2*PRECISION
            allowed = .99*p['min_width']; half_scale = .01*p['min_width']
            normalized = max(allowed-width, 0.)/half_scale
            best = max(allowed-(width+error_bound), 0.)/half_scale
            if 2.**-best-2.**-normalized > .001:
                raise ValueError('Continuous route score remains uncertain at the declared polygon precision')
            quantities.append({'status': 'measured', **row, 'normalized_errors': [normalized], 'unit': 'm',
                'actual_bottleneck_width_m': width, 'width_error_bound_m': error_bound,
                'required_width_m': p['min_width'], 'allowed_width_m': allowed, 'half_scale_m': half_scale,
                'continuous_score_interval': [2.**-normalized, 2.**-best], 'bisection_iterations': iterations})
    return {'status': 'measured', 'quantities': quantities, 'evidence': evidence,
        'parameters': p, 'road_height_m': ground, 'road_domain': coordinates(domain),
        'blocker_domain': coordinates(occupied), 'blocker_objects': objects, 'precision_m': PRECISION,
        'circular_arc_quadrant_segments': ARC_SEGMENTS, 'registration': 'none',
        'scope': 'Complete horizontal road and all obstacle surfaces/closed interiors in the public clearance-height band; every endpoint pair',
        'limitations': 'Constant-height road only. Circular horizontal clearance and public endpoint-center snapping include terminal boundaries. Nonplanar envelopes require a height-field adapter.'}
