"""CPU-only local Grounding DINO worker. Does not execute candidate code."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time


def digest(file):
    with Path(file).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def uniform_image(image):
    """A constant RGB image cannot contain a visible localized foreground."""
    return all(high-low <= 1 for low,high in image.convert('RGB').getextrema())


def phrase_prompt(phrases):
    """Keep phrase boundaries explicit, including multi-token object names."""
    text='';spans=[]
    for phrase in phrases:
        phrase=phrase.strip().lower()
        if not phrase or '.' in phrase:raise ValueError('Distinct plain object phrases required')
        start=len(text);text+=phrase;spans.append((start,len(text)));text+='. '
    if len(set(phrases))!=len(phrases):raise ValueError('Duplicate object/context phrases')
    return text.rstrip(),spans


def phrase_scores(probabilities,offsets,spans):
    """Mean token probability per fixed phrase, as in given-phrase grounding."""
    import numpy as np
    indices=[[i for i,(a,b) in enumerate(offsets) if b>a and a<end and b>start] for start,end in spans]
    if any(not selected for selected in indices):raise ValueError('Missing/truncated phrase tokens')
    if max(max(s) for s in indices)>=probabilities.shape[1]:raise ValueError('Phrase tokens exceed detector capacity')
    return np.stack([probabilities[:,selected].mean(axis=1) for selected in indices],axis=1)


def planet_limb_box(image,box):
    """Recover a full disk from observed curved edges, never from reference coordinates.

    Seed boxes only bound the search. Require radial edge support over at least
    40% of angular bins; straight terminators/rectangles alone cannot define a disk.
    Unresolved partial boxes are diagnostic, not an automatic model penalty.
    """
    import numpy as np
    from PIL import ImageFilter
    image=image.convert('L');image.thumbnail((1000,1000));w,h=image.size
    b=np.array(box)*[w,h,w,h];span=max(b[2]-b[0],b[3]-b[1]);pad=.65*span
    if span<12:return None
    left,top=np.maximum(0,np.floor(b[:2]-pad)).astype(int);right,bottom=np.minimum([w,h],np.ceil(b[2:]+pad)).astype(int)
    gray=np.array(image.filter(ImageFilter.GaussianBlur(.8)),dtype=float)
    gy,gx=np.gradient(gray);mag=np.hypot(gx,gy)
    roi=mag[top:bottom,left:right];threshold=max(2.,float(np.quantile(roi,.86)))
    ys,xs=np.nonzero(roi>threshold);xs=xs+left;ys=ys+top
    if len(xs)<20:return None
    ex=gx[ys,xs]/mag[ys,xs];ey=gy[ys,xs]/mag[ys,xs]
    best=None
    for radius in np.linspace(.4*span,.7*span,41):
        votes=np.zeros((bottom-top,right-left),np.float32)
        for sign in [-1,1]:
            cx=np.rint(xs+sign*radius*ex-left).astype(int);cy=np.rint(ys+sign*radius*ey-top).astype(int)
            ok=(cx>=0)&(cx<right-left)&(cy>=0)&(cy<bottom-top)
            np.add.at(votes,(cy[ok],cx[ok]),1)
        votes=sum(np.roll(np.roll(votes,dy,0),dx,1) for dy in [-1,0,1] for dx in [-1,0,1])
        for flat in np.argpartition(votes.ravel(),-3)[-3:]:
            cy,cx=np.unravel_index(flat,votes.shape);cx+=left;cy+=top
            dx=xs-cx;dy=ys-cy;distance=np.hypot(dx,dy)
            alignment=np.abs((dx*ex+dy*ey)/np.maximum(distance,1))
            tolerance=max(1.5,.015*radius)
            good=(np.abs(distance-radius)<tolerance)&(alignment>.8)
            bins=np.floor((np.arctan2(dy[good],dx[good])+np.pi)*36/(2*np.pi)).astype(int)%36
            coverage=len(np.unique(bins))/36
            if coverage<.4:continue
            circle=np.array([cx-radius,cy-radius,cx+radius,cy+radius])
            inter=np.prod(np.maximum(0,np.minimum(circle[2:],b[2:])-np.maximum(circle[:2],b[:2])))
            if inter/np.prod(b[2:]-b[:2])<.75:continue
            score=coverage+min(1,len(bins)/(2*np.pi*radius))*.1
            if best is None or score>best[0]:best=(score,cx,cy,radius,coverage,good)
    if best is None:return None
    _,cx,cy,radius,coverage,good=best
    for _ in range(3):
        x=xs[good];y=ys[good];solution=np.linalg.lstsq(np.column_stack([2*x,2*y,np.ones(len(x))]),x*x+y*y,rcond=None)[0]
        a,c,k=solution;rad=np.sqrt(max(0,k+a*a+c*c))
        if abs(rad-radius)>.12*radius or np.hypot(a-cx,c-cy)>.12*radius:break
        cx,cy,radius=a,c,rad;d=np.hypot(xs-cx,ys-cy);good=(np.abs(d-radius)<max(2.,.05*radius))&(np.abs(((xs-cx)*ex+(ys-cy)*ey)/np.maximum(d,1))>.8)
    return {'box':np.clip(np.array([cx-radius,cy-radius,cx+radius,cy+radius])/[w,h,w,h],0,1).tolist(),'coverage':coverage,'circle':[float(cx),float(cy),float(radius)],'method':'visible_limb_circle_v1'}

def main(request, output):
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    import torch
    import transformers
    from PIL import Image
    from transformers import AutoProcessor, AutoTokenizer, AutoModelForZeroShotObjectDetection
    config = request['detector'];directory = Path(request['model_directory'])
    fingerprint=hashlib.sha256(json.dumps({k:v for k,v in config.items() if k!='fingerprint'},
        sort_keys=True,separators=(',',':')).encode()).hexdigest()
    modern=config.get('worker_version') in {'l2-grounding-dino-v5','l2-grounding-dino-v6'}
    expected_mode='joint_phrase_spans_argmax' if modern else 'joint_phrases_unique_label'
    if (fingerprint!=config['fingerprint'] or config.get('worker_version') not in {'l2-grounding-dino-v4','l2-grounding-dino-v5','l2-grounding-dino-v6'}
            or config.get('uniform_max_channel_range')!=1
            or config.get('query_mode')!=expected_mode or config.get('device')!='cpu'
            or config.get('threads')!=4 or config.get('threshold')!=.25 or config.get('text_threshold')!=.25
            or config.get('use_fast') is not False):raise ValueError('Frozen detector configuration mismatch')
    refinement=config.get('boundary_refinement',{})
    if config.get('worker_version')=='l2-grounding-dino-v6':
        if refinement!={'planet':'visible_limb_circle_v1'}:raise ValueError('Frozen planet boundary convention required')
    elif refinement:raise ValueError('Boundary refinement requires the v6 detector')
    scales=config.get('short_edges',[800])
    if scales not in ([800],[800,1200]):raise ValueError('Unsupported frozen image pyramid')
    if not modern and scales!=[800]:raise ValueError('Legacy detector uses one scale')
    if {'torch': torch.__version__, 'transformers': transformers.__version__} != config['runtime']:
        raise ValueError('Frozen detector runtime version mismatch')
    for name, expected in config['files'].items():
        if Path(name).name != name or digest(directory/name) != expected:
            raise ValueError('Detector model/tokenizer/configuration hash mismatch')
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    torch.manual_seed(0);torch.use_deterministic_algorithms(True)
    processor = AutoProcessor.from_pretrained(directory, local_files_only=True, use_fast=False)
    span_tokenizer=AutoTokenizer.from_pretrained(directory,local_files_only=True,use_fast=True) if modern else None
    model = AutoModelForZeroShotObjectDetection.from_pretrained(directory, local_files_only=True,
        use_safetensors=True).to('cpu').eval()
    results = []
    for item in request['images']:
        started=time.monotonic();file=Path(item['path']);before=digest(file)
        if before!=item['sha256']:raise ValueError('Image changed before detection')
        with Image.open(file) as source:image=source.convert('RGB')
        queries={q:[] for q in item['queries']};ambiguous=[]
        prompts=[*queries,*item.get('context_queries',[])]
        if modern:
            text,spans=phrase_prompt(prompts)
            # Fast offsets only map phrases; the detector still uses the frozen
            # slow tokenizer, with exact input-id equality checked below.
            tokens=span_tokenizer(text,return_offsets_mapping=True)
            constant=uniform_image(image)
            for scale in scales:
                inputs=processor(images=image,text=text,return_tensors='pt',
                    size={'shortest_edge':scale,'longest_edge':round(scale*1333/800)})
                if inputs.input_ids[0].tolist()!=tokens['input_ids']:raise ValueError('Phrase tokenization mismatch')
                with torch.inference_mode():raw=model(**inputs)
                scores=phrase_scores(raw.logits[0].sigmoid().cpu().numpy(),tokens['offset_mapping'],spans)
                winners=scores.argmax(axis=1)
                for index,(cx,cy,w,h) in enumerate(raw.pred_boxes[0].tolist()):
                    owner=int(winners[index]);confidence=float(scores[index,owner])
                    if confidence<.25:continue
                    box=[max(0.,min(1.,v)) for v in [cx-w/2,cy-h/2,cx+w/2,cy+h/2]]
                    if box[2]<=box[0] or box[3]<=box[1]:continue
                    label=prompts[owner]
                    row={'box':box,'confidence':confidence,'text_label':label,'short_edge':scale}
                    if constant:
                        row['rejected_reason']='uniform_image_without_visible_foreground';ambiguous.append(row)
                    elif label in queries:queries[label].append(row)
                    else:
                        row['rejected_reason']='context_class';ambiguous.append(row)
        else:
            legacy_detect(processor,model,torch,image,prompts,queries,ambiguous)
            constant=uniform_image(image)
        unresolved=[]
        for query in refinement:
            for row in queries.get(query,[]):
                fitted=planet_limb_box(image,row['box'])
                row['raw_detector_box']=row['box']
                if fitted:
                    row['box']=fitted['box'];row['boundary_refinement']=fitted
                else:
                    width=(row['box'][2]-row['box'][0])*image.width
                    height=(row['box'][3]-row['box'][1])*image.height
                    if max(width,height)/min(width,height)>1.35:
                        unresolved.append({'query':query,'box':row['box'],'reason':'Full planet limb could not be resolved; partial illuminated region is diagnostic only'})
        if digest(file)!=before:raise ValueError('Image changed during detection')
        results.append({'key':item['key'],'status':'measured','image_sha256':before,
            'image_size':list(image.size),'queries':queries,'detector_fingerprint':config['fingerprint'],
            'uniform_image_filter':constant,'boundary_review_required':unresolved,
            'ambiguous_detections':ambiguous,'elapsed_seconds':time.monotonic()-started})
        output.parent.mkdir(parents=True,exist_ok=True)
        temporary=output.with_suffix('.tmp');temporary.write_text(json.dumps(results,indent=2)+'\n');temporary.replace(output)
        print('detected',item['key'],{q:len(v) for q,v in queries.items()},flush=True)


def legacy_detect(processor,model,torch,image,prompts,queries,ambiguous):
    inputs=processor(images=image,text=' '.join(q.lower().rstrip('.')+'.' for q in prompts),return_tensors='pt')
    with torch.inference_mode():raw=model(**inputs)
    values=processor.post_process_grounded_object_detection(raw,inputs.input_ids,
        threshold=.25,text_threshold=.25,target_sizes=[image.size[::-1]])[0]
    constant=uniform_image(image)
    for box,confidence,label in zip(values['boxes'].tolist(),values['scores'].tolist(),values['text_labels']):
        box=[max(0.,min(1.,float(x)/scale)) for x,scale in zip(box,[*image.size,*image.size])]
        if box[2]<=box[0] or box[3]<=box[1]:continue
        # Partial phrases are accepted only if they identify exactly one
        # frozen query ("chest" -> "chest of drawers"). Multi-class labels
        # are never assigned to whichever reference box fits best.
        label=label.strip().rstrip('.').strip()
        row={'box':box,'confidence':float(confidence),'text_label':label}
        matches=[q for q in prompts if label and set(label.split())<=set(q.split())]
        if constant:
            row['rejected_reason']='uniform_image_without_visible_foreground';ambiguous.append(row)
        elif len(matches)==1 and matches[0] in queries:queries[matches[0]].append(row)
        else:ambiguous.append(row)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();main(json.loads(args.request.read_text()),args.output)
