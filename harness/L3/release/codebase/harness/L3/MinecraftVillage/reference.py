"""Native-view image reconstruction measurements, separate from VLM rubrics.

The submitted camera is a frozen part of the prediction for external screenshots;
the evaluator re-renders it. No image fitting, best-view selection or rescaling.
Reference annotation readiness and rendering limitations remain explicit.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy.optimize import linear_sum_assignment
from .protocol import digest, write_json


def polygon_mask(points, size):
    if len(points)<3 or any(len(p)!=2 or any(not np.isfinite(x) or not 0<=x<=1 for x in p) for p in points):
        raise ValueError('Polygons require at least three normalized image points')
    w,h=size;image=Image.new('1',size)
    ImageDraw.Draw(image).polygon([(x*(w-1),y*(h-1)) for x,y in points],fill=1)
    return np.asarray(image,bool)


def mask_iou(a,b):
    union=np.count_nonzero(a|b)
    return np.count_nonzero(a&b)/union if union else 0.


def bounding_mask(mask):
    result=np.zeros_like(mask)
    y,x=np.nonzero(mask)
    if len(x):result[y.min():y.max()+1,x.min():x.max()+1]=True
    return result


def match_instances(reference, candidates):
    if not reference:raise ValueError('No reference instances; accuracy is not applicable without targets')
    matrix=np.array([[mask_iou(r['mask'],c['mask']) if r['class']==c['class'] else 0. for c in candidates] for r in reference])
    pairs={}
    if candidates:
        rows,cols=linear_sum_assignment(-matrix)
        pairs={int(i):int(j) for i,j in zip(rows,cols) if matrix[i,j]>0}
    records=[{'reference':r['id'],'candidate':candidates[pairs[i]]['id'] if i in pairs else None,
              'visible_iou':float(matrix[i,pairs[i]]) if i in pairs else 0.} for i,r in enumerate(reference)]
    return {'reference_count':len(reference),'candidate_count':len(candidates),'matches':records,
            'unmatched_reference':len(reference)-len(pairs),'unmatched_candidate':len(candidates)-len(pairs),
            'mean_visible_iou_with_missing_and_extra_penalty':sum(r['visible_iou'] for r in records)/max(len(reference),len(candidates)),
            'scope':'Visible annotated silhouettes and class-constrained correspondence, not hidden 3D shape or semantic correctness from IDs'}


def rendered_mask_color(rgb, encoding):
    """UE converts FColor sRGB to linear, then disabled-tonemapper output uses gamma 2.2."""
    if encoding!='ue_srgb_linear_display_gamma_2_2':raise ValueError('Unknown mask color encoding')
    values=np.asarray(rgb,float)/255
    linear=np.where(values<=.04045,values/12.92,((values+.055)/1.055)**2.4)
    return np.rint(np.power(linear,1/2.2)*255).astype(np.int16)


def evaluate(reference_path, candidate_path, annotation_path, view_path, mask_path=None, palette_path=None):
    reference=np.asarray(Image.open(reference_path).convert('RGB'),float)/255
    candidate=np.asarray(Image.open(candidate_path).convert('RGB'),float)/255
    if reference.shape!=candidate.shape:raise ValueError('Native image dimensions must match; resizing is forbidden')
    annotations=json.loads(annotation_path.read_text());view=json.loads(view_path.read_text())
    if annotations['reference_sha256']!=digest(reference_path):raise ValueError('Reference image differs from frozen annotations')
    if view.get('candidate_sha256')!=digest(candidate_path) or view.get('reference_sha256')!=digest(reference_path):
        raise ValueError('Render provenance does not match the measured images')
    if view.get('protocol') not in {'fixed_reference_camera','joint_scene_camera_prediction'} or view.get('posthoc_alignment') is not False:
        raise ValueError('Declare a fixed camera protocol with no post-hoc image alignment')
    if view.get('evaluator_rendered') is not True or not view.get('camera'):
        raise ValueError('A genuine evaluator render and camera observation are required')
    from src.evaluator.l2_reference_image import appearance_components
    global_appearance=appearance_components(reference,candidate)
    regions=[];h,w=reference.shape[:2]
    for region in annotations.get('regions',[]):
        mask=polygon_mask(region['polygon'],(w,h))
        if not mask.any():raise ValueError('Empty reference region')
        # Equal region reporting prevents a huge terrain/background from hiding
        # a missing village; no inter-region or cross-dimension weight is invented.
        regions.append({'id':region['id'],'pixel_count':int(mask.sum()),
                        'native_rgb_mae':float(np.abs(reference[mask]-candidate[mask]).mean()),
                        'mean_color_error':float(np.linalg.norm(reference[mask].mean(0)-candidate[mask].mean(0)))})
    objects={'status':'pending_instance_masks','value':None}
    if mask_path is not None:
        if palette_path is None:raise ValueError('Instance masks require a trusted palette record')
        palette=json.loads(palette_path.read_text())
        if palette.get('mask_sha256')!=digest(mask_path) or palette.get('candidate_sha256')!=digest(candidate_path):
            raise ValueError('Mask/candidate provenance mismatch')
        if palette.get('camera')!=view['camera']:raise ValueError('Mask and RGB must use the same camera')
        colors=[tuple(group['rgb']) for group in palette['groups']]
        if len(set(colors))!=len(colors) or any(len(c)!=3 or not any(c) or any(type(v) is not int or not 0<=v<=255 for v in c) for c in colors):
            raise ValueError('Mask colors must be unique nonblack RGB codes')
        pixels=np.asarray(Image.open(mask_path).convert('RGB'))
        if pixels.shape!=reference.shape:raise ValueError('Mask has a different native resolution')
        refs=[dict(id=r['id'],**{'class':r['class']},mask=polygon_mask(r['polygon'],(w,h))) for r in annotations.get('objects',[])]
        candidates=[]
        known=np.max(pixels,axis=2)<=3
        for group in palette['groups']:
            # Renderer AA is disabled; permit only a small recorded colour-code deviation.
            encoded=rendered_mask_color(group['rgb'],palette.get('color_encoding'))
            mask=np.max(np.abs(pixels.astype(np.int16)-encoded),axis=2)<=3
            known|=mask
            if annotations.get('object_geometry')=='bounding_box':mask=bounding_mask(mask)
            if mask.any():candidates.append(dict(id=group['id'],**{'class':group['class']},mask=mask))
        nonblack=np.count_nonzero(np.max(pixels,axis=2)>3)
        unknown_fraction=np.count_nonzero(~known)/max(nonblack,1)
        if unknown_fraction>.01:raise ValueError('Mask color validation failed; do not interpret renderer errors as missing objects')
        objects=match_instances(refs,candidates)
        objects['unknown_color_fraction_of_foreground']=float(unknown_fraction)
        objects.update(status='measured_visible_2d',value=None,mask_sha256=digest(mask_path),
                       opacity_preserved=not palette.get('nonopaque_components'),
                       rendering_limitations=palette.get('nonopaque_components',[]))
        objects['annotation_geometry']=annotations.get('object_geometry','visible_polygon')
        if annotations.get('object_geometry')=='bounding_box':
            objects['scope']='Visible instance bounding-box localization; no silhouette, part, material or 3D-shape accuracy is inferred.'
    reviewed=annotations.get('status')=='independently_reviewed'
    return {'method':'native_reference_and_visible_instances_v1','reference_sha256':digest(reference_path),
            'candidate_sha256':digest(candidate_path),'annotations_sha256':digest(annotation_path),
            'camera_protocol':view['protocol'],'annotation_status':annotations.get('status','unknown'),
            'environment':{'global_l2_appearance':global_appearance,'regions':regions,'value':None},'objects':objects,
            'formal_score':None,'annotation_ready':reviewed,
            'scope':'Single-view reconstruction of visible content; camera prediction error remains part of image error. Unseen interiors are evaluated against text requirements.',
            'limitations':([] if reviewed else ['Reference annotations require independent review.'])+
                           ['Region and cross-dimension weights are not set; no full 3D accuracy is claimed.']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','candidate','annotations','view','output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--mask',type=Path);p.add_argument('--palette',type=Path);a=p.parse_args()
    write_json(a.output,evaluate(a.reference,a.candidate,a.annotations,a.view,a.mask,a.palette))
