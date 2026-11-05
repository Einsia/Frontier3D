"""Replay the MC integration fixture measurements; never publish a model baseline."""
import argparse,json,statistics,collections
from pathlib import Path
from .protocol import read_json,write_json,digest,DOORS,REQUIRED,BUILDINGS,tree_digest
from .evaluate import local_diagnostics,journey_diagnostics
from .rubric import CHECKS,VERSION


def inventory_checks(folder):
    ledger=[json.loads(s) for s in (folder/'inventory-audit.jsonl').read_text().splitlines()]
    fields=['seeds','crops','processed','tools']
    expected={'closed_take':[0,0,0,0],'open_chest':[0,0,0,0],'take_seed':[1,0,0,0],'duplicate_seed':[1,0,0,0],
      'plant_mature':[1,0,0,0],'harvest':[1,1,0,0],'duplicate_harvest':[1,1,0,0],'plant':[0,1,0,0],
      'duplicate_plant':[0,1,0,0],'harvest_immature':[0,1,0,0],'harvest_second':[0,2,0,0],
      'plant_without_seed':[0,2,0,0],'process':[0,1,0,0],'busy_process':[0,1,0,0],
      'complete_processing':[0,1,1,0],'second_process':[0,0,2,0],'empty_process':[0,0,2,0],
      'take_tool':[0,0,2,1],'duplicate_tool':[0,0,2,1]}
    rows={}
    for name,wanted in expected.items():
        frame=read_json(folder/(name+'_state.json'));states=[r for r in ledger if r['time']<=frame['time']+1e-6]
        actual=[states[-1][f] for f in fields] if states else None
        rows[name]={'expected':wanted,'actual':actual,'passed':actual==wanted,'time':frame['time']}
    return {'fields':fields,'checks':rows,'passed':sum(r['passed'] for r in rows.values()),'total':len(rows),
      'method':'Evaluator C++ reads actual gameplay counters; candidate state strings/HUD are not used',
      'scope':'Known pilot instrumentation; not a generic adversarially secure inventory oracle'}


def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--evaluation',type=Path,required=True);p.add_argument('--review',type=Path,required=True);p.add_argument('--repair',type=Path);a=p.parse_args()
 root=a.evaluation;w=root/'workspace';original=read_json(a.run/'report.json');episodes=dict(original['episodes'])
 for target in DOORS:
  key=target.replace('.','_');episodes[target]=local_diagnostics(w/key,read_json(w/(key+'-plan.json')),read_json(w/(key+'-binding.json')))
 counts={k:sum(r['check_counts'][k] for r in episodes.values()) for k in ['passed','failed','unresolved','total']}
 inv=inventory_checks(w/'inventory-002');flow=w/'e2e';ledger=[json.loads(s) for s in (flow/'inventory-audit.jsonl').read_text().splitlines()];fields=inv['fields']
 expected=[[0,0,0,0],[1,0,0,0],[1,1,0,0],[0,1,0,0],[0,0,0,0],[0,0,1,0],[0,0,1,1]]
 observed=[[r[f] for f in fields] for r in ledger]
 journey=journey_diagnostics(flow);plan=read_json(w/'e2e-plan.json')
 workflow={'inventory_transition_sequence_passed':observed==expected,'observed':observed,'expected':expected,'fields':fields,
   'no_teleport_in_plan':not any(s['op']=='fixture' for s in plan['steps']),'journey':journey,'route_human_validated':False,
   'scope':'Executed fixed route and inventory sequence; not general navigation coverage or save/reload persistence'}
 review=read_json(a.review/'summary.json');subscores={};repairs=[]
 for name in CHECKS:
  runs=[read_json(a.review/f'{name}-{i}.json') for i in range(3)]
  for i,row in enumerate(runs):
   if row['status']!='judged' and a.repair and (a.repair/f'{name}-0.json').exists():
    replacement=read_json(a.repair/f'{name}-0.json');repairs.append({'item':name,'repeat':i,'invalid_source':str(a.review/f'{name}-{i}.json'),'replacement':str(a.repair/f'{name}-0.json'),'reason':row.get('detail')});runs[i]=replacement
  values=[r['verdict']['score'] for r in runs if r['status']=='judged' and not r['verdict']['not_judgeable'] and r['verdict']['score'] is not None]
  subscores[name]={'median':statistics.median(values) if len(values)==3 else None,'valid_repeats':len(values),'range':[min(values),max(values)] if values else None,'runs':runs}
 axes={}
 for axis in sorted({v[0] for v in CHECKS.values()}):
  names=[k for k,v in CHECKS.items() if v[0]==axis];values=[subscores[k]['median'] for k in names];valid=all(v is not None for v in values)
  axes[axis]={'score':sum(values)/len(values)/4 if valid else None,'subcriteria':names,'weights':[1/len(names)]*len(names),'method':'Equal weight within axis of three-repeat median anchored grades / 4; no cross-axis total'}
 metrics={p.stem:read_json(p) for p in (root/'metrics').glob('*.json') if p.stem!='reference-buildings'}
 support=metrics.get('support-indexed',{});support['unsupported_by_actor']=dict(collections.Counter(v['object'] for v in support.get('unsupported',[])))
 source=Path(read_json(root/'environment.json')['original_project']);instrumented=w/'project';differences=[]
 for file in source.rglob('*'):
  if not file.is_file() or set(file.relative_to(source).parts)&{'Binaries','Intermediate','Saved','DerivedDataCache'} or str(file.relative_to(source)).startswith('Plugins/BenchRuntime/'):continue
  relative=file.relative_to(source)
  if not (instrumented/relative).is_file() or digest(file)!=digest(instrumented/relative):differences.append(str(relative))
 if differences:raise ValueError('Candidate source changed: '+str(differences))
 report={'kind':'manually_adapted_MC_integration_fixture','formal_score_eligible':False,'score':None,'weights':None,
  'candidate_source_sha256':tree_digest(source),'source_gameplay_unchanged':True,'original_run_manifest_sha256':digest(a.run/'run.json'),
  'mechanical_checks':counts,'episodes':episodes,'inventory':inv,'continuous_workflow':workflow,'metrics':metrics,
  'rubric_version':VERSION,'rubrics':axes,'rubric_subcriteria':subscores,'invalid_judge_repairs':repairs,
  'judge_model':'gpt-5.6-sol','tested_generation_model':'gpt-6-astra','same_model_family':True,
  'limitations':['Manual compile adaptation prevents autonomous model-baseline interpretation.',
   'Single fixture and same-family machine judges; cross-level calibration is not established by this pilot.',
   'Reference image and projected boxes are uncalibrated 2D proxies; no independent 3D ground truth.',
   'Static support and sampled door clearance do not certify all scene penetrations or continuous safety.',
   'Weights between dimensions are undecided; no total score is manufactured.']}
 write_json(root/'report.json',report)
 files={}
 for base in [root/'workspace/calibration',*[w/t.replace('.','_') for t in DOORS],flow,w/'inventory-002',w/'native',root/'metrics',a.review,*([a.repair] if a.repair else [])]:
  for path in base.rglob('*'):
   if path.is_file() and path.suffix in {'.json','.jsonl','.png'}:files[str(path)]=digest(path)
 files[str(w/'geometry/geometry.json')]=digest(w/'geometry/geometry.json')
 write_json(root/'evidence-manifest.json',{'report_sha256':digest(root/'report.json'),'files':files})
 print(json.dumps({'checks':counts,'inventory':{k:inv[k] for k in ['passed','total']},'workflow':observed==expected,'rubrics':axes},ensure_ascii=False))

if __name__=='__main__':main()
