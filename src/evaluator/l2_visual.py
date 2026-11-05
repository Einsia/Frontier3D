"""Image pairing and reviewed ROI/mask/landmark diagnostics, never semantic gates."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps
from skimage.metrics import structural_similarity


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def image_ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': file_hash(path)}


def checked_image(item):
    path = Path(item['path'])
    if file_hash(path) != item['sha256']:
        raise ValueError('Visual evidence changed: '+path.name)
    with Image.open(path) as image:
        return image.convert('RGB')


def annotation_template(evidence):
    views = {}
    for name, artifact in evidence.get('artifacts', {}).items():
        if not name.endswith('.png') or not artifact.get('loadable') or not artifact.get('path'):
            continue
        reference = evidence.get('reference_images', {}).get(Path(name).stem)
        views[name] = {'candidate': image_ref(artifact['path']),
            'reference': image_ref(reference['path']) if reference else None, 'regions': []}
        camera = next((v['camera'] for v in evidence.get('audit_views', []) if v['artifact'] == name), None)
        for entity, projection in evidence.get('scene', {}).get('entity_projections', {}).get(camera, {}).items():
            if reference and projection.get('role') == 'chair' and projection.get('box'):
                box = projection['box']
                views[name]['regions'].append({'id': 'chair_'+hashlib.sha256(entity.encode()).hexdigest()[:8],
                    'reference_box': box, 'candidate_box': box, 'approved': False, 'landmarks': [],
                    'reference_mask': None, 'candidate_mask': None,
                    'proposal_source': 'Candidate chair projection; a human must locate the corresponding reference region.'})
    return {'schema_version': 1, 'reviewer': '', 'reviewed_at': '', 'views': views,
        'region_example': {'id': 'chair', 'reference_box': [0., 0., 1., 1.],
            'candidate_box': [0., 0., 1., 1.], 'approved': False,
            'landmarks': [], 'reference_mask': None, 'candidate_mask': None},
        'instructions': 'Add task-relevant normalized XYXY regions and paired landmarks; approve only after visual review. Empty regions are pending, never perfect similarity.'}


def valid_points(value, shape):
    array = np.asarray(value, dtype=float)
    if array.shape != shape or not np.isfinite(array).all() or np.any(array < 0) or np.any(array > 1):
        raise ValueError('Coordinates must be finite normalized values in [0,1]')
    return array


def crop(image, box):
    box = valid_points(box, (4,))
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError('ROI must have positive area')
    rectangle = tuple(round(v*s) for v, s in zip(box, (image.width,image.height,image.width,image.height)))
    if rectangle[2]-rectangle[0] < 1 or rectangle[3]-rectangle[1] < 1:
        raise ValueError('ROI is smaller than one pixel')
    return image.crop(rectangle)


def comparison(reference, candidate):
    reference = reference.resize((256,256))
    candidate = candidate.resize((256,256))
    a,b = [np.asarray(im.convert('L'), dtype=float)/255 for im in (reference,candidate)]
    edges = []
    for data in (a,b):
        gy,gx = np.gradient(data)
        edges.append(np.hypot(gx,gy) > .08)
    intersection = np.logical_and(*edges).sum()
    union = np.logical_or(*edges).sum()
    return {'ssim': float(structural_similarity(a,b,data_range=1)),
        'edge_iou': float(intersection/union) if union else None,
        'method': 'Resized pixel/edge proxies; alignment and semantic correctness are not established.'}


def pair_sheet(reference, candidate, path, label):
    canvas = Image.new('RGB',(900,490),'#eeeeee')
    draw = ImageDraw.Draw(canvas)
    draw.text((10,10), label[:120], fill='black')
    for x, name, im in ((0,'REFERENCE',reference),(450,'CANDIDATE',candidate)):
        draw.text((x+10,32),name if im else name+' unavailable', fill='black')
        if im:
            tile = ImageOps.contain(im,(440,435))
            canvas.paste(tile,(x+(450-tile.width)//2,50+(435-tile.height)//2))
    canvas.save(path)


def visual_diagnostics(annotations, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if annotations.get('schema_version') != 1:
        raise ValueError('Invalid visual annotation schema')
    results = {'diagnostic_only': True, 'views': {}, 'pending_regions': [], 'status': 'pending_human'}
    for index, (view, entry) in enumerate(annotations['views'].items()):
        candidate = checked_image(entry['candidate'])
        reference = checked_image(entry['reference']) if entry.get('reference') else None
        pair_sheet(reference,candidate,output/f'view-{index}.png', view)
        result = {'pair_image': str((output/f'view-{index}.png').resolve()), 'regions': [],
            'full_image_proxy': comparison(reference,candidate) if reference else None}
        seen = set()
        if reference and not entry['regions']:
            results['pending_regions'].append(view)
        for region in entry['regions']:
            identity = region.get('id','')
            if not re.fullmatch(r'[A-Za-z0-9_-]+',identity) or identity in seen or reference is None:
                raise ValueError('Regions require a reference and unique safe identifiers')
            seen.add(identity)
            if type(region.get('approved')) is not bool:
                raise ValueError('Region needs explicit approval state')
            approved = region['approved']
            if approved and (not annotations.get('reviewer','').strip() or not annotations.get('reviewed_at','').strip()):
                raise ValueError('Approved annotations require reviewer and date')
            a,b = crop(reference,region['reference_box']),crop(candidate,region['candidate_box'])
            image_path = output/f'view-{index}-{identity}.png'
            pair_sheet(a,b,image_path,view+' / '+identity)
            measurements = comparison(a,b)
            measurements['reference_roi_aspect'] = a.width/a.height
            measurements['candidate_roi_aspect'] = b.width/b.height
            measurements['aspect_ratio_relative_error'] = abs((b.width/b.height)/(a.width/a.height)-1)
            landmarks = region.get('landmarks',[])
            distances = []
            for landmark in landmarks:
                a,b = [valid_points(landmark[key],(2,)) for key in ('reference','candidate')]
                distances.append(float(np.linalg.norm(a-b)))
            measurements['landmark_mean_normalized_distance'] = float(np.mean(distances)) if distances else None
            masks = [region.get(k) for k in ('reference_mask','candidate_mask')]
            if any(masks):
                if not all(masks):
                    raise ValueError('Both reference and candidate masks are required')
                arrays = []
                for mask, source, box in zip(masks,(reference,candidate),(region['reference_box'],region['candidate_box'])):
                    image = checked_image(mask)
                    if image.size != source.size:
                        raise ValueError('Mask must match its full source image dimensions')
                    arrays.append(np.asarray(crop(image,box).convert('L').resize((256,256), Image.Resampling.NEAREST)) > 127)
                union = np.logical_or(*arrays).sum()
                measurements['silhouette_iou'] = float(np.logical_and(*arrays).sum()/union) if union else None
            if not approved:
                results['pending_regions'].append(view+'/'+identity)
            result['regions'].append({'id': identity, 'status': 'reviewed_annotation' if approved else 'pending_human',
                'measurements': measurements, 'pair_image': str(image_path.resolve())})
        results['views'][view] = result
    results['annotation_status'] = 'pending_human' if results['pending_regions'] else 'available'
    (output/'visual_diagnostics.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return results
