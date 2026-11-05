"""Fixed-budget global camera fitting and visible-building image measurements.

Camera fitting uses only reference rectangles and exported 3D bounds. RGB is
held out from fitting. No object transform, per-object rotation, image warp or
candidate-dependent reference selection is allowed. Scores are 2D proxies.
"""
import itertools
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.optimize import differential_evolution, linear_sum_assignment
from skimage.metrics import structural_similarity

from .protocol import BUILDINGS, digest, read_json, write_json, reference_plan
from .reference import rendered_mask_color
from src.evaluator.l2_reference_boxes import pair_metrics
from src.evaluator.l2_reference_image import appearance_components

VERSION = 'l3-global-camera-visible-crops-v1'


def world_bounds(export):
    groups = {}
    for item in export['instances']:
        if not item.get('visible', True):
            continue
        v = np.asarray(export['meshes'][item['mesh']]['vertices_cm'], float)
        a = np.asarray([item['axis_x'], item['axis_y'], item['axis_z']])
        world = v @ a + item['origin_cm']
        groups.setdefault(item['actor'], []).append([world.min(0), world.max(0)])
    result = {}
    for name, parts in groups.items():
        a = np.asarray(parts)
        result[name] = np.asarray([a[:, 0].min(0), a[:, 1].max(0)])
    return result


def building_corners(export):
    bounds = world_bounds(export)
    out = {}
    for name in BUILDINGS:
        if name not in bounds:
            continue
        alias = name.removeprefix('building.') + '.'
        parts = [b for k, b in bounds.items() if k == name or k.startswith(alias)]
        b = np.asarray(parts)
        lo, hi = b[:, 0].min(0), b[:, 1].max(0)
        out[name] = np.asarray(list(itertools.product(*zip(lo, hi))))
    return out


def reference_boxes(annotation):
    rows = []
    for obj in annotation['objects']:
        if obj['class'] != 'building':
            continue
        p = np.asarray(obj['polygon'])
        rows.append(dict(id=obj['id'], box=[*p.min(0), *p.max(0)]))
    if not rows:
        raise ValueError('No fixed reference building population')
    return rows


def project(corners, camera, aspect=2560/1440):
    position, target = np.asarray(camera['position_cm']), np.asarray(camera['look_cm'])
    f = target-position
    f /= np.linalg.norm(f)
    right = np.cross([0., 0., 1.], f)
    right /= np.linalg.norm(right)
    up = np.cross(f, right)
    p = corners-position
    depth = p@f
    if np.any(depth <= 1):
        return None
    scale = math.tan(math.radians(camera['horizontal_fov_deg'])/2)
    xy = np.column_stack((.5+(p@right)/depth/(2*scale), .5-(p@up)/depth/(2*scale)*aspect))
    return np.r_[xy.min(0), xy.max(0)]


def fit_camera(export, annotation, bindings):
    groups = building_corners(export)
    if len(groups) < 3:
        return {'status': 'insufficient_visible_geometry', 'camera': None}
    refs = reference_boxes(annotation)
    rb = np.asarray([r['box'] for r in refs]); rc = (rb[:, :2]+rb[:, 2:])/2
    rs = rb[:, 2:]-rb[:, :2]
    allpoints = np.concatenate(list(groups.values()))
    center = (allpoints.min(0)+allpoints.max(0))/2
    span = max(np.ptp(allpoints[:, 0]), np.ptp(allpoints[:, 1]), 500.)
    target_z = float(np.median(allpoints[:, 2]))

    def decode(x):
        az, el, dist, tx, ty = x
        az, el = np.radians([az, el]); dist = span*math.exp(dist)
        target = np.array([center[0]+tx*span, center[1]+ty*span, target_z])
        position = target+dist*np.array([math.cos(el)*math.cos(az), math.cos(el)*math.sin(az), math.sin(el)])
        return {'position_cm': position.tolist(), 'look_cm': target.tolist(), 'horizontal_fov_deg': 60.}

    def objective(x):
        cam = decode(x)
        boxes = [project(g, cam) for g in groups.values()]
        if any(b is None for b in boxes):
            return 1000.
        cb = np.asarray(boxes); cc = (cb[:, :2]+cb[:, 2:])/2; cs = cb[:, 2:]-cb[:, :2]
        cost = np.sum((rc[:, None]-cc[None])**2, axis=2)
        cost += .004*np.sum(np.log(np.maximum(cs[None], 1e-5)/rs[:, None])**2, axis=2)
        rows, cols = linear_sum_assignment(cost)
        return float(cost[rows, cols].mean())

    result = differential_evolution(objective, [(0, 360), (15, 80), (math.log(.8), math.log(10)), (-1, 1), (-1, 1)],
                                    seed=42, popsize=12, maxiter=80, polish=True, workers=1)
    camera = decode(result.x)
    candidate_bindings = {**bindings, 'views': {**bindings['views'], 'overview': camera}}
    plan = reference_plan(candidate_bindings)
    return {'status': 'fitted', 'method': VERSION, 'camera': camera, 'plan': plan,
            'objective': float(result.fun), 'objective_evaluations': int(result.nfev),
            'fit_inputs': 'reference building boxes and candidate 3D bounds; no RGB or VLM score',
            'search': {'seed': 42, 'population_multiplier': 12, 'iterations': 80, 'fov_deg': 60},
            'limitations': ['Reference rectangle annotations await independent human validation.',
                           'Global camera is a fitted nuisance variable; submitted camera is reported separately.',
                           'Bounds-based fitting does not establish semantic correspondence or hidden geometry.']}


def mask_boxes(mask_path, groups):
    pixels = np.asarray(Image.open(mask_path).convert('RGB')).astype(np.int16)
    h, w = pixels.shape[:2]; rows = []; known = np.max(pixels, axis=2) <= 3
    for group in groups:
        color = rendered_mask_color(group['rgb'], 'ue_srgb_linear_display_gamma_2_2')
        mask = np.max(np.abs(pixels-color), axis=2) <= 3
        known |= mask
        y, x = np.nonzero(mask)
        if len(x):
            rows.append({'id': group['id'], 'box': [x.min()/w, y.min()/h, (x.max()+1)/w, (y.max()+1)/h],
                         'visible_pixels': len(x)})
    if np.count_nonzero(~known)/max(1, np.count_nonzero(np.max(pixels, axis=2)>3)) > .01:
        raise ValueError('Invalid instance mask palette; do not score missing instances')
    return rows


def crop(image, box, size=192):
    w, h = image.size
    x0, y0, x1, y1 = np.clip(box, 0, 1)*[w, h, w, h]
    if x1-x0 < 3 or y1-y0 < 3:
        raise ValueError('Crop too small to measure')
    patch = image.crop((int(x0), int(y0), int(math.ceil(x1)), int(math.ceil(y1))))
    patch.thumbnail((size, size), Image.Resampling.LANCZOS)
    result = Image.new('RGB', (size, size), (127, 127, 127))
    result.paste(patch, ((size-patch.width)//2, (size-patch.height)//2))
    return result


def compare(reference, rgb, mask, annotations, groups, output):
    output.mkdir(parents=True, exist_ok=False)
    ann = read_json(annotations)
    if digest(reference) != ann['reference_sha256']:
        raise ValueError('Changed reference image')
    left, right = Image.open(reference).convert('RGB'), Image.open(rgb).convert('RGB')
    if left.size != right.size:
        raise ValueError('Whole-scene comparisons require equal native grids')
    refs, candidates = reference_boxes(ann), mask_boxes(mask, groups)
    matrix = np.array([[pair_metrics(r['box'], c['box'], left.size)['score'] for c in candidates] for r in refs])
    matches = {}
    if candidates:
        ri, ci = linear_sum_assignment(-matrix)
        matches = {int(i): int(j) for i, j in zip(ri, ci) if matrix[i,j] > 0}
    rows=[]; sheet=Image.new('RGB',(192*2,218*len(refs)),(24,24,24)); draw=ImageDraw.Draw(sheet)
    for i, r in enumerate(refs):
        row={'reference':r['id'], 'candidate':None, 'localization':0., 'structure':0., 'material_appearance':0., 'score':0.}
        a=crop(left,r['box']);sheet.paste(a,(0,i*218+26))
        if i in matches:
            c=candidates[matches[i]];b=crop(right,c['box']);sheet.paste(b,(192,i*218+26))
            parts=appearance_components(np.asarray(a,float)/255,np.asarray(b,float)/255)
            loc=float(matrix[i,matches[i]])
            structure=.75*parts['structure_ssim_mean']+.25*parts['edge_score']
            material=.625*parts['region_color_score']+.375*parts['region_tone_score']
            row.update(candidate=c['id'],localization=loc,structure=structure,material_appearance=material,
                       score=loc*(.6*structure+.4*material),appearance=parts,reference_box=r['box'],candidate_box=c['box'])
        draw.text((3,i*218+4),f"{r['id']} -> {row['candidate'] or 'missing'}",fill='white')
        rows.append(row)
    sheet.save(output/'object-comparisons.jpg',quality=92)
    appearance=appearance_components(np.asarray(left,float)/255,np.asarray(right,float)/255)
    # Foreground village gets equal weight to the whole environment; fixed
    # reference ROI is the union rectangle, never inferred from the candidate.
    boxes=np.asarray([r['box'] for r in refs]);roi=np.r_[boxes[:,:2].min(0),boxes[:,2:].max(0)]
    w,h=left.size;rect=tuple(int(v) for v in roi*[w,h,w,h])
    village=appearance_components(np.asarray(left.crop(rect),float)/255,np.asarray(right.crop(rect),float)/255)
    denom=max(len(refs),len(candidates))
    result={'method':VERSION, 'reference_sha256':digest(reference),'candidate_sha256':digest(rgb),'mask_sha256':digest(mask),
            'annotation_sha256':digest(annotations),'annotation_status':ann['status'],
            'environment_score':.5*appearance['score']+.5*village['score'],
            'environment':{'whole_image':appearance,'fixed_village_region':village,'region':roi.tolist()},
            'objects_score':sum(r['score'] for r in rows)/denom,
            'localization_score':sum(r['localization'] for r in rows)/denom,
            'reference_count':len(refs),'candidate_count':len(candidates),'objects':rows,
            'formula':'mean over max(reference,candidate) of localization*(0.6*crop_structure+0.4*crop_material_appearance)',
            'crop_protocol':'aspect-preserving fit to 192x192 neutral canvas; no per-object rotation or image warping',
            'formal_score_eligible':False,
            'limitations':['Visible 2D building evidence only; no hidden 3D accuracy claim.',
                           'RGB crops contain background; the score is an image proxy, not semantic identity proof.',
                           'Reference annotation calibration and human ranking validation remain pending.']}
    write_json(output/'scores.json',result)
    return result
