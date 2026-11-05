"""Finite complete-surface probes for cylindrical components, independent of names.

Closed circular cross-sections must persist along a geometric axis. A flat disk,
one ring, cube, or spherical bulge cannot establish a cylindrical container.
These probes count geometry; they do not certify watertightness or semantics.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from .metrics import MissingEvidence


def canonical_direction(direction):
    direction = np.asarray(direction, float)
    direction = direction / np.linalg.norm(direction)
    if direction[np.argmax(np.abs(direction))] < 0:
        direction = -direction
    return direction


def axis_candidates(surface, limit=16):
    normal = np.cross(surface[:, 1] - surface[:, 0], surface[:, 2] - surface[:, 0])
    area = np.linalg.norm(normal, axis=1)
    valid = area > 1e-12
    normal = normal[valid] / area[valid, None]
    area = area[valid]
    if not len(normal):
        return []
    sign = normal[np.arange(len(normal)), np.argmax(np.abs(normal), axis=1)] < 0
    normal[sign] *= -1
    # Area weighting prevents fine triangulation from dominating axis proposals.
    keys, inverse = np.unique(np.round(normal / .015).astype(np.int64), axis=0, return_inverse=True)
    weights = np.bincount(inverse, weights=area, minlength=len(keys))
    vectors = np.column_stack([np.bincount(inverse, weights=area * normal[:, i], minlength=len(keys)) for i in range(3)])
    order = np.argsort(-weights, kind='stable')[:48]
    normals = vectors[order] / np.linalg.norm(vectors[order], axis=1)[:, None]
    weights = weights[order] / area.sum()
    axes = []

    def append(direction):
        direction = canonical_direction(direction)
        if not any(abs(float(direction @ old)) > np.cos(np.deg2rad(4)) for old in axes):
            axes.append(direction)

    # Cap normals remain useful even when an unrelated large plane is present.
    for direction in normals[:4]:
        append(direction)
    proposals = []
    for i in range(len(normals)):
        for j in range(i):
            cross = np.cross(normals[i], normals[j])
            length = np.linalg.norm(cross)
            if length > .3:
                proposals.append((float(weights[i] * weights[j] * length), cross / length))
    proposals.sort(key=lambda row: -row[0])
    for _, direction in proposals:
        append(direction)
        if len(axes) >= limit:
            break
    return axes


def section_segments(surface, axis, offset, epsilon):
    distance = surface @ axis - offset
    rows = []
    owners = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        crossing = (distance[:, i] <= 0) != (distance[:, j] <= 0)
        indices = np.flatnonzero(crossing)
        if not len(indices):
            continue
        fraction = distance[indices, i] / (distance[indices, i] - distance[indices, j])
        rows.append(surface[indices, i] + fraction[:, None] * (surface[indices, j] - surface[indices, i]))
        owners.append(indices)
    if not rows:
        return np.empty((0, 2, 3)), np.empty(0, int)
    points = np.concatenate(rows)
    owners = np.concatenate(owners)
    order = np.argsort(owners, kind='stable')
    points = points[order]
    owners = owners[order]
    unique, start, counts = np.unique(owners, return_index=True, return_counts=True)
    valid = counts == 2
    segments = np.stack((points[start[valid]], points[start[valid] + 1]), axis=1)
    valid_length = np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1) > epsilon
    return segments[valid_length], unique[valid][valid_length]


def closed_loops(segments, epsilon):
    """Walk bounded planar faces, including two circular loops that touch."""
    if not len(segments):
        return []
    points = segments.reshape(-1, 2)
    parent = np.arange(len(points))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return int(index)

    for a, b in cKDTree(points).query_pairs(epsilon, output_type='ndarray'):
        a, b = root(a), root(b)
        if a != b:
            parent[max(a, b)] = min(a, b)
    indices = np.array([root(i) for i in range(len(points))]).reshape(-1, 2)
    edges = {tuple(sorted((int(a), int(b)))) for a, b in indices if a != b}
    neighbours = {}
    for a, b in edges:
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
    neighbours = {a: sorted(bs, key=lambda b: np.arctan2(*(points[b] - points[a])[::-1])) for a, bs in neighbours.items()}
    visited = set()
    loops = []
    for a, b in sorted(edges):
        for start in ((a, b), (b, a)):
            if start in visited:
                continue
            edge = start
            chain = []
            while edge not in visited:
                visited.add(edge)
                u, v = edge
                chain.append(u)
                around = neighbours[v]
                edge = (v, around[(around.index(u) - 1) % len(around)])
            if edge != start or len(chain) < 3:
                continue
            polygon = points[chain]
            area = np.sum(polygon[:, 0] * np.roll(polygon[:, 1], -1) - polygon[:, 1] * np.roll(polygon[:, 0], -1)) / 2
            if area > epsilon ** 2:
                loops.append(polygon)
    return loops


def circular_section(polygon, minimum_radius, maximum_radius, maximum_gap_degrees=60):
    # Remove triangulation-created collinear vertices before fitting a circle.
    before = polygon - np.roll(polygon, 1, axis=0)
    after = np.roll(polygon, -1, axis=0) - polygon
    cross = np.abs(before[:, 0] * after[:, 1] - before[:, 1] * after[:, 0])
    keep = cross > 1e-5 * np.linalg.norm(before, axis=1) * np.linalg.norm(after, axis=1)
    polygon = polygon[keep]
    if len(polygon) < 6:
        return None
    origin = polygon.mean(axis=0)
    local = polygon - origin
    coefficients, *_ = np.linalg.lstsq(np.column_stack((2 * local, np.ones(len(local)))), np.sum(local * local, axis=1), rcond=None)
    center = coefficients[:2]
    radius = float(np.sqrt(max(0., coefficients[2] + center @ center)))
    if not minimum_radius <= radius <= maximum_radius:
        return None
    residual = np.abs(np.linalg.norm(local - center, axis=1) - radius) / radius
    angles = np.sort(np.arctan2(*(local - center).T[::-1]))
    gap = float(np.diff(np.r_[angles, angles[0] + 2 * np.pi]).max())
    if float(np.sqrt(np.mean(residual ** 2))) > .025 or float(residual.max()) > .06 or gap > np.deg2rad(maximum_gap_degrees) + 1e-6:
        return None
    return {'center': center + origin, 'radius': radius, 'residual_rms': float(np.sqrt(np.mean(residual ** 2)))}


def detect_cylinders(surface, *, scale_height, scale_diagonal, sections=33, maximum_section_gap_degrees=60):
    surface = np.asarray(surface, float)
    if (surface.ndim != 3 or surface.shape[1:] != (3, 3) or not np.isfinite(surface).all()
            or not np.isfinite([scale_height, scale_diagonal]).all() or min(scale_height, scale_diagonal) <= 0):
        raise MissingEvidence('Finite full geometry and positive visible scale required')
    if len(surface) > 500_000:
        raise MissingEvidence('Cylinder probes exceed 500,000 triangles; no sampled fallback')
    if not len(surface):
        return {'status': 'measured', 'count': 0, 'components': []}
    epsilon = max(scale_diagonal * 1e-6, 1e-7)
    minimum_radius = scale_diagonal * .04
    maximum_radius = scale_diagonal * .4
    minimum_height = scale_height * .4
    normal = np.cross(surface[:, 1] - surface[:, 0], surface[:, 2] - surface[:, 0])
    norm = np.linalg.norm(normal, axis=1)
    normal = np.divide(normal, norm[:, None], out=np.zeros_like(normal), where=norm[:, None] > 0)
    components = []
    axes = axis_candidates(surface)
    for axis in axes:
        helper = np.eye(3)[np.argmin(np.abs(axis))]
        x = np.cross(axis, helper)
        x /= np.linalg.norm(x)
        y = np.cross(axis, x)
        basis = np.column_stack((x, y))
        projected = surface @ axis
        low, high = float(projected.min()), float(projected.max())
        if high - low < minimum_height:
            continue
        spacing = (high - low) / sections
        tracks = []
        for index, offset in enumerate(low + (np.arange(sections) + .417) * spacing):
            segments, owners = section_segments(surface, axis, offset, epsilon)
            # True axial side surfaces are needed, not the equator of a sphere.
            transverse = np.abs(normal[owners] @ axis) <= .25
            loops = closed_loops(segments[transverse] @ basis, epsilon)
            for polygon in loops:
                circle = circular_section(polygon, minimum_radius, maximum_radius, maximum_section_gap_degrees)
                if circle is None:
                    continue
                match = next((track for track in tracks if index - track['last_index'] <= 2
                    and np.linalg.norm(circle['center'] - track['center']) <= .1 * max(circle['radius'], track['radius'])
                    and .8 <= circle['radius'] / track['radius'] <= 1.25), None)
                if match is None:
                    tracks.append({**circle, 'first': float(offset), 'last': float(offset), 'last_index': index,
                        'indices': {index}, 'radii': [circle['radius']]})
                else:
                    match['last'] = float(offset)
                    match['last_index'] = index
                    match['indices'].add(index)
                    match['radii'].append(circle['radius'])
        for track in tracks:
            radius = float(np.median(track['radii']))
            height = track['last'] - track['first']
            if (len(track['indices']) < 4 or height < max(minimum_height, radius)
                    or height > 8 * radius or max(track['radii']) / min(track['radii']) > 1.25):
                continue
            center = basis @ track['center'] + axis * ((track['first'] + track['last']) / 2)
            # Inner/outer shells, repeated surfaces, and nearby axis proposals
            # cannot count the same spatial component more than once.
            if any(np.linalg.norm(center - np.asarray(old['center_m'])) < .6 * max(radius, old['radius_m']) for old in components):
                continue
            components.append({'center_m': center.tolist(), 'axis': axis.tolist(), 'radius_m': radius,
                'observed_axial_span_m': height, 'section_count': len(track['indices']),
                'radius_range_m': [float(min(track['radii'])), float(max(track['radii']))]})
    return {'status': 'measured', 'count': len(components), 'components': components,
        'axis_proposals': len(axes), 'section_planes_per_axis': sections, 'weld_epsilon_m': epsilon,
        'maximum_section_gap_degrees': maximum_section_gap_degrees,
        'minimum_radius_m': minimum_radius, 'maximum_radius_m': maximum_radius,
        'minimum_axial_span_m': minimum_height, 'threshold_status': 'pilot_not_calibrated',
        'scope': 'Finite persistent circular-section components; not watertightness, support, exact dimensions or semantic certification'}


def cylindrical_containers(candidate, baseline, reference, targets, definition):
    """Use visible reference extent for broad scale/location, never hidden shape."""
    from .l2_reference_numeric import triangles
    try:
        visible = reference['scene'].get('visible_surface', {})
        if visible.get('status') != 'measured':
            raise MissingEvidence('Visible reference extent is required')
        points = np.asarray([point for point, name in zip(visible['world_points_m'], visible['object_names'])
                             if name in targets], float)
        if len(points) < 8 or points.shape[1:] != (3,) or not np.isfinite(points).all():
            raise MissingEvidence('At least eight finite visible target points required')
        low, high = points.min(axis=0), points.max(axis=0)
        diagonal = float(np.linalg.norm(high - low))
        height = float(high[2] - low[2])
        before = baseline['scene']['objects']
        members = [triangles(obj, candidate) for name, obj in candidate['scene']['objects'].items()
                   if name not in before and obj.get('faces', 0) > 0 and obj.get('visible_render')]
        surface = np.concatenate(members) if members else np.empty((0, 3, 3))
        # v2.4.0 used 90 degrees; retain its published behaviour explicitly.
        result = detect_cylinders(surface, scale_height=height, scale_diagonal=diagonal,
            maximum_section_gap_degrees=definition.get('maximum_section_gap_degrees',90))
        margin = diagonal * .25
        inside = [item for item in result['components'] if np.all(np.asarray(item['center_m']) >= low - margin)
                  and np.all(np.asarray(item['center_m']) <= high + margin)]
        actual, expected = len(inside), definition['expected_count']
        return {**result, 'count_in_target_area': actual, 'expected_count': expected,
            'passed': actual == expected,
            'score': min(actual, expected) / max(actual, expected) if max(actual, expected) else 0.,
            'visible_extent_m': [low.tolist(), high.tolist()], 'location_margin_m': margin,
            'counted_components': inside, 'hidden_reference_geometry_used': False,
            'candidate_names_or_object_count_used_as_answers': False,
            'scope': 'Number of persistent cylindrical structures in the visible target neighbourhood; not complete shells, support, bands/caps or full task certification'}
    except MissingEvidence as error:
        return {'status': 'not_measurable', 'passed': False, 'score': 0., 'reason': str(error)}
