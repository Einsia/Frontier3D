"""Measured camera and allowed-edit checks for the case-owned L2 protocol."""
import math
import numpy as np

from .metrics import _register, MissingEvidence, resolve


@_register('l2_case_camera_pair','mode','delta_m degrees tolerance alternate')
def camera_pair(check,evidence,spec):
    cameras=resolve(evidence,'/scene/cameras')
    a,b=cameras.get('__main'),cameras.get(check.params.get('alternate','__alternate'))
    if not a or not b:raise MissingEvidence('Both pixel-matched saved cameras are required')
    p=check.params;mode=p['mode'];tol=p.get('tolerance',.003)
    same_projection=a['type']==b['type'] and abs(a['lens']-b['lens'])<1e-5 and abs(a['ortho_scale']-b['ortho_scale'])<1e-5
    ar,br=np.asarray(a['basis_z']),np.asarray(b['basis_z'])
    delta=np.asarray(b['location'])-a['location']
    if mode=='local_translation':
        expected=np.asarray(a['basis_x'])*p['delta_m']
        error=float(np.linalg.norm(delta-expected))
        rotation=max(float(np.linalg.norm(np.asarray(a[k])-b[k])) for k in ('basis_x','basis_y','basis_z'))
        passed=error<=tol and rotation<1e-5 and same_projection
        return float(passed),{'local_translation_error_m':error,'basis_error':rotation,'projection_preserved':same_projection}
    if mode=='distance':
        distance=float(np.linalg.norm(delta))
        return float(abs(distance-p['delta_m'])<=tol),{'camera_distance_m':distance}
    horizontal=np.linalg.norm(ar[:2])*np.linalg.norm(br[:2])
    if horizontal<=1e-9:raise MissingEvidence('Vertical camera has undefined azimuth')
    angle=math.degrees(math.acos(float(np.clip(np.dot(ar[:2],br[:2])/horizontal,-1,1))))
    if mode=='different_azimuth':
        return float(angle>1e-4),{'azimuth_degrees':angle}
    if mode!='orbit':raise ValueError('Unsupported camera relationship')
    distances=np.linalg.lstsq(np.column_stack((ar,-br)),delta,rcond=None)[0]
    center_a=np.asarray(a['location'])+distances[0]*ar
    center_b=np.asarray(b['location'])+distances[1]*br
    intersection=float(np.linalg.norm(center_a-center_b))
    radius_error=abs(abs(float(distances[0]))-abs(float(distances[1])))
    radius=max(abs(float(distances[0])),1e-6)
    passed=(abs(angle-p['degrees'])<=p.get('tolerance',.25) and same_projection
        and abs(float(delta[2]))<=radius*.01 and intersection<=radius*.01
        and radius_error<=radius*.01 and all(distances<0))
    return float(passed),{'azimuth_degrees':angle,'focus_ray_separation_m':intersection,
        'view_distance_error_m':radius_error,'height_difference_m':float(delta[2]),'projection_preserved':same_projection}
