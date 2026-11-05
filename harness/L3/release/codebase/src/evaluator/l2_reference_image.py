"""Deterministic main-view appearance components without candidate-fitted alignment."""
import numpy as np
from scipy.ndimage import gaussian_filter, distance_transform_edt
from skimage.color import rgb2lab, rgb2gray
from skimage.feature import canny
from skimage.metrics import structural_similarity

METHOD='native-appearance-v1'


def appearance_components(a,b):
    if a.shape!=b.shape or a.ndim!=3 or a.shape[2]!=3 or min(a.shape[:2])<7:
        raise ValueError('Identical native RGB pixel grids required')
    if not np.isfinite(a).all() or not np.isfinite(b).all():raise ValueError('Non-finite image pixels')
    # Fixed smoothing reduces penalties for fine texture/lettering that the
    # task allows simplifying. No transform is optimized against a candidate.
    ssim=[]
    for sigma in (0.,2.,6.):
        left=gaussian_filter(a,(sigma,sigma,0)) if sigma else a
        right=gaussian_filter(b,(sigma,sigma,0)) if sigma else b
        ssim.append(float(structural_similarity(left,right,data_range=1.,channel_axis=2)))
    structure=float(np.clip(np.mean(ssim),0,1))
    labs=[rgb2lab(x) for x in (a,b)];tile_errors=[];tone_errors=[]
    for ys in np.array_split(np.arange(a.shape[0]),4):
        for xs in np.array_split(np.arange(a.shape[1]),4):
            left,right=[v[ys[0]:ys[-1]+1,xs[0]:xs[-1]+1].mean(axis=(0,1)) for v in labs]
            tile_errors.append(float(np.linalg.norm(left-right)))
            tone_errors.append(float(abs(left[0]-right[0])))
    mean_delta=float(np.mean(tile_errors));color=float(np.exp(-mean_delta/25.))
    mean_tone=float(np.mean(tone_errors));tone=float(np.exp(-mean_tone/20.))
    edge_a,edge_b=[canny(rgb2gray(x),sigma=2.,low_threshold=.05,high_threshold=.15) for x in (a,b)]
    diagonal=float(np.hypot(*a.shape[:2]))
    if not edge_a.any() and not edge_b.any():edge_error=0.;edge_score=1.
    elif not edge_a.any() or not edge_b.any():edge_error=None;edge_score=0.
    else:
        edge_error=float((distance_transform_edt(~edge_b)[edge_a].mean()+distance_transform_edt(~edge_a)[edge_b].mean())/(2*diagonal))
        edge_score=float(np.exp(-edge_error/.02))
    score=.45*structure+.25*color+.15*tone+.15*edge_score
    return {'method':METHOD,'score':score,'structure_ssim_mean':structure,'ssim_scales':ssim,
        'region_color_score':color,'mean_tile_delta_e76':mean_delta,
        'region_tone_score':tone,'mean_tile_lightness_error':mean_tone,
        'edge_score':edge_score,'symmetric_edge_distance_fraction':edge_error,
        'weights':{'structure':.45,'region_color':.25,'region_tone':.15,'edges':.15},
        'calibration_status':'pilot_not_calibrated',
        'regions':'Fixed 4x4 image grid, not semantic masks',
        'alignment':'Native grid; fixed smoothing only; no resize, homography or candidate-fitted registration',
        'scope':'Appearance diagnostics; color/tone do not uniquely separate material from illumination, edges are not semantic silhouettes'}
