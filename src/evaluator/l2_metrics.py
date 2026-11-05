"""L2 role claims verified against measured geometry, never object names.

Roles are a public submission interface. Shape/material semantics remain an
explicit limitation; an annotation by itself never establishes task success.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import distance_transform_edt, label
from scipy.spatial import ConvexHull, QhullError

from .metrics import MissingEvidence, _register, _scale, camera_delta, resolve


def validate_parameters(check):
    p = check.params
    for name in ('role','road_role','start_role','goal_role','support_role','camera','main','alternate'):
        if name in p and (not isinstance(p[name],str) or not p[name]):
            raise ValueError(f'Invalid {name} in {check.id}')
    for name in ('roles','parts'):
        if name in p and (not isinstance(p[name],list) or not p[name] or any(not isinstance(v,str) or not v for v in p[name])):
            raise ValueError(f'Invalid {name} in {check.id}')
    for name in ('min_volume','min_width','cell_size','max_snap','max_gap','max_penetration','bound_tolerance','max_fill','min_azimuth_degrees','clearance_height'):
        if name in p and (type(p[name]) not in (int,float) or not math.isfinite(p[name]) or p[name]<0):
            raise ValueError(f'Invalid {name} in {check.id}')
    for name in ('min_count','max_count'):
        if name in p and (type(p[name]) is not int or p[name]<1):
            raise ValueError(f'Invalid {name} in {check.id}')
    if check.metric=='l2_entity':
        low, high = np.asarray(p['min_dimensions']), np.asarray(p['max_dimensions'])
        if low.shape!=(3,) or high.shape!=(3,) or not np.isfinite(low).all() or not np.isfinite(high).all() or np.any(low<0) or np.any(high<low):
            raise ValueError('Invalid entity dimensions')
        if 'target_bounds' in p:
            bounds=np.asarray(p['target_bounds'])
            if bounds.shape!=(2,3) or not np.isfinite(bounds).all() or np.any(bounds[1]<bounds[0]):
                raise ValueError('Invalid target bounds')
    if check.metric=='l2_route' and (p['cell_size']<=0 or p['min_width']<=0 or p['cell_size']>p['min_width']/4):
        raise ValueError('Navigation grid must resolve the required width')


def planar_dimensions(members):
    points = np.array([p[:2] for _,o in members for triangle in o.get('surface_triangles', []) for p in triangle])
    if len(points) < 3:
        raise MissingEvidence('Evaluated footprint geometry is required')
    points = np.unique(points, axis=0)
    try:
        hull = points[ConvexHull(points).vertices]
    except QhullError:
        return sorted(np.ptp(points, axis=0))
    edges = np.roll(hull,-1,axis=0)-hull
    angles = np.unique(np.arctan2(edges[:,1],edges[:,0]) % (np.pi/2))
    best = None
    for angle in angles:
        c,s = np.cos(angle), np.sin(angle)
        dimensions = np.ptp(hull @ np.array([[c,-s],[s,c]]), axis=0)
        if best is None or np.prod(dimensions) < np.prod(best):
            best = dimensions
    return sorted(best)


def entities(evidence, role):
    objects = resolve(evidence, "/scene/objects")
    groups = {}
    for name, obj in objects.items():
        if obj.get("role") != role or obj.get("type") != "MESH" or not obj.get("visible_render"):
            continue
        if not obj.get("bounds") or obj.get("faces", 0) <= 0:
            continue
        groups.setdefault(obj.get("entity", name), []).append((name, obj))
    result = []
    for identity, members in groups.items():
        bounds = np.asarray([o["bounds"] for _, o in members], dtype=float)
        low, high = bounds[:, 0].min(axis=0), bounds[:, 1].max(axis=0)
        result.append({"id": identity, "members": members, "low": low, "high": high,
                       "dimensions": high-low, "volume": sum(o.get("volume", 0) for _, o in members)})
    return result


@_register("l2_entity", "role min_dimensions max_dimensions min_volume", "min_count max_count parts target_bounds bound_tolerance max_fill")
def entity_geometry(check, evidence, spec):
    p = check.params
    outcomes = []
    for entity in entities(evidence, p["role"]):
        d = entity["dimensions"]
        measured = np.array([*planar_dimensions(entity['members']), d[2]])
        minimum = np.array([*sorted(p['min_dimensions'][:2]),p['min_dimensions'][2]])
        maximum = np.array([*sorted(p['max_dimensions'][:2]),p['max_dimensions'][2]])
        passed = bool(np.all(measured >= minimum-1e-6) and np.all(measured <= maximum+1e-6)
                      and entity["volume"] >= p["min_volume"])
        parts = {o.get("part") for _, o in entity["members"] if o.get("volume", 0) > 1e-8}
        passed &= set(p.get("parts", [])) <= parts
        if "target_bounds" in p:
            expected = np.asarray(p["target_bounds"], float)
            tolerance = p.get("bound_tolerance", .25)
            passed &= bool(np.all(np.abs(entity["low"]-expected[0]) <= tolerance)
                           and np.all(np.abs(entity["high"]-expected[1]) <= tolerance))
        if "max_fill" in p:
            passed &= entity["volume"] / max(float(np.prod(d)), 1e-12) <= p["max_fill"]
        outcomes.append({"entity": entity["id"], "dimensions": measured.tolist(),
                         "volume": entity["volume"], "parts": sorted(x for x in parts if x), "passed": bool(passed)})
    count = sum(item["passed"] for item in outcomes)
    passed = p.get("min_count", 1) <= count <= p.get("max_count", 100000)
    # Invalid extra entities cannot be hidden behind one valid instance.
    passed &= all(item["passed"] for item in outcomes)
    return float(passed), {"role": p["role"], "entities": outcomes, "valid_count": count}


@_register('l2_extent', 'role expected tolerance')
def role_extent(check, evidence, spec):
    selected = entities(evidence, check.params['role'])
    actual = np.array(planar_dimensions([m for e in selected for m in e['members']]))
    expected = np.sort(check.params['expected'])
    errors = np.abs(actual-expected)
    passed = bool(np.all(errors <= _scale(check.params['tolerance'],spec)))
    return float(passed), {'dimensions':actual.tolist(),'absolute_error':errors.tolist(),'within_tolerance':passed}


@_register('l2_camera_delta', 'camera', 'baseline_camera reference_camera expected_local_delta max_location_delta max_rotation_delta max_lens_delta')
def tolerant_camera_delta(check, evidence, spec):
    score, details = camera_delta(check, evidence, spec)
    passed = all(details[field+'_error'] <= _scale(check.params.get('max_'+field+'_delta',.01),spec)
                 for field in ('location','rotation','lens') if field+'_error' in details)
    return score, {**details,'within_tolerance':passed}


def _triangles(objects, *, top=None, bottom=None):
    for _, obj in objects:
        triangles = obj.get("surface_triangles")
        if triangles is None:
            raise MissingEvidence("Missing evaluated surface triangles")
        for triangle in triangles:
            t = np.asarray(triangle, dtype=float)
            if top is not None and t[:, 2].min() > top:
                continue
            if bottom is not None and t[:, 2].max() < bottom:
                continue
            yield t


def _inside(points, triangle):
    # Barycentric inclusion in the actual projected triangle (not its AABB).
    a, b, c = triangle[:, :2]
    v0, v1 = b-a, c-a
    denominator = v0[0]*v1[1]-v0[1]*v1[0]
    if abs(denominator) < 1e-12:
        return np.zeros(points.shape[:-1], dtype=bool)
    v = points-a
    u = (v[..., 0]*v1[1]-v[..., 1]*v1[0])/denominator
    w = (v0[0]*v[..., 1]-v0[1]*v[..., 0])/denominator
    return (u >= -1e-7) & (w >= -1e-7) & (u+w <= 1+1e-7)


@_register("l2_support", "roles max_gap max_penetration", "support_role")
def supported_entities(check, evidence, spec):
    p = check.params
    supports = [m for e in entities(evidence, p.get("support_role", "ground")) for m in e["members"]]
    if not supports:
        raise MissingEvidence("No geometric support surface")
    triangles = list(_triangles(supports))
    outcomes = []
    for role in p["roles"]:
        selected = entities(evidence, role)
        if not selected:
            raise MissingEvidence(f"No visible geometry for role {role}")
        for e in selected:
            # Lowest vertices of the whole entity: a mattress/seat need not touch the floor.
            points = [v for _, o in e["members"] for v in o.get("support_points", [])
                      if v[2] <= e["low"][2]+.02]
            gaps = []
            for point in points:
                heights = []
                for t in triangles:
                    if _inside(np.asarray(point[:2]), t):
                        normal = np.cross(t[1]-t[0], t[2]-t[0])
                        if abs(normal[2]) > 1e-10:
                            heights.append(float(t[0, 2]-(normal[0]*(point[0]-t[0, 0])+normal[1]*(point[1]-t[0, 1]))/normal[2]))
                if heights:
                    gaps.append(point[2]-max(heights))
            passed = bool(gaps) and min(gaps) >= -p["max_penetration"] and min(gaps) <= p["max_gap"]
            outcomes.append({"role": role, "entity": e["id"], "gaps": gaps, "passed": bool(passed)})
    return float(all(o["passed"] for o in outcomes)), {"entities": outcomes}


def _rasterize(mask, triangles, origin, cell):
    for t in triangles:
        xy = t[:, :2]
        low = np.maximum(0, np.floor((xy.min(axis=0)-origin)/cell).astype(int))
        high = np.minimum(np.array(mask.shape[::-1])-1, np.ceil((xy.max(axis=0)-origin)/cell).astype(int))
        if np.any(high < low):
            continue
        x, y = np.meshgrid(np.arange(low[0], high[0]+1), np.arange(low[1], high[1]+1))
        points = np.stack((x, y), axis=-1)*cell+origin+cell/2
        mask[low[1]:high[1]+1, low[0]:high[0]+1] |= _inside(points, t)


def _obstacle_mask(objects, shape, origin, cell, bottom, top):
    blocked = np.zeros(shape, bool)
    for member in objects:
        lower, upper = np.full(shape, np.inf), np.full(shape, -np.inf)
        for t in _triangles([member]):
            normal = np.cross(t[1]-t[0], t[2]-t[0])
            if abs(normal[2]) < 1e-12:
                continue
            low = np.maximum(0, np.floor((t[:, :2].min(axis=0)-origin)/cell).astype(int))
            high = np.minimum(np.array(shape[::-1])-1, np.ceil((t[:, :2].max(axis=0)-origin)/cell).astype(int))
            if np.any(high < low):
                continue
            x, y = np.meshgrid(np.arange(low[0], high[0]+1), np.arange(low[1], high[1]+1))
            points = np.stack((x,y), axis=-1)*cell+origin+cell/2
            inside = _inside(points, t)
            height = t[0,2]-(normal[0]*(points[...,0]-t[0,0])+normal[1]*(points[...,1]-t[0,1]))/normal[2]
            index = np.s_[low[1]:high[1]+1, low[0]:high[0]+1]
            lower[index] = np.minimum(lower[index], np.where(inside, height, np.inf))
            upper[index] = np.maximum(upper[index], np.where(inside, height, -np.inf))
        blocked |= (upper >= bottom) & (lower <= top)
    return blocked


@_register("l2_route", "road_role start_role goal_role min_width cell_size max_snap", "clearance_height")
def traversable_route(check, evidence, spec, *, diagnostic_directory=None):
    p = check.params
    roads = entities(evidence, p["road_role"])
    starts, goals = entities(evidence, p["start_role"]), entities(evidence, p["goal_role"])
    if not roads or not starts or not goals:
        raise MissingEvidence("Road, entrance and work-zone geometry are required")
    road_members = [m for e in roads for m in e["members"]]
    cell = float(p["cell_size"])
    if not math.isfinite(cell) or cell <= 0 or p["min_width"] <= 0:
        raise ValueError("Invalid navigation resolution/width")
    origin = np.min([e["low"][:2] for e in roads], axis=0)-cell*2
    high = np.max([e["high"][:2] for e in roads], axis=0)+cell*2
    shape = np.ceil((high-origin)/cell).astype(int)[::-1]
    if np.prod(shape) > 2_000_000:
        raise ValueError("Navigation grid exceeds frozen capacity")
    road = np.zeros(shape, bool)
    _rasterize(road, _triangles(road_members), origin, cell)
    elevation = max(e["high"][2] for e in roads)
    excluded = {n for n, _ in road_members}
    obstacles = [(n, o) for n, o in resolve(evidence, "/scene/objects").items()
                 if n not in excluded and o.get("type") == "MESH" and o.get("visible_render")
                 and o.get("bounds") and o["bounds"][1][2] > elevation+.15]
    blocked = _obstacle_mask(obstacles, shape, origin, cell, elevation+.15, elevation+p.get("clearance_height", 4))
    free = road & ~blocked
    radius = distance_transform_edt(free)*cell
    usable = free & (radius >= p["min_width"]/2-cell/2)
    components, _ = label(usable)  # Four-neighbour connectivity prevents diagonal corner leaks.
    def nearby(e):
        center = (e["low"][:2]+e["high"][:2])/2
        yy, xx = np.nonzero(usable)
        points = np.stack((xx, yy), axis=-1)*cell+origin+cell/2
        keep = np.linalg.norm(points-center, axis=1) <= p["max_snap"]
        return set(components[yy[keep], xx[keep]].tolist())-{0}
    start_labels = set().union(*(nearby(e) for e in starts))
    goal_labels = set().union(*(nearby(e) for e in goals))
    passed = bool(start_labels & goal_labels)
    bottleneck = None
    if diagnostic_directory is not None:
        # Largest raster radius connecting endpoint neighborhoods; advisory only.
        yy, xx = np.indices(free.shape)
        xy = np.stack((xx, yy), axis=-1)*cell+origin+cell/2
        endpoint_masks = []
        for selected in (starts, goals):
            endpoint_masks.append(np.logical_or.reduce([
                np.linalg.norm(xy-(e['low'][:2]+e['high'][:2])/2,axis=-1) <= p['max_snap'] for e in selected]))
        def connected_at(radius_threshold):
            labels, _ = label(free & (radius >= radius_threshold))
            a,b = [set(labels[m].tolist())-{0} for m in endpoint_masks]
            return bool(a & b)
        if connected_at(0):
            lo, hi = 0., float(radius.max())
            for _ in range(16):
                middle = (lo+hi)/2
                if connected_at(middle):
                    lo = middle
                else:
                    hi = middle
            bottleneck = 2*lo
        from .l2_diagnostics import write_route
        write_route(diagnostic_directory, road, blocked, usable, radius, origin, cell,
                    start_labels, goal_labels, components)
    return float(passed), {"connected_with_clear_width": passed, "min_width": p["min_width"],
                           "cell_size": cell, "road_cells": int(road.sum()), "blocked_cells": int((road & blocked).sum()),
                           "traversable_cells": int(usable.sum()),
                           **({"approximate_bottleneck_width_m": bottleneck, "diagnostic_only": True} if diagnostic_directory is not None else {})}


@_register("l2_camera_separation", "main alternate min_azimuth_degrees")
def camera_separation(check, evidence, spec):
    cameras = resolve(evidence, "/scene/cameras")
    a, b = (cameras.get(check.params[k]) for k in ("main", "alternate"))
    if not a or not b:
        raise MissingEvidence("Both output cameras are required")
    directions = [-np.asarray(c["basis_z"][:2], float) for c in (a, b)]
    norm = np.linalg.norm(directions[0])*np.linalg.norm(directions[1])
    if norm < 1e-9:
        raise MissingEvidence("Camera azimuth is undefined")
    angle = math.degrees(math.acos(np.clip(np.dot(*directions)/norm, -1, 1)))
    return float(angle >= check.params["min_azimuth_degrees"]), {"azimuth_difference": angle}


@_register("l2_part_materials", "role parts")
def part_materials(check, evidence, spec):
    outcomes = []
    for e in entities(evidence, check.params["role"]):
        for part in check.params["parts"]:
            objects = [o for _, o in e["members"] if o.get("part") == part]
            materials = [m for o in objects for m in o.get("material_properties", [])]
            passed = bool(materials) and all(m.get("principled") and m.get("metallic", 1) <= .1
                                            and .2 <= m.get("roughness", 0) <= 1 for m in materials)
            outcomes.append({"entity": e["id"], "part": part, "passed": passed})
    return float(bool(outcomes) and all(o["passed"] for o in outcomes)), {"parts": outcomes,
        "limitation": "Checks measurable nonmetallic rough materials; wood/fabric appearance needs visual review."}
