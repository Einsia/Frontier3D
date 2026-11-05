"""Explicit mechanical measurements from world-space triangles and public probes.

Probes are frozen before candidate evaluation. Circular fitting measures a local
feature; it never transforms a candidate or aligns it to reference geometry.
"""
import numpy as np


def line_intersections(vertices, triangles, origin, direction, merge_m=1e-8):
    v, f, o, d = np.asarray(vertices, float), np.asarray(triangles), np.asarray(origin, float), np.asarray(direction, float)
    if o.shape != (3,) or d.shape != (3,) or not np.isfinite(o).all() or not np.isfinite(d).all() or not np.linalg.norm(d):
        raise ValueError('Finite line and nonzero direction required')
    d = d/np.linalg.norm(d)
    xyz = v[f]; e1, e2 = xyz[:, 1]-xyz[:, 0], xyz[:, 2]-xyz[:, 0]
    h = np.cross(d, e2); determinant = np.einsum('ij,ij->i', e1, h)
    valid = np.abs(determinant) > 1e-14*np.linalg.norm(e1, axis=1)*np.linalg.norm(e2, axis=1)
    inv = np.divide(1., determinant, out=np.zeros_like(determinant), where=valid)
    s = o-xyz[:, 0]; u = inv*np.einsum('ij,ij->i', s, h)
    q = np.cross(s, e1); w = inv*(q@d)
    t = inv*np.einsum('ij,ij->i', e2, q)
    values = np.sort(t[valid & (u >= -1e-9) & (w >= -1e-9) & (u+w <= 1+1e-9)])
    if not len(values): return values
    return values[np.r_[True, np.diff(values) > merge_m]]


def basis(axis):
    w = np.asarray(axis, float); w /= np.linalg.norm(w)
    a = np.eye(3)[np.argmin(np.abs(w))]
    u = np.cross(a, w); u /= np.linalg.norm(u)
    return np.column_stack([u, np.cross(w, u), w])


def circle_probe(vertices, triangles, definition):
    center = np.asarray(definition['center_m'], float)
    frame = basis(definition['axis'])
    expected_radius = definition['radius_hint_m']
    limit = definition.get('search_radius_m', 2*expected_radius)
    angles = definition.get('angles', np.linspace(0, 2*np.pi, 64, endpoint=False).tolist())
    points, missing = [], []
    for angle in angles:
        direction = frame[:, 0]*np.cos(angle)+frame[:, 1]*np.sin(angle)
        hits = line_intersections(vertices, triangles, center, direction)
        positive = hits[(hits > 1e-9) & (hits < limit)]
        if not len(positive): missing.append(float(angle)); continue
        # Select the declared inner/outer surface in a public spatial window.
        distance = positive[0] if definition.get('boundary', 'inner') == 'inner' else positive[-1]
        points.append(center+distance*direction)
    if missing:
        return {'status': 'absent', 'reason': 'Required radial boundary missing in declared section',
                'missing_angles': missing, 'observed_rays': len(points), 'required_rays': len(angles)}
    points = np.asarray(points)
    local = (points-center)@frame[:, :2]
    fit, _, rank, _ = np.linalg.lstsq(np.column_stack([2*local, np.ones(len(local))]), (local**2).sum(1), rcond=None)
    radius2 = fit[2]+fit[:2]@fit[:2]
    if rank != 3 or radius2 <= 0:
        return {'status': 'absent', 'reason': 'Observed section has no finite circular fit'}
    radius = float(np.sqrt(radius2)); observed_center = center+frame[:, :2]@fit[:2]
    residual = np.abs(np.linalg.norm(local-fit[:2], axis=1)-radius)
    return {'status': 'measured', 'radius_m': radius, 'diameter_m': 2*radius,
        'center_world_m': observed_center.tolist(), 'radial_residuals_m': residual.tolist(),
        'points_world_m': points.tolist(), 'fitting': 'feature_measurement_only_no_candidate_transform'}


def line_probe(vertices, triangles, definition):
    hits = line_intersections(vertices, triangles, definition['origin_m'], definition['axis'])
    lower, upper = definition.get('window_m', [-float('inf'), float('inf')])
    selected = hits[(hits >= lower) & (hits <= upper)]
    mode = definition.get('mode', 'bracket')
    if mode in ('bracket', 'outer_bracket'):
        negative, positive = selected[selected < -1e-9], selected[selected > 1e-9]
        if not len(negative) or not len(positive):
            return {'status': 'absent', 'reason': 'Required two-sided boundary missing', 'intersections_m': hits.tolist()}
        endpoints = [float(negative[-1 if mode == 'bracket' else 0]), float(positive[0 if mode == 'bracket' else -1])]
        actual = endpoints[1]-endpoints[0]
    elif mode in ('first_positive', 'last_positive'):
        positive = selected[selected > 1e-9]
        if not len(positive): return {'status': 'absent', 'reason': 'Required boundary missing', 'intersections_m': hits.tolist()}
        actual = float(positive[0 if mode == 'first_positive' else -1]); endpoints = [actual]
    else: raise ValueError('Unknown line measurement')
    direction = np.asarray(definition['axis'], float); direction /= np.linalg.norm(direction)
    center = np.asarray(definition['origin_m'], float)+direction*np.mean(endpoints)
    return {'status': 'measured', 'distance_m': actual, 'endpoints_m': endpoints, 'center_world_m': center.tolist(),
            'intersections_m': hits.tolist(), 'origin_m': definition['origin_m'], 'axis': definition['axis']}


def scalar_error(actual, expected, tolerance, half_scale=None):
    values = np.asarray(actual, float); wanted = np.asarray(expected, float)
    if values.shape != wanted.shape or not np.isfinite(values).all() or not np.isfinite(wanted).all():
        raise ValueError('Comparable finite numeric observations required')
    scale = tolerance if half_scale is None else half_scale
    if tolerance < 0 or scale <= 0 or not np.isfinite([tolerance, scale]).all():
        raise ValueError('Valid tolerance and positive half scale required')
    return (np.maximum(np.abs(values-wanted)-tolerance, 0)/scale).reshape(-1).tolist()


def observe(vertices, triangles, definition):
    kind = definition['kind']
    if kind == 'circle': return circle_probe(vertices, triangles, definition)
    if kind == 'line': return line_probe(vertices, triangles, definition)
    if kind == 'pair_distance':
        observations = [observe(vertices, triangles, item) for item in definition['probes']]
        if any(item['status'] == 'absent' for item in observations):
            return {'status': 'absent', 'reason': 'Required feature pair not observed', 'pair': observations}
        delta = np.asarray(observations[1]['center_world_m'])-observations[0]['center_world_m']
        distance = abs(delta[definition['distance_component']]) if 'distance_component' in definition else np.linalg.norm(delta)
        return {'status': 'measured', 'distance_m': float(distance), 'pair': observations}
    raise ValueError('Unknown numeric probe kind: '+kind)


def measure_probes(vertices, triangles, definitions, evidence):
    if not definitions or not evidence: raise ValueError('Frozen probes and bound evidence required')
    errors, rows, quantities = [], [], []
    for definition in definitions:
        observation = observe(vertices, triangles, definition)
        row = {'definition': definition, 'observation': observation}; rows.append(row)
        if observation['status'] == 'absent':
            quantities.append({'status':'absent','reason':observation['reason'],'probe_index':len(rows)-1})
            continue
        field = definition['value']
        actual = observation[field]
        if 'component' in definition: actual = actual[definition['component']]
        if 'norm_components' in definition: actual = float(np.linalg.norm(np.asarray(actual)[definition['norm_components']]))
        actual = np.asarray(actual)*definition.get('multiply', 1)+definition.get('value_offset_m', 0)
        actual = actual.tolist()
        row['actual'] = actual
        row['normalized_errors'] = scalar_error(actual, definition['expected'], definition['tolerance_m'])
        errors.extend(row['normalized_errors'])
        quantities.append({'status':'measured','normalized_errors':row['normalized_errors'],
                           'actual':actual,'expected':definition['expected'],'probe_index':len(rows)-1})
    return {'observations': rows, 'normalized_errors': errors, 'quantities':quantities, 'evidence': evidence,
            'absent_probes': sum(r['observation']['status'] == 'absent' for r in rows),
            'status': 'measured'}
