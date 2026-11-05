"""Reference-owned, fixed-pixel regional appearance. No candidate annotations.

This is an interpretable appearance proxy, not an object detector. Regions and
weights must be frozen before a scored generation campaign.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt, gaussian_filter
from skimage.color import rgb2gray, rgb2lab
from skimage.feature import canny
from skimage.metrics import structural_similarity

from .l2_reference_image import appearance_components

METHOD = 'reference-regions-v1'
PROFILE = 'l2-reference-embodied-v4.0.0'


def validate_annotation(annotation):
    if annotation.get('version') != METHOD:
        raise ValueError('Unknown reference region annotation version')
    regions = annotation.get('regions', [])
    if not regions or len({r['id'] for r in regions}) != len(regions):
        raise ValueError('Distinct reference regions required')
    if not np.isclose(sum(r['weight'] for r in regions), 1., atol=1e-9):
        raise ValueError('Reference region weights must sum to one')
    for region in regions:
        points = np.asarray(region['polygon'], float)
        if (points.ndim != 2 or points.shape[1] != 2 or len(points) < 3
                or not np.isfinite(points).all() or np.any((points < 0) | (points > 1))
                or not np.isfinite(region['weight']) or not 0 < region['weight'] <= 1):
            raise ValueError('Invalid normalized reference polygon/weight')


def load_annotation(root, binding):
    if set(binding) != {'path', 'sha256'} or binding['path'] != 'harness/reference_regions.json':
        raise ValueError('Unexpected reference annotation binding')
    path = Path(root)/binding['path']
    if path.is_symlink():
        raise ValueError('Reference annotation cannot be a symlink')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != binding['sha256']:
        raise ValueError('Reference annotation hash changed')
    annotation = json.loads(raw)
    validate_annotation(annotation)
    ref = Path(root)/annotation['reference_path']
    if not ref.resolve().is_relative_to((Path(root)/'environment/input').resolve()):
        raise ValueError('Reference image must be task input')
    if hashlib.sha256(ref.read_bytes()).hexdigest() != annotation['reference_sha256']:
        raise ValueError('Annotated reference image hash changed')
    return annotation


def region_mask(region, shape):
    height, width = shape[:2]
    canvas = Image.new('1', (width, height))
    ImageDraw.Draw(canvas).polygon([(round(x*(width-1)), round(y*(height-1)))
                                   for x, y in region['polygon']], fill=1)
    return np.asarray(canvas, dtype=bool)


def regional_components(a, b, annotation):
    validate_annotation(annotation)
    global_score = appearance_components(a, b)
    gray_a, gray_b = rgb2gray(a), rgb2gray(b)
    edges = [canny(x, sigma=2., low_threshold=.05, high_threshold=.15) for x in (gray_a, gray_b)]
    lab_a, lab_b = rgb2lab(a), rgb2lab(b)
    ssim_maps = []
    for sigma in (0., 2., 6.):
        left, right = [gaussian_filter(x, (sigma, sigma, 0)) if sigma else x for x in (a, b)]
        _, similarity = structural_similarity(left, right, data_range=1., channel_axis=2, full=True)
        ssim_maps.append(similarity.mean(axis=2))
    # Fixed tolerance admits small detail displacement, not arbitrary alignment.
    radius = max(2., .01*float(np.hypot(*a.shape[:2])))
    rows = []
    for region in annotation['regions']:
        mask = region_mask(region, a.shape)
        if mask.sum() < 49:
            raise ValueError('Reference region too small at native resolution')
        ea, eb = [edge & mask for edge in edges]
        na, nb = int(ea.sum()), int(eb.sum())
        # Distances stay inside the same reference region: outside edges cannot
        # impersonate a missing subject. Blank/blank never earns edge credit.
        recall = float(np.mean(distance_transform_edt(~eb)[ea] <= radius)) if na and nb else 0.
        precision = float(np.mean(distance_transform_edt(~ea)[eb] <= radius)) if na and nb else 0.
        edge_f1 = 2*precision*recall/(precision+recall) if precision+recall else 0.
        structure = float(np.clip(np.mean([s[mask].mean() for s in ssim_maps]), 0., 1.))
        color = float(np.exp(-np.linalg.norm(lab_a[mask].mean(0)-lab_b[mask].mean(0))/25.))
        # Color and empty-background SSIM do not rescue a region with no detail.
        # Reference-only thresholds; excess edges also reduce the multiplier.
        detail = min(na, nb)/max(na, nb) if na else 0.
        std_a, std_b = float(gray_a[mask].std()), float(gray_b[mask].std())
        contrast = min(std_a, std_b)/max(std_a, std_b) if max(std_a, std_b) > 1e-8 else 0.
        evidence = float(np.sqrt(detail*contrast))
        value = (.5*structure+.3*edge_f1+.2*color)*evidence
        rows.append({'id': region['id'], 'label': region['label'], 'weight': region['weight'],
                     'score': value, 'structure': structure, 'color': color, 'edge_f1': edge_f1,
                     'detail_ratio': detail, 'contrast_ratio': contrast, 'evidence_multiplier': evidence,
                     'reference_edge_pixels': na, 'candidate_edge_pixels': nb, 'pixels': int(mask.sum())})
    subjects = sum(row['weight']*row['score'] for row in rows)
    return {'method': METHOD, 'score': .9*subjects+.1*global_score['score'],
            'subject_score': subjects, 'global_score': global_score['score'], 'regions': rows,
            'weights': {'reference_regions': .9, 'whole_image': .1},
            'ssim_scales': global_score['ssim_scales'], 'edge_tolerance_pixels': radius,
            'calibration_status': 'pilot_reference_reviewed_not_perceptually_calibrated',
            'scope': 'Fixed reference subject regions; appearance evidence, not semantic recognition',
            'alignment': 'Native pixel grid; no candidate-fitted alignment or mask'}
