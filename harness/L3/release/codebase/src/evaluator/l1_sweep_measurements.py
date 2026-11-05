"""Text014 task measurements with a private, hash-bound polynomial reference.

Finite section checks supplement, never replace, full two-sided surface bounds.
The tight-bend span is not a rectangular plane section of the reference solid.
Its geometry remains covered by the surface comparison, not a hidden width gate.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import shapely

from .l1_sections import section_loops
from .l1_sleeve import interval_check, unavailable, verdict
from .l1_surface import load_surface
from .l1_sweep import GUARD, compare_sweep, reference_mesh, validate_reference

PROTOCOL = 'l1-swept-bar-measurement-v1'
FEATURES = {'solid', 'surface', 'section_dimensions'}
FIELDS = {'width_m', 'depth_m', 'tolerance_m', 'reference_path', 'reference_sha256'}
FRACTIONS = (.15, .35, .5, .65, .85)


def validate_design(design):
    from .spec import relative_path
    if not isinstance(design, dict) or set(design) != FIELDS:
        raise ValueError('Sweep design needs explicit dimensions, tolerance and reference binding')
    if any(type(design[k]) not in (int, float) or not np.isfinite(design[k]) or design[k] <= 0
           for k in ('width_m', 'depth_m', 'tolerance_m')):
        raise ValueError('Sweep dimensions must be finite positive numbers')
    if not 64*GUARD < design['tolerance_m'] < min(design['width_m'], design['depth_m'])/10:
        raise ValueError('Unsupported sweep dimension precision')
    relative_path(design['reference_path'])
    if (not design['reference_path'].startswith('harness/') or not isinstance(design['reference_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', design['reference_sha256'])):
        raise ValueError('Sweep reference must be a hash-bound evaluator asset')


def section_frames(reference):
    spans, _ = validate_reference(reference)
    for index, span in enumerate(spans):
        for fraction in FRACTIONS:
            work = span.copy()
            while work.shape[1] > 1:
                work = (1-fraction)*work[:, :-1]+fraction*work[:, 1:]
            ends = work[:, 0]
            center = ends.mean(axis=0)
            direction = ends[1]-ends[0]
            if np.linalg.norm(direction) <= GUARD:
                raise ValueError('Unresolved reference section direction')
            direction /= np.linalg.norm(direction)
            yield {'span': index, 'fraction': fraction, 'center_m': [center[0], 0., center[1]],
                'width_axis': [direction[0], 0., direction[1]],
                'normal': [-direction[1], 0., direction[0]]}


def section_rectangle(mesh, frame):
    section = section_loops(mesh, frame['center_m'], frame['normal'], 0.)
    if section['status'] != 'ok':
        return unavailable(section.get('reason', 'Section unavailable'))
    candidates, polygons = [], []
    for loop in section['loops']:
        points = np.asarray(loop['points_m'])
        local = points @ np.asarray(section['basis_world'])[:, :2].T
        local += np.asarray(frame['normal'])*section['offset_m']
        xy = np.column_stack((local @ frame['width_axis'], local[:, 1]))
        polygon = shapely.Polygon(xy)
        if not polygon.is_valid:
            return unavailable('Invalid section boundary')
        polygons.append((loop, polygon))
        if loop['kind'] == 'outer' and polygon.covers(shapely.Point(0, 0)):
            candidates.append((xy, polygon))
    if len(candidates) != 1:
        return unavailable('A unique closed section enclosing the public centre is required')
    xy, polygon = candidates[0]
    if any(loop['kind'] == 'cavity' and polygon.intersects(hole) for loop, hole in polygons):
        return {'status': 'failed', 'passed': False, 'reason': 'A cavity intersects the solid rectangular section'}
    lower, upper = xy.min(axis=0), xy.max(axis=0)
    rectangle = shapely.box(*[lower[0], lower[1], upper[0], upper[1]])
    # Exact polygonal boundary comparison; no finite point subsampling. GEOS
    # distance alone is not a Hausdorff bound, so prove both complete lines
    # lie within fixed inscribed neighbourhoods of the other line.
    return {'status': 'measured', 'width_m': float(upper[0]-lower[0]), 'depth_m': float(upper[1]-lower[1]),
        'center_offset_m': ((lower+upper)/2).tolist(), 'offset_m': section['offset_m'],
        'boundary': polygon.boundary, 'rectangle': rectangle.boundary,
        'vertices': len(xy), 'area_m2': polygon.area}


def rectangular_bound(measured, tolerance):
    if measured['status'] != 'measured':
        return False
    # Round-buffer polygon chords are INSIDE the exact Euclidean tube. A
    # coverage success is conservative; failure is not a rejection witness.
    a, b = measured['boundary'], measured['rectangle']
    radius = tolerance-GUARD
    return bool(a.buffer(radius, quad_segs=8).covers(b) and b.buffer(radius, quad_segs=8).covers(a))


def measure_sections(mesh, reference, design):
    target, approximation = reference_mesh(reference, error_m=design['tolerance_m']/16)
    measured, omitted = [], []
    for frame in section_frames(reference):
        baseline = section_rectangle(target, frame)
        # This eligibility test consumes only the evaluator-owned reference;
        # a candidate cannot cause a difficult section to disappear.
        eligible = (baseline['status'] == 'measured'
            and max(abs(baseline[k]-design[k]) for k in ('width_m','depth_m')) < design['tolerance_m']/8
            and rectangular_bound(baseline, design['tolerance_m']/8))
        if not eligible:
            omitted.append({**frame, 'reason': 'Reference plane is not an unambiguous nominal rectangular section',
                'reference_width_m': baseline.get('width_m'), 'reference_depth_m': baseline.get('depth_m')})
            continue
        actual = section_rectangle(mesh, frame)
        info = {**frame, 'reference_width_m': baseline['width_m'], 'reference_depth_m': baseline['depth_m']}
        if actual['status'] != 'measured':
            measured.append({**info, **actual})
            continue
        dimensions = {k: interval_check(actual[k], actual[k], design[k], design['tolerance_m']) for k in ('width_m','depth_m')}
        rectangular = rectangular_bound(actual, design['tolerance_m'])
        dimensions['rectangular_boundary'] = {'status': 'passed' if rectangular else 'not_measurable',
            'passed': rectangular, 'reason': 'Two complete polygonal boundary tube covers; failure of this sufficient proof is unavailable'}
        dimensions['centering'] = interval_check(0., float(np.linalg.norm(actual['center_offset_m'])), 0., design['tolerance_m'])
        measured.append({**info, **verdict(**dimensions), 'plane_offset_m': actual['offset_m'],
            'vertices': actual['vertices'], 'width_m': actual['width_m'], 'depth_m': actual['depth_m']})
    if len(measured) < 5 or not {0, len(reference['strips_xz_m'])-1} <= {r['span'] for r in measured}:
        return {**unavailable('Insufficient unambiguous reference sections'), 'sections': measured, 'omitted': omitted}
    result = verdict(**{str(i): row for i,row in enumerate(measured)})
    return {k:v for k,v in result.items() if k!='measurements'} | {'sections': measured, 'omitted': omitted,
        'reference_approximation': approximation, 'scope': 'Finite fixed sections only, not continuous all-path dimension proof'}


def inspect_sweep(scene, design, *, trusted_root, assets_root, max_patches=262144):
    from .spec import contained_path
    validate_design(design)
    path = contained_path(Path(assets_root), design['reference_path'])
    if path.stat().st_size > 2*1024*1024:
        raise ValueError('Oversized sweep reference')
    with path.open('rb') as stream:
        content = stream.read(2*1024*1024+1)
    if len(content) > 2*1024*1024:
        raise ValueError('Oversized sweep reference')
    if hashlib.sha256(content).hexdigest() != design['reference_sha256']:
        raise ValueError('Sweep reference hash mismatch')
    reference = json.loads(content)
    validate_reference(reference)
    if reference.get('width_m') != design['width_m'] or reference['depth_m'] != design['depth_m'] or reference.get('surface_tolerance_m') != design['tolerance_m']:
        raise ValueError('Sweep design does not match its authored reference')
    objects = scene.get('objects', {})
    meshes = [(n,r) for n,r in objects.items() if r.get('entity_scope')=='delivery_geometry' and r.get('type')=='MESH']
    if len(meshes)!=1 or any(r.get('entity_scope')=='unsupported_delivery_geometry' for r in objects.values()):
        return {'protocol':PROTOCOL,'design':copy.deepcopy(design),'status':'failed','passed':False,
                'features':{n:{'status':'failed','passed':False,'reason':'Expected one editable sweep mesh'} for n in FEATURES}}
    name,record = meshes[0]
    mesh = load_surface(record['mesh_payload'], Path(trusted_root))
    valid = (record.get('valid_solid') is True and record.get('closed') is True
             and record.get('components')==1 and record.get('editable') is True)
    features = {'solid': {'status':'passed' if valid else 'failed','passed':valid},
        'surface': compare_sweep(mesh,reference,design['tolerance_m'],max_patches=max_patches),
        'section_dimensions': measure_sections(mesh,reference,design)}
    result = verdict(**features)
    return {k:v for k,v in result.items() if k!='measurements'} | {'protocol':PROTOCOL,'design':copy.deepcopy(design),'features':features,
        'source':{'object':name,'mesh_payload':copy.deepcopy(record['mesh_payload']),'trusted_solid':valid,
                  'reference':{'path':str(path),'sha256':design['reference_sha256'],'bytes':len(content)}}}
