"""Saved-render image measurements; called inside the bounded scoring worker.

Scores are explicitly uncalibrated appearance measurements, not material or
semantic ground truth. Foreground comes from real geometry, not colour keys.
"""
import hashlib
import io
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
from skimage.color import rgb2lab
from skimage.metrics import structural_similarity

PROTOCOL = 'l1-foreground-appearance-v1'
RENDER_PROTOCOL = 'l1-saved-camera-v1'
DECLARED_PROTOCOL = 'l1-declared-camera-v1'


def validate_parameters(check, spec):
    from .spec import relative_path
    params = check.params
    view = next((v for v in spec.render_views if v['id'] == params['view']), {})
    if spec.profile != 'L1' or spec.mode != 'reference' or view.get('camera_source') not in {'saved', 'declared'}:
        raise ValueError('Native image metrics require an L1 image saved/declared-camera beauty view')
    motion_primary = (spec.to_dict().get('l1_image_quality', {}).get('version') == 'l1-reference-visual-v2.0.0'
        and any(c.metric == 'procedural_material_sequence' and c.applicable
                and c.params['frames'] == [1, 31, 61, 91, 121, 1]
                for group in spec.checks.values() for c in group))
    if type(view.get('frame')) is not int or view['frame'] != 1 and not (motion_primary and view['frame'] == 61):
        raise ValueError('Primary appearance requires frame 1, or frame 61 for declared visual v2 hinge states')
    if check.metric == 'main_render_consistency':
        if view['camera_source'] != 'saved':
            raise ValueError('Submitted PNG consistency must use the submitted saved camera')
        if params['artifact'] not in spec.required_artifacts:
            raise ValueError('Image consistency must bind a declared artifact')
        for name in ('mean_tolerance', 'p99_tolerance'):
            value = params[name]
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < .1:
                raise ValueError('Image consistency tolerances must be finite in (0, .1)')
        return
    if params['view'] not in spec.reference_images:
        raise ValueError('Native image comparison requires a public reference image')
    relative_path(params['mask_asset'])
    if not isinstance(params['mask_sha256'], str) or re.fullmatch('[0-9a-f]{64}', params['mask_sha256']) is None:
        raise ValueError('Reference mask requires a SHA256 binding')
    if not isinstance(params['reference_sha256'], str) or re.fullmatch('[0-9a-f]{64}', params['reference_sha256']) is None:
        raise ValueError('Reference image requires a SHA256 binding paired with its mask')
    if check.id in spec.critical_constraints:
        raise ValueError('Continuous image quality cannot act as a binary task-completion gate')
    if check.pass_threshold != 0:
        raise ValueError('Uncalibrated image quality has no task-completion threshold; use zero')
    regions = params['regions']
    if not isinstance(regions, dict) or not 1 <= len(regions) <= 32:
        raise ValueError('Image comparison needs explicit bounded reference regions')
    for name, boxes in regions.items():
        if not isinstance(name, str) or not name or not isinstance(boxes, list) or not 1 <= len(boxes) <= 16:
            raise ValueError('Invalid reference region')
        for box in boxes:
            if (not isinstance(box, list) or len(box) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in box)
                    or not box[0] < box[2] or not box[1] < box[3]):
                raise ValueError('Reference regions use normalized [left, top, right, bottom] boxes')


def read_bound_image(path, sha256):
    from .metrics import MissingEvidence
    # Decode exactly the bytes whose digest is compared, avoiding hash/open races.
    blob = Path(path).read_bytes()
    if hashlib.sha256(blob).hexdigest() != sha256:
        raise MissingEvidence('Image content changed after evaluator capture')
    with Image.open(io.BytesIO(blob)) as image:
        if image.width * image.height > 4096**2:
            raise MissingEvidence('Image exceeds the declared measurement capacity')
        return np.asarray(image.convert('RGBA'), dtype=np.uint8)


def saved_image(evidence, view, scene_name, *, frame, camera_source='saved', definition=None):
    from .metrics import MissingEvidence, resolve
    item = resolve(evidence, '/views/' + view)
    protocol = RENDER_PROTOCOL if camera_source == 'saved' else DECLARED_PROTOCOL
    if (not isinstance(item, dict) or item.get('render_protocol') != protocol
            or item.get('camera_source') != camera_source
            or item.get('source_sha256') != evidence.get('artifacts', {}).get(scene_name, {}).get('sha256')
            or not item.get('source_sha256') or not item.get('inspector_execution')
            or type(item.get('frame')) is not int or item['frame'] != frame
            or any(not item.get(k) for k in ('image', 'image_sha256', 'mask', 'mask_sha256'))):
        raise MissingEvidence('Missing saved-render protocol or source/inspection binding')
    if camera_source == 'declared' and item.get('camera_definition') != definition:
        raise MissingEvidence('Declared camera does not match the frozen view definition')
    return item, read_bound_image(item['image'], item['image_sha256'])


def consistency(check, evidence, spec):
    from .metrics import MissingEvidence, resolve
    params = check.params
    frame = next(v['frame'] for v in spec.render_views if v['id'] == params['view'])
    render, left = saved_image(evidence, params['view'], spec.scene, frame=frame)
    artifact = resolve(evidence, '/artifacts/' + params['artifact'].replace('~', '~0').replace('/', '~1'))
    if not artifact.get('sha256') or not artifact.get('validation_io', {}).get('path'):
        raise MissingEvidence('Missing submitted PNG capture')
    right = read_bound_image(artifact['validation_io']['path'], artifact['sha256'])
    if left.shape != right.shape:
        return 0., {'protocol': RENDER_PROTOCOL, 'passed': False, 'reason': 'Native pixel sizes differ',
                    'render_size': list(left.shape[:2]), 'submission_size': list(right.shape[:2])}
    if left.size == 0:
        raise MissingEvidence('Empty saved render')
    error = np.abs(left.astype(float) - right.astype(float)) / 255
    mean_error = float(np.mean(error))
    p99_error = float(np.quantile(error, .99))
    passed = mean_error <= params['mean_tolerance'] and p99_error <= params['p99_tolerance']
    return float(passed), {
        'protocol': RENDER_PROTOCOL, 'passed': passed, 'mean_rgba_error': mean_error,
        'p99_rgba_error': p99_error, 'mean_tolerance': params['mean_tolerance'],
        'p99_tolerance': params['p99_tolerance'], 'max_rgba_error': float(error.max()),
        'source_sha256': render['source_sha256'], 'calibration_status': 'pilot_not_calibrated',
        'measured_frame': frame,
    }


def appearance_arrays(candidate, reference, candidate_mask, reference_mask, regions):
    """No resizing, best-view search, background-colour mask or fitted alignment."""
    if (candidate.shape != reference.shape or candidate.shape[:2] != candidate_mask.shape
            or reference_mask.shape != candidate_mask.shape or min(candidate_mask.shape) < 16):
        raise ValueError('Images and masks must use the same native pixel grid')
    if not reference_mask.any():
        raise ValueError('Reference mask is empty')
    left, right = candidate[..., :3].astype(float) / 255, reference[..., :3].astype(float) / 255
    # Composite transparent pixels over neutral white; never reward hidden RGB.
    for pixels, source in ((left, candidate), (right, reference)):
        alpha = source[..., 3:4].astype(float) / 255
        pixels[:] = pixels * alpha + (1-alpha)
    ssim_maps = []
    for sigma in (0, 2, 6):
        a = gaussian_filter(left, (sigma, sigma, 0)) if sigma else left
        b = gaussian_filter(right, (sigma, sigma, 0)) if sigma else right
        _, values = structural_similarity(a, b, channel_axis=2, data_range=1., full=True)
        ssim_maps.append(values.mean(axis=2))
    structure = np.mean(ssim_maps, axis=0)
    lab_left, lab_right = rgb2lab(left), rgb2lab(right)
    colour = np.linalg.norm(lab_left - lab_right, axis=2)
    lightness = np.abs(lab_left[..., 0] - lab_right[..., 0])
    intersection = int(np.count_nonzero(candidate_mask & reference_mask))
    union = int(np.count_nonzero(candidate_mask | reference_mask))
    iou = intersection / union if union else 0.
    height, width = reference_mask.shape
    measurements = {}
    for name, boxes in regions.items():
        selected = np.zeros_like(reference_mask)
        for x0, y0, x1, y1 in boxes:
            selected[int(y0*height):math.ceil(y1*height), int(x0*width):math.ceil(x1*width)] = True
        selected &= reference_mask
        count = int(selected.sum())
        if not count:
            raise ValueError('Reference region has no visible geometry: ' + name)
        ssim = float(np.clip(structure[selected].mean(), 0, 1))
        delta = float(colour[selected].mean())
        tone = float(lightness[selected].mean())
        # Broad appearance, not a claim to distinguish material from lighting.
        colour_score = math.exp(-delta/25)
        tone_score = math.exp(-tone/20)
        coverage = float(candidate_mask[selected].mean())
        score = coverage * (.5*ssim + .3*colour_score + .2*tone_score)
        measurements[name] = {'foreground_pixels': count, 'structure_ssim': ssim,
                              'delta_e76_mean': delta, 'lightness_error_mean': tone,
                              'colour_score': colour_score, 'tone_score': tone_score,
                              'geometry_coverage': coverage, 'score': score}
    macro = float(np.mean([r['score'] for r in measurements.values()]))
    return {
        'protocol': PROTOCOL, 'score': iou * macro, 'silhouette_iou': iou,
        'region_macro': macro, 'regions': measurements,
        'reference_foreground_pixels': int(reference_mask.sum()),
        'candidate_foreground_pixels': int(candidate_mask.sum()),
        'formula': 'geometry_silhouette_iou * equal_region_mean(coverage * (.5*SSIM + .3*colour + .2*tone))',
        'alignment': 'Same native pixels; no resize, fitted transform or hidden-view reference',
        'region_scope': 'Evaluator-authored 2D ROI boxes intersected with GT geometry; not semantic segmentation',
        'calibration_status': 'pilot_not_calibrated',
        'pass_semantics': 'Measurement available, not image-quality or task completion; score is continuous',
        'scope': 'Visible projection and appearance; not thickness, hidden geometry or semantic completion',
    }


def image_pair(check, evidence, spec):
    from .metrics import MissingEvidence, resolve
    params = check.params
    view = next(v for v in spec.render_views if v['id'] == params['view'])
    frame = view['frame']
    definition = {key: view[key] for key in ('location', 'target', 'ortho_scale')} if view['camera_source'] == 'declared' else None
    native, candidate = saved_image(evidence, params['view'], spec.scene, frame=frame,
                                    camera_source=view['camera_source'], definition=definition)
    reference = resolve(evidence, '/reference_images/' + params['view'])
    ref_mask = resolve(evidence, '/image_reference_masks/' + params['view'])
    if ref_mask.get('sha256') != params['mask_sha256']:
        raise MissingEvidence('Reference mask does not match the versioned specification')
    if reference.get('sha256') != params['reference_sha256']:
        raise MissingEvidence('Reference image no longer matches its geometry mask')
    truth = read_bound_image(reference['path'], reference['sha256'])
    actual_mask = read_bound_image(native['mask'], native['mask_sha256'])[..., 3] >= 128
    expected_mask = read_bound_image(ref_mask['path'], ref_mask['sha256'])[..., 3] >= 128
    if 'l1_image_quality' in spec.to_dict():
        from .l2_reference_image import appearance_components
        def rgb(pixels):
            rgba = pixels.astype(float) / 255.
            return rgba[..., :3] * rgba[..., 3:4] + 1 - rgba[..., 3:4]
        result = appearance_components(rgb(candidate), rgb(truth))
    else:
        result = appearance_arrays(candidate, truth, actual_mask, expected_mask, params['regions'])
    result['measured_frame'] = frame
    result['camera_source'] = view['camera_source']
    result['hashes'] = {'scene': native['source_sha256'], 'render': native['image_sha256'],
                        'candidate_mask': native['mask_sha256'], 'reference': reference['sha256'],
                        'reference_mask': ref_mask['sha256']}
    return result['score'], result


def collect_reference_masks(spec, evidence, assets_root, output, *, deadline):
    from .l1_failures import InspectionFailure, record_failure
    from .l1_file_io import run_file_io
    from .spec import contained_path
    for group in spec.checks.values():
        for check in group:
            if not check.applicable or check.metric != 'native_image_pair':
                continue
            params = check.params
            scope = '/image_reference_masks/' + params['view']
            try:
                source = contained_path(assets_root, params['mask_asset'])
                result = run_file_io('stage_image', {
                    'path': str(source), 'target': str(output / 'reference_masks' / (params['view'] + '.png')),
                }, output=output / 'file_io', deadline=deadline)
                if result['sha256'] != params['mask_sha256']:
                    raise ValueError('Reference mask changed from the frozen case specification')
                evidence.setdefault('image_reference_masks', {})[params['view']] = result
            except (OSError, ValueError, InspectionFailure) as error:
                failure = error if isinstance(error, InspectionFailure) else InspectionFailure(
                    'infrastructure_error', 'REFERENCE_MASK_UNAVAILABLE', str(error))
                record_failure(spec, evidence, [scope], failure)
