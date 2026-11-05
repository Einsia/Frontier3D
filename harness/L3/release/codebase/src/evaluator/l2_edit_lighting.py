"""Lighting restoration from bound initial/reference/candidate main renders.

Reports spatial bins of color and luminance improvement without demanding exact
private light values. Geometry/material preservation is enforced separately.
"""
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
from skimage.color import rgb2lab


def load(item):
    path=Path(item['path'])
    with path.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=item['sha256']:raise ValueError('Lighting image hash changed')
    with Image.open(path) as image:
        return np.asarray(image.convert('RGB'),float)/255.


def lighting_improvement(evidence,min_improvement=.5):
    items=[evidence.get('edit_initial_image'),evidence.get('reference_images',{}).get('main'),
           evidence.get('artifacts',{}).get('main.png')]
    if not all(items):return {'status':'not_measurable','passed':False,'score':0.,'reason':'Initial, reference and candidate main views required'}
    initial,reference,candidate=[load(item) for item in items]
    if initial.shape!=reference.shape or candidate.shape!=reference.shape:
        return {'status':'not_measurable','passed':False,'score':0.,'reason':'Native image sizes must match'}
    labs=[rgb2lab(gaussian_filter(x,(3,3,0))) for x in (initial,reference,candidate)]
    rows=[]
    for yi,ys in enumerate(np.array_split(np.arange(reference.shape[0]),4)):
        for xi,xs in enumerate(np.array_split(np.arange(reference.shape[1]),4)):
            before,goal,after=[v[ys[0]:ys[-1]+1,xs[0]:xs[-1]+1] for v in labs]
            baseline=float(np.linalg.norm(before-goal,axis=2).mean())
            error=float(np.linalg.norm(after-goal,axis=2).mean())
            # Select from initial/reference only; candidate cannot redefine ROI.
            if baseline<2.:continue
            improvement=1-error/baseline
            rows.append({'grid':[yi,xi],'initial_delta_e':baseline,'candidate_delta_e':error,
                'relative_improvement':improvement,'initial_luminance':float(before[:,:,0].mean()),
                'reference_luminance':float(goal[:,:,0].mean()),'candidate_luminance':float(after[:,:,0].mean())})
    if not rows:return {'status':'not_measurable','passed':False,'score':0.,'reason':'Initial/reference lighting change too small to establish restoration'}
    values=np.array([r['relative_improvement'] for r in rows])
    average=float(np.mean(values));improved_fraction=float(np.mean(values>=.25))
    return {'status':'measured','passed':average>=min_improvement and improved_fraction>=.75,
        'score':float(np.clip(average,0,1)),'mean_relative_improvement':average,'improved_region_fraction':improved_fraction,
        'regions':rows,'minimum_improvement':min_improvement,'threshold_status':'pilot_not_calibrated',
        'scope':'Fixed image bins selected from initial-reference changes, not semantic masks; private light intensities are not hard targets'}
