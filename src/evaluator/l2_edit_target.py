"""Visible target geometry comparison without candidate naming requirements."""
import numpy as np


def compare_visible_target(candidate,baseline,reference,reference_targets,tolerance=.03):
    before=baseline['scene']['objects']
    a=candidate['scene'].get('visible_surface',{});b=reference['scene'].get('visible_surface',{})
    if a.get('status')!='measured' or b.get('status')!='measured' or a.get('size')!=b.get('size'):
        return {'status':'not_measurable','passed':False,'score':0.,'reason':'Matching visible surface samples required'}
    # All reference naming remains private; candidates can use any object names.
    expected=np.array([n in reference_targets for n in b['object_names']],bool)
    actual=np.array([n is not None and n not in before for n in a['object_names']],bool)
    if expected.sum()<8:
        return {'status':'not_measurable','passed':False,'score':0.,'reason':'Reference target has too few visible samples'}
    overlap=expected & actual;union=expected | actual
    iou=float(overlap.sum()/union.sum()) if union.any() else 0.
    reference_points=np.asarray([p for p,k in zip(b['world_points_m'],expected) if k],float)
    diagonal=float(np.linalg.norm(np.ptp(reference_points,axis=0)))
    distances=np.array([np.linalg.norm(np.array(p)-q) for p,q,k in zip(a['world_points_m'],b['world_points_m'],overlap) if k])
    relative=distances/max(diagonal,1e-9)
    coverage=float((relative<=tolerance).sum()/expected.sum())
    return {'status':'measured','passed':iou>=.8 and coverage>=.8,'score':.5*iou+.5*coverage,
        'target_silhouette_iou':iou,'visible_surface_coverage':coverage,'reference_samples':int(expected.sum()),
        'candidate_samples':int(actual.sum()),'relative_surface_error_p95':float(np.quantile(relative,.95)) if len(relative) else None,
        'tolerance_fraction':tolerance,'reference_visible_diagonal_m':diagonal,
        'threshold_status':'pilot_not_calibrated','candidate_names_used_as_answers':False,
        'scope':'Visible silhouette and depth surface only; cavities, supports and invisible geometry need separate probes'}
