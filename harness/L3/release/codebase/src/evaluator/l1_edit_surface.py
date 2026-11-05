"""Finite sampled native edit-surface similarity in unchanged world coordinates.

This is a quality measurement, never a proof of every CAD dimension or a
continuous Hausdorff bound. Public initial geometry defines preservation.
"""
from pathlib import Path

import numpy as np

from .l1_surface import SurfaceMesh, load_surface, sample_surface, surface_distances

PROTOCOL = 'l1-edit-sampled-surface-v1'


def scene_mesh(scene, root):
    vertices, triangles, offset = [], [], 0
    for obj in scene['objects'].values():
        if obj.get('type') != 'MESH':
            continue
        mesh = load_surface(obj['mesh_payload'], Path(root), surface_only=True)
        vertices.append(mesh.vertices)
        triangles.append(mesh.triangles + offset)
        offset += len(mesh.vertices)
    if not vertices:
        raise ValueError('No measured native mesh surface')
    return SurfaceMesh(np.concatenate(vertices), np.concatenate(triangles))


def compare(candidate, baseline, reference, *, dimension_m, preserve_m, samples=4096):
    def similarity(distances, tolerance):
        return float(np.exp(-np.maximum(distances-tolerance, 0)/tolerance).mean())
    ref_points = sample_surface(reference, samples, 171)
    initial_points = sample_surface(baseline, samples, 172)
    candidate_points = sample_surface(candidate, samples, 173)
    changed_reference = surface_distances(ref_points, baseline) > preserve_m
    protected_initial = surface_distances(initial_points, reference) <= preserve_m
    changed_candidate = surface_distances(candidate_points, baseline) > preserve_m
    if changed_reference.sum() < 8 or protected_initial.sum() < 8:
        return {'protocol':PROTOCOL, 'status':'not_measurable',
                'reason':'Insufficient sampled target or protected surface; no default full score'}
    target_distances = surface_distances(ref_points[changed_reference], candidate)
    target_recall = similarity(target_distances, dimension_m)
    if changed_candidate.any():
        extra_distances = surface_distances(candidate_points[changed_candidate], reference)
        target_precision = similarity(extra_distances, dimension_m)
    else:
        target_precision = 0.
    preserve_distances = surface_distances(initial_points[protected_initial], candidate)
    return {'protocol':PROTOCOL, 'status':'measured',
            'target':float((target_recall*target_precision)**.5),
            'preservation':similarity(preserve_distances, preserve_m),
            'target_recall':target_recall, 'target_precision':target_precision,
            'target_sample_count':int(changed_reference.sum()),
            'candidate_changed_sample_count':int(changed_candidate.sum()),
            'protected_sample_count':int(protected_initial.sum()), 'samples_per_scene':samples,
            'dimension_m':dimension_m, 'preserve_m':preserve_m,
            'target_mean_distance_m':float(target_distances.mean()),
            'preserved_mean_distance_m':float(preserve_distances.mean()),
            'scope':'sampled_edit_surface_not_complete_dimensional_or_material_verification'}


def measure(payload):
    root = payload['trusted_root']
    result = compare(*(scene_mesh(payload[k], root) for k in ('scene','baseline','reference')),
                     **payload['policy'])
    result['source'] = {k:[obj['mesh_payload']['sha256'] for obj in payload[k]['objects'].values()
                           if obj.get('type') == 'MESH'] for k in ('scene','baseline','reference')}
    result['surface_diagnostics'] = {k: {
        name: load_surface(obj['mesh_payload'], Path(root), surface_only=True).surface_diagnostics
        for name, obj in payload[k]['objects'].items() if obj.get('type') == 'MESH'
    } for k in ('scene', 'baseline', 'reference')}
    return result


def collect(spec, evidence, output, deadline):
    if 'l1_edit_quality' not in spec.to_dict():
        return
    from .l1_compute import run_compute
    from .l1_failures import InspectionFailure, record_failure
    from .metrics import resolve, MissingEvidence
    for label, pointer in (('native','/scene'),('glb','/artifacts/scene.glb/scene')):
        path = '/edit_surface/'+label
        try:
            payload = {'scene':resolve(evidence,pointer), 'baseline':resolve(evidence,'/baseline'),
                       'reference':resolve(evidence,'/reference'), 'trusted_root':str(output),
                       'policy':spec.to_dict()['l1_edit_quality']['surface']}
            result = run_compute('edit_surface',payload,output=output/'edit_surface_jobs',deadline=deadline)
            evidence.setdefault('edit_surface',{})[label] = result
        except (InspectionFailure, MissingEvidence, OSError, ValueError) as error:
            failure = error if isinstance(error, InspectionFailure) else InspectionFailure(
                'not_measurable','EDIT_SURFACE_UNAVAILABLE',str(error))
            record_failure(spec,evidence,[path],failure)
