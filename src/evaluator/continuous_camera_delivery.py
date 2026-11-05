"""Measure the public second-camera translation in physical world units."""
import math
import numpy as np
from .continuous_scene_preservation import CAMERA_FIELDS,deviation,semantic


def measure(scene,views,*,translation_m=.30,tolerance_m=.003):
    names={k:views[k]['camera'] for k in ('main.png','alternate.png')}
    objects={o['object']:o for o in scene['objects'] if o['type']=='CAMERA'}
    if any(name not in objects for name in names.values()) or len(set(names.values()))!=2:
        return {'score':0.,'reason':'Two distinct rendered cameras required','cameras':names}
    main,alternate=[objects[names[k]] for k in ('main.png','alternate.png')]
    a,b=np.asarray(main['matrix_world'],float),np.asarray(alternate['matrix_world'],float)
    def axes(matrix):
        scale=np.linalg.norm(matrix[:3,:3],axis=0)
        if np.any(scale==0):raise ValueError('Degenerate saved camera transform')
        return matrix[:3,:3]/scale
    first,second=axes(a),axes(b)
    displacement=(b[:3,3]-a[:3,3])*scene['unit_scale']
    target=first[:,0]*translation_m;error=float(np.linalg.norm(displacement-target))
    translation=2.**(-max(error-tolerance_m,0)/tolerance_m)
    rotation=float(np.max(np.arccos(np.clip(np.sum(first*second,axis=0),-1,1))))
    rotation_q=2.**(-max(rotation-1e-6,0)/math.radians(1))
    def projection(o):return {'projection':{k:o.get('settings',{}).get(k) for k in CAMERA_FIELDS},
                              'dof':semantic(o.get('dof'))}
    optical=deviation(projection(main),projection(alternate))
    return {'score':min(translation,rotation_q,optical['score']),'cameras':names,
        'actual_world_displacement_m':displacement.tolist(),'required_world_displacement_m':target.tolist(),
        'displacement_error_m':error,'translation_score':translation,'tolerance_m':tolerance_m,
        'rotation_error_radians':rotation,'rotation_score':rotation_q,'projection':optical,
        'policy':'0.30 m along normalized local positive X; camera object scale does not multiply physical distance'}
