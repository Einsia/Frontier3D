"""Public Brief2Scene quantities on complete, semantically reviewed triangles.

Role identification is separately bound. This kernel computes continuous
numerical compliance, with explicit missing-entity and missing-support zeros.
"""
import hashlib
import math
import numpy as np
from shapely.geometry import MultiPoint
from .continuous_numeric import line_intersections
from .continuous_sceneedit_surface import join, triangle_keys
from .continuous_surface import triangle_areas


def interval_error(value, low, high, tolerance=0., half_scale=None):
    nominal = max(abs(x) for x in (low, high) if x is not None)
    scale = .01*nominal if half_scale is None else half_scale
    if not math.isfinite(value) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('Finite quantity and positive public half scale required')
    lower = -math.inf if low is None else low-abs(low)*tolerance
    upper = math.inf if high is None else high+abs(high)*tolerance
    error = max(lower-value, value-upper, 0.)
    return {'actual': float(value), 'lower': low, 'upper': high, 'relative_tolerance': tolerance,
            'allowed_lower': None if low is None else lower, 'allowed_upper': None if high is None else upper,
            'absolute_error': float(error), 'half_scale': scale, 'normalized_error': float(error/scale)}


def actual_entities(entities, *, volumetric=False):
    """Deduplicate co-located complete triangle surfaces, independent of splitting."""
    accepted = []; rows = []; seen = {}
    for entity in entities:
        v, f = entity['mesh']; area = float(triangle_areas(v, f).sum())
        points = np.unique(v[f].reshape(-1, 3), axis=0) if len(f) else np.empty((0, 3))
        extent = np.linalg.svd(points-points.mean(axis=0), compute_uv=False) if len(points) else np.zeros(3)
        rank = int((extent > 1e-7).sum()); key = hashlib.sha256(np.unique(triangle_keys(v, f)).tobytes()).hexdigest()
        row = {'entity': entity['id'], 'surface_area_m2': area, 'rank': rank,
               'surface_identity': key, 'triangles': len(f)}
        if area <= 1e-12: row['rejected'] = 'No actual nondegenerate surface'
        elif volumetric and rank < 3: row['rejected'] = 'Required three-dimensional entity is flat or degenerate'
        elif key in seen: row['rejected'] = 'Coincident duplicate of '+seen[key]
        else:
            seen[key] = entity['id']; accepted.append(entity)
        rows.append(row)
    return accepted, rows


def population(entities, minimum):
    return entities+[None]*max(0, minimum-len(entities))


def missing(reason, **metadata): return {'status': 'absent', 'reason': reason, **metadata}


def dimensions(mesh):
    v, f = mesh; points = v[f].reshape(-1, 3)
    if not len(points): return None
    footprint = MultiPoint(points[:, :2]).minimum_rotated_rectangle
    if footprint.geom_type != 'Polygon' or footprint.area <= 0: return None
    corners = np.asarray(footprint.exterior.coords)[:4]
    extents = np.sort(np.linalg.norm(np.roll(corners, -1, axis=0)-corners, axis=1))
    return [float(extents[0]), float(extents[-1]), float(np.ptp(points[:, 2]))]


def measure(check, roles, minimum_entities, evidence):
    p = check['params']; metric = check['metric']; role = p['role']; selected = roles.get(role, [])
    selected, selection = actual_entities(selected, volumetric=metric == 'l2_brief_count')
    quantities = []
    if metric == 'l2_brief_count':
        observed = interval_error(len(selected), p['minimum'], p.get('maximum'), half_scale=1.)
        quantities = [{'status': 'measured', 'normalized_errors': [observed['normalized_error']], 'observations': [observed], 'unit': 'count'}]
        if not selected: quantities = [missing('No qualifying reviewed three-dimensional entity', observations=[observed])]
    elif metric == 'l2_brief_dimensions':
        if p['scope'] == 'union': selected = [{'id': role+' union', 'mesh': join([x['mesh'] for x in selected])}] if selected else []
        elif p['scope'] != 'each': raise ValueError('Unknown dimension population')
        for entity in population(selected, 1 if p['scope'] == 'union' else minimum_entities[role]):
            values = dimensions(entity['mesh']) if entity else None
            if values is None:
                quantities.append(missing('Required entity or horizontal surface extent is absent')); continue
            observations = [interval_error(value, lo, hi, p['relative_tolerance'])
                for value, lo, hi in zip(values, p['lower'], p['upper']) if lo is not None or hi is not None]
            quantities.append({'status': 'measured', 'entity': entity['id'], 'dimensions_m': values,
                'axes': ['horizontal_short', 'horizontal_long', 'vertical_span'], 'unit': 'm',
                'observations': observations, 'normalized_errors': [x['normalized_error'] for x in observations]})
    elif metric == 'l2_brief_level':
        support = join([e['mesh'] for e in roles.get(p['support_role'], [])])
        for entity in population(selected, minimum_entities[role]):
            if entity is None or not len(support[1]):
                quantities.append(missing('Required entity or local support geometry is absent')); continue
            v, f = entity['mesh']; points = np.unique(v[f].reshape(-1, 3), axis=0)
            if p['endpoint'] not in ('top', 'bottom'): raise ValueError('Unknown vertical endpoint')
            extremum = float(points[:, 2].max() if p['endpoint'] == 'top' else points[:, 2].min())
            probes = points[np.abs(points[:, 2]-extremum) <= 1e-6]
            ceiling = max(float(support[0][support[1]][:, :, 2].max()), float(points[:, 2].max()))+1.
            observations = []; uncovered = []
            for point in probes:
                hits = line_intersections(*support, [*point[:2], ceiling], [0., 0., -1.])
                hits = hits[hits >= 0.]
                if not len(hits): uncovered.append(point.tolist()); continue
                ground = ceiling-float(hits[0]); actual = float(point[2]-ground)
                observations.append({**interval_error(actual, p['lower'], p['upper'], p['relative_tolerance']),
                                     'probe_world_m': point.tolist(), 'support_height_m': ground})
            if uncovered:
                quantities.append(missing('Actual support surface absent under required extreme vertices',
                    entity=entity['id'], uncovered_world_m=uncovered, observations=observations)); continue
            quantities.append({'status': 'measured', 'entity': entity['id'], 'unit': 'm',
                'observations': observations, 'extreme_vertices': len(probes),
                'normalized_errors': [max(x['normalized_error'] for x in observations)],
                'aggregation': 'worst actual local height error across all endpoint vertices'})
    else: raise ValueError('Unimplemented Brief quantity: '+metric)
    return {'status': 'measured', 'quantities': quantities, 'evidence': evidence, 'native_check': check,
            'entity_selection': selection, 'coordinate_space': 'world_metres', 'registration': 'none',
            'scope': 'Complete selected surfaces; exact public ranges; local vertical surface intersections',
            'limitations': 'Semantic roles require a bound review. Endpoint contact is a geometric measurement only.'}


def editable(roles, minimum_entities, major_structures, evidence):
    rows = []; owners = {}
    for role in major_structures:
        for entity in roles.get(role, []):
            for obj in entity['objects']: owners.setdefault(obj['object'], set()).add((role, entity['id']))
    for role in major_structures:
        selected, _ = actual_entities(roles.get(role, []))
        for entity in population(selected, minimum_entities[role]):
            if entity is None:
                rows.append({'role': role, 'score': 0., 'reason': 'Required major structure absent'}); continue
            objects = entity['objects']
            # Independent instances and modifier-backed meshes remain editable.
            # A shared datablock does not prevent an instance transform edit.
            usable = bool(objects) and all(o['editable'] and len(owners[o['object']]) == 1 for o in objects)
            rows.append({'role': role, 'entity': entity['id'], 'score': float(usable),
                         'objects': [{'object': o['object'], 'editable': o['editable'], 'instance': o['instance'],
                                      'semantic_owners': len(owners[o['object']])} for o in objects]})
    if not rows: raise ValueError('Public major-structure population required')
    return {'status': 'measured', 'preserved_fraction': sum(r['score'] for r in rows)/len(rows),
            'evidence': evidence, 'observations': rows, 'minimum_entities': minimum_entities,
            'population': 'All observed major structures, padded to public minimum for missing required entities',
            'scope': 'Independent editable object/instance addresses; semantic child details scored visually'}
