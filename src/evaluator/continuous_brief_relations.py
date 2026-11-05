"""Continuous public layout and attachment measurements on reviewed geometry.

All lengths are measured in the retained world frame. Geometry determines the
local measuring axes; no candidate transform or private target is fitted.
"""
import math
import numpy as np
from scipy.optimize import linear_sum_assignment

from .continuous_brief_numeric import actual_entities, interval_error, missing, population
from .continuous_sceneedit_surface import join
from .l2_brief_relations import long_axis
from .l2_brief_assemblies import clip_height, surface_band
from .l2_surface_relief import VerticalSurface, footprint


SUPPORTED = {'l2_side_layout', 'l2_attachment_correspondence', 'l2_entity_part_geometry'}


def surface(entity):
    vertices, faces = entity['mesh']
    return vertices[faces]


def quantity(observations, **metadata):
    return {'status': 'measured', 'observations': observations,
            'normalized_errors': [o['normalized_error'] for o in observations], **metadata}


def fractional(value, **metadata):
    """Preserve an exactly measured coverage fraction in the shared kernel."""
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Finite measured coverage in [0,1] required')
    if value == 0:
        return missing('No measured coverage of the required relation', measured_fraction=0., **metadata)
    return {'status': 'measured', 'normalized_errors': [-math.log2(value)],
            'measured_fraction': value, **metadata}


def geometric_score(observations):
    # Each probe must satisfy all simultaneous geometric constraints. Their
    # worst error remains continuous; there are no pass/fail grade bands.
    return 2.**-max(o['normalized_error'] for o in observations)


def layout(roles, p):
    axis_mesh = join([e['mesh'] for e in roles.get(p['axis_role'], [])])
    if not len(axis_mesh[1]):
        return [missing('Required longitudinal road/path surface absent')]
    origin, _, half_width, along, across = long_axis(axis_mesh[0][axis_mesh[1]])
    selected, selection = actual_entities(roles.get(p['role'], []), volumetric=True)
    if not selected:
        return [missing('Required layout entities absent', entity_selection=selection)]
    sides = {-1: [], 1: []}
    for entity in selected:
        points = surface(entity)[:, :, :2].reshape(-1, 2)-origin
        transverse, longitudinal = points@across, points@along
        center = float((transverse.min()+transverse.max())/2)
        side = 1 if center >= 0 else -1
        closest = float((side*transverse).min())
        sides[side].append({'entity': entity['id'],
            'along_m': float((longitudinal.min()+longitudinal.max())/2),
            'clearance_m': closest-half_width})
    rows = []
    for side in (-1, 1):
        entities = sorted(sides[side], key=lambda e: e['along_m'])
        count = interval_error(len(entities), p['per_side'], p['per_side'], half_scale=1.)
        rows.append(quantity([count], side=side, kind='side_count', entities=entities))
        probes = [interval_error(e['clearance_m'], 0., None, half_scale=p['row_tolerance_m'])
                  for e in entities]
        if probes:
            rows.append(quantity(probes, side=side, kind='whole_entity_side_clearance'))
        else:
            rows.append(missing('No entities on this required side', side=side, kind='whole_entity_side_clearance'))
        expected_rows = p['rows_per_side']
        if not expected_rows:
            continue
        if p['per_side'] % expected_rows:
            raise ValueError('The public regular-row layout requires integral row occupancy')
        # Fixed public occupancy makes equal longitudinal positions a row.
        # Sorting only defines the measuring groups; coordinates remain intact.
        occupancy = p['per_side']//expected_rows
        groups = [entities[i:i+occupancy] for i in range(0, len(entities), occupancy)]
        centers = []
        for index in range(max(expected_rows, len(groups))):
            group = groups[index] if index < len(groups) else []
            if len(group) != occupancy:
                rows.append(missing('Required row occupancy absent', side=side, row=index,
                                    required_occupancy=occupancy, actual_occupancy=len(group)))
                continue
            values = [e['along_m'] for e in group]
            span = max(values)-min(values)
            centers.append((max(values)+min(values))/2)
            rows.append(quantity([interval_error(span, 0., p['row_tolerance_m'],
                half_scale=p['row_tolerance_m'])], side=side, row=index, kind='row_band', entities=group))
        for index in range(expected_rows-1):
            if index+1 >= len(centers):
                rows.append(missing('Required distinct longitudinal row absent', side=side, row=index))
            else:
                rows.append(quantity([interval_error(centers[index+1]-centers[index],
                    p['row_tolerance_m'], None, half_scale=p['row_tolerance_m'])],
                    side=side, row=index, kind='row_separation'))
    return rows


def attachment_probes(attached, base, p):
    points, bottom, top, valid = surface_band(attached, p['grid_size'])
    heights = VerticalSurface(base).top(points)
    probes = []
    for xy, low, high, finite, roof in zip(points, bottom, top, valid, heights):
        if not finite or not np.isfinite(roof):
            probes.append({'xy_m': xy.tolist(), 'status': 'absent', 'score': 0.,
                           'reason': 'Finite attachment section or actual base surface absent'})
            continue
        thickness = float(high-low)
        observations = [
            interval_error(float(low-roof), None, p['max_gap_m'], half_scale=p['max_gap_m']),
            interval_error(float(high-roof), p['min_protrusion_m'], None, half_scale=p['min_protrusion_m']),
            interval_error(float((roof-low)/thickness), None, p['maximum_embedded_fraction'],
                           half_scale=p['maximum_embedded_fraction']),
        ]
        probes.append({'xy_m': xy.tolist(), 'bottom_m': float(low), 'top_m': float(high),
            'base_height_m': float(roof), 'status': 'measured', 'observations': observations,
            'score': geometric_score(observations)})
    coverage = math.fsum(row['score'] for row in probes)/len(probes)
    return min(1., coverage/p['required_fraction']), probes


def distinct_assignment(quality, required):
    """Maximum-weight matching with the public, fixed number of distinct pairs."""
    n, m = quality.shape
    count = min(required, n, m)
    if not count:
        return []
    # Dummy rows/columns leave exactly `count` real pairings. Optimizing a full
    # matching and selecting its best k edges need not optimize the required k.
    costs = np.zeros((n+m-count, n+m-count))
    costs[:n, :m] = -quality
    costs[n:, m:] = np.inf
    left, right = linear_sum_assignment(costs)
    return [(int(i), int(j)) for i, j in zip(left, right) if i < n and j < m]


def attachments(roles, p):
    bases, base_selection = actual_entities(roles.get(p['base_role'], []), volumetric=True)
    attached, attachment_selection = actual_entities(roles.get(p['attachment_role'], []), volumetric=True)
    required = p['minimum_distinct_bases']
    if not bases or not attached:
        return [missing('Required base or attachment surface absent', base_selection=base_selection,
                        attachment_selection=attachment_selection)]
    quality = np.zeros((len(attached), len(bases)))
    proof = []
    for i, part in enumerate(attached):
        for j, base in enumerate(bases):
            quality[i, j], probes = attachment_probes(surface(part), surface(base), p)
            proof.append({'attachment': part['id'], 'base': base['id'], 'score': float(quality[i, j]), 'probes': probes})
    # A one-to-one assignment measures distinct bases. Two chimneys on one house
    # cannot fulfil the requirement for chimneys on two different houses.
    matching = distinct_assignment(quality, required)
    distinct = math.fsum(float(quality[i, j]) for i, j in matching)/required
    every_attachment = float(quality.max(axis=1).mean())
    return [fractional(distinct, kind='distinct_base_coverage', required=required,
                assignments=[{'attachment': attached[i]['id'], 'base': bases[j]['id'],
                              'score': float(quality[i, j])} for i, j in matching], base_probes=proof),
            fractional(every_attachment, kind='all_attachment_coverage', actual_attachments=len(attached))]


def grave_decompositions(triangles, p):
    normal = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
    areas = np.linalg.norm(normal, axis=1)/2
    low, high = float(triangles[:, :, 2].min()), float(triangles[:, :, 2].max())
    planar = (np.ptp(triangles[:, :, 2], axis=1) <= 1e-5) & (np.abs(normal[:, 2]) > 1e-12)
    levels = triangles.mean(axis=1)[:, 2]
    candidates = []
    for level in np.unique(np.round(levels[planar], 5)):
        if not low+1e-5 < level < high-1e-5:
            continue
        mask = planar & (np.abs(levels-level) <= 1e-5)
        bed = triangles[mask]
        origin, radii, rotation = footprint(bed)
        upper = clip_height(triangles, level+1e-5, True)
        if not len(upper):
            continue
        points = np.unique(upper.reshape(-1, 3), axis=0)
        # Presence of a three-dimensional marker is categorical. Its dimensions,
        # proportions, separation and contact use continuous measured errors.
        if np.linalg.matrix_rank(points-points.mean(axis=0), tol=1e-7) < 3:
            continue
        _, upper_radii, _ = footprint(upper)
        horizontal = 2*min(radii); upright_width = 2*max(upper_radii)
        if min(horizontal, upright_width) <= 1e-8:
            continue
        lower = clip_height(triangles, float(bed[:, :, 2].max()), False)
        _, _, _, valid = surface_band(lower, p['grid_size'])
        area_fraction = float(areas[mask].sum()/(4*np.prod(radii)))
        offset = np.maximum(np.abs((points[:, :2]-origin)@rotation)-radii, 0.)
        offset_fraction = float(offset.max()/(2*max(radii)))
        observations = [
            interval_error(float((level-low)/horizontal), None, p['horizontal_max_height_ratio'],
                           half_scale=p['horizontal_max_height_ratio']),
            interval_error(float(high-level), p['min_protrusion_m'], None, half_scale=p['min_protrusion_m']),
            interval_error(float((high-level)/upright_width), p['upright_min_height_ratio'], None,
                           half_scale=p['upright_min_height_ratio']),
            interval_error(area_fraction, p['minimum_bed_area_fraction'], None,
                           half_scale=p['minimum_bed_area_fraction']),
            interval_error(offset_fraction, None, p['maximum_part_offset_fraction'],
                           half_scale=p['maximum_part_offset_fraction']),
            interval_error(float(upper[:, :, 2].min()-level), None, p['max_gap_m'], half_scale=p['max_gap_m']),
        ]
        finite_fraction = float(valid.sum()/len(valid))
        candidates.append({'bed_top_m': float(level), 'observations': observations,
            'finite_bed_fraction': finite_fraction,
            'score': geometric_score(observations)*finite_fraction})
    return candidates


def entity_parts(roles, p, minimum):
    entities, selection = actual_entities(roles.get(p['role'], []), volumetric=True)
    rows = []
    for entity in population(entities, minimum[p['role']]):
        if entity is None:
            rows.append(missing('Required complete grave entity absent')); continue
        candidates = grave_decompositions(surface(entity), p)
        rows.append(fractional(max((r['score'] for r in candidates), default=0.),
            entity=entity['id'], candidate_decompositions=candidates, entity_selection=selection))
    return rows


def measure(check, roles, minimum_entities, evidence):
    metric, p = check['metric'], check['params']
    if metric == 'l2_side_layout':
        rows = layout(roles, p)
    elif metric == 'l2_attachment_correspondence':
        rows = attachments(roles, p)
    elif metric == 'l2_entity_part_geometry':
        rows = entity_parts(roles, p, minimum_entities)
    else:
        raise ValueError('Unsupported continuous relation: '+metric)
    return {'status': 'measured', 'quantities': rows, 'evidence': evidence, 'native_check': check,
        'coordinate_space': 'world_metres', 'registration': 'none',
        'scope': 'Complete reviewed geometry; continuous public-range errors and fixed required populations',
        'kernel': '2**(-max(excess/public_half_scale)); exact measured fractions retained without verdict rounding'}
