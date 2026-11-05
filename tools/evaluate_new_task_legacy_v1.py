"""Isolated legacy-v1 components for new tasks, retaining missing native evidence.

Uses unchanged v1 image/box/rubric functions. New task recipes are separately
frozen. A weighted total is never emitted when a required component is missing.
"""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from pathlib import Path

import argparse,copy,concurrent.futures,fcntl,json,os,sys,time

from dataclasses import replace

ROOT=Path(__file__).resolve().parents[1]

sys.path.insert(0,str(ROOT))

from tools.prepare_new_task_legacy_v1 import RUN,BATCH,verify

from src.agent_judge.protocol import read_json as read,write_json as write,digest,contract_hash

from harness.L2.vlm_judge import judge_task,JudgeConfig

from src.agent_judge.runtime import run_codex

from src.agent_judge import l2_rubric,task_continuous

from src.evaluator.l2_reference_boxes import POLICY as BOX_POLICY,validate_annotation

from src.evaluator.l2_reference_regions import regional_components

from src.evaluator.l2_reference_image import appearance_components

from PIL import Image

import numpy as np

def pin(p):p=Path(p);return {'path':str(p.resolve()),'sha256':digest(p)}

def invoke(*args,**kwargs):return run_codex(*args,**kwargs,engine='responses',image_transport='lossless_webp',responses_options={'max_rounds':1,'request_attempts':2,'max_output_tokens':10000})

def specs(row,rules,folder,refs):
 brief=not refs;instruction=(Path(row['task_root'])/'instruction.md').read_text();annotation=None
 if refs:
  primary=refs[0];size=Image.open(primary['path']).size
  annotation={'version':'reference-boxes-v1','scoring_profile':'l2-photo-localized-v5.0.0' if row['category']=='Reference2Scene-RealPhoto' else 'l2-reference-localized-v5.3.0','policy':BOX_POLICY,'task_id':row['task_id'],'image_size':list(size),'reference_path':rules['reference_primary'],'reference_sha256':primary['sha256'],'detector':{'fingerprint':'gpt-6-astra-reference-only-v1-rules-'+digest(folder/'rules.json')},'context_queries':[],'targets':[{**t,'review_status':'approved','machine_annotation':True,'human_reviewed':False} for t in rules['targets']]}
  validate_annotation(annotation)
 if brief:
  checks=[{'id':r['id'],'question':r['question'],'dimension':'instruction_following','weight':.6*r['weight'],'units':[r['source_quote']]} for r in rules['semantic_checks']]
  checks += [{'id':'aesthetic_'+str(i),'question':q,'dimension':'aesthetics','weight':.1,'units':[q]} for i,q in enumerate(['作者构图、视觉层级与可读性','光照、阴影与色彩协调','形体、材质和连接细节的完成度','整体设计与呈现的一致性'])]
 else:
  checks=[{'id':k,'question':q,'dimension':d,'weight':w,'units':[k]} for k,d,w,q in [('subject_fidelity','reference_fidelity',.4,'Compare subject identity, distinctive shape, proportions, completeness and visible parts against original references.'),('composition_fidelity','reference_layout',.3,'Compare primary framing, relative position, scale, depth and occlusion on original pixel grid; no alignment.'),('appearance_fidelity','reference_appearance',.3,'Compare authored materials, colours, lighting and rendering style to original references.')]]
 spec={'protocol':l2_rubric.PROTOCOL,'case_id':row['task_id'],'family':'Brief2Scene' if brief else 'Reference2Scene','instruction_sha256':contract_hash(instruction),'reference_policy':'Written public brief only; no private example.' if brief else 'reference/reference-0 is the primary target. Other supplied references clarify geometry only. Compare native pixel grids without registration.','focus':'New-task adaptation of legacy-detail-20261018-v1. Exact numeric properties require native measurements; never infer them from perspective pixels.','missing_policy':l2_rubric.MISSING_POLICY,'anchors':l2_rubric.ANCHORS,'checks':checks,'localization':annotation}
 l2_rubric.validate_spec(spec)
 bindings={f'reference/reference-{i}'+Path(r['path']).suffix:r['sha256'] for i,r in enumerate(refs)}
 detail={'protocol':task_continuous.PROTOCOL,'release_id':'legacy-v1-new-task-detail-20261020','case_id':row['task_id'],'family':'Brief2Scene' if brief else 'Reference2Scene','instruction_sha256':contract_hash(instruction),'reference_policy':spec['reference_policy'],'focus':'Only local morphology and part composition; preserve allowed simplifications, do not give colour credit for shape.','reference_bindings':bindings,'authoring':'candidate_blind_public_contract_rules','formal_score_eligible':False,'checks':[{'id':r['id'],'component':'F','question':r['question'],'units':[r['source_quote']],'global_weight':r['weight'],'coverage_definition':'Fraction of explicit local features demonstrated','deviation_definition':'Geometric deviation within implemented features only; zero coverage implies zero deviation','required_evidence':['candidate/main.png','candidate/alternate.png',*bindings]} for r in rules['detail_checks']]}
 task_continuous.validate_spec(detail)
 return spec,detail

def measured_image(row,rules,refs,images):
 with Image.open(refs[0]['path']) as a, Image.open(images['main.png']['path']) as b:
  if a.size!=b.size:return {'score':None,'status':'not_measurable','reason':'Native pixel grids differ; no resizing allowed'}
  aa=np.asarray(a.convert('RGB'),dtype=float)/255;bb=np.asarray(b.convert('RGB'),dtype=float)/255
  result=appearance_components(aa,bb) if row['category']=='Reference2Scene-RealPhoto' else regional_components(aa,bb,{'version':'reference-regions-v1','regions':rules['regions']})
 return {**result,'status':'measured','reference':refs[0],'candidate':images['main.png']}

def run_one(row,model):
 name=Path(row['task_id']).name;out=RUN/'new-task-evaluations'/model/name;out.mkdir(parents=True,exist_ok=True)
 if (out/'report.json').exists():return read(out/'report.json')['status']
 rf=RUN/'new-task-rules'/name;accepted=read(rf/'accepted.json')
 if digest(rf/'rules.json')!=accepted['sha256']:raise ValueError('Rules changed')
 rules=verify(read(rf/'rules.json'),row)
 original=BATCH/'runs'/model/name;source=read(original/'evaluation/report.json');generation=read(original/'generation_state.json')
 if generation['status']!='completed':raise ValueError('Source candidate not completed')
 for n,h in generation['artifact_sha256'].items():
  if digest(Path(generation['output'])/n)!=h:raise ValueError('Original generated artifact changed')
 images=source['images']
 for v in images.values():
  if digest(Path(v['path']))!=v['sha256']:raise ValueError('Image evidence changed')
 refs=[pin(Path(row['task_root'])/'environment'/n) for n in sorted(row['public_reference_paths'],key=lambda n:(n!=rules['reference_primary'],n))]
 v_spec,d_spec=specs(row,rules,rf,refs)
 for n,s in [('vlm_spec.json',v_spec),('detail_spec.json',d_spec)]:
  p=out/n
  if p.exists() and read(p)!=s:raise ValueError('Cannot change frozen candidate rubric')
  if not p.exists():write(p,s)
 write(out/'source_bindings.json',{'rule':pin(rf/'rules.json'),'source_report':pin(original/'evaluation/report.json'),'generation':pin(original/'generation_state.json'),'images':images,'references':refs,'candidate_model':model})
 cfg=replace(JudgeConfig.from_env(env_path()),model=judge_model(),effort='medium',timeout=600,attempts=3)
 judgments={}
 for key,spec in [('vlm',v_spec),('detail',d_spec)]:
  write(out/'state.json',{'status':'running','phase':key,'task_id':row['task_id'],'tested_model':model,'pid':os.getpid()})
  evidence={'artifacts':images,'reference_images':{f'{i:03d}':r for i,r in enumerate(refs)}}
  frozen={'version':'continuous-task-judge-v1' if key=='detail' else 'l2-vlm-judge-v2','spec':spec,'spec_sha256':digest(out/('detail_spec.json' if key=='detail' else 'vlm_spec.json')),'mode':'visual'}
  judgments[key]=judge_task(Path(row['task_root']),evidence,{'_vlm_judge':frozen},out/key,config=cfg,tested_model=model,invoke=invoke)
  if judgments[key].get('status')!='scored':
   write(out/'state.json',{'status':'technical_failure','phase':key});return 'technical_failure'
 image=measured_image(row,rules,refs,images) if refs else None
 if image:write(out/'image_measurement.json',image)
 # Native content remains a distinct measurement. Never replace unknown native
 # quantities with VLM guesses or turn partial audit statuses into numeric scores.
 native=read(original/'constraints/report.json')
 components={'vlm':judgments['vlm']['S_vlm'],'detail':sum(c['global_weight']*next(x['score'] for x in judgments['detail']['criteria'] if x['check_id']==c['id']) for c in d_spec['checks'])}
 missing=[]
 if refs:
  components.update(main_image=image['score'],localization=judgments['vlm'].get('localization',{}).get('score'))
  weights={'main_image':.5,'localization':.2,'vlm':.2,'detail':.1}
 else:
  components['data']=None;weights={'vlm':.6,'data':.3,'detail':.1}
  missing.append('Native content collectors for the frozen numeric checks are required; existing partial/observed audits cannot be converted to pass scores.')
 # Legacy v1 requires variant provenance for detail and system validity; preserve
 # unknowns while showing measured components. These are not final v1 totals.
 missing.append('Bind required seed/export detail variants and original legacy system-validity gates for this new task revision.')
 missing += ['Missing component: '+k for k,v in components.items() if v is None]
 report={'task_id':row['task_id'],'model':model,'status':'components_measured_missing_evidence','score':None,'S_core':None,'components':components,'component_weights':weights,'missing_measurements':missing,'vlm':judgments['vlm'],'detail':judgments['detail'],'native_audit_source':pin(original/'constraints/report.json'),'rules':pin(rf/'rules.json'),'new_candidate_generations':0,'formal_score_eligible':False,'scoring_version':'legacy-detail-20261018-v1','task_adaptation':'new-task-v1-20261020','source_scene_sha256':generation['artifact_sha256']['scene.blend']}
 write(out/'report.json',report);write(out/'state.json',{'status':report['status']});return report['status']
