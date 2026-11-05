"""Aggregate corrected measurements using the original task-mode weights."""
import copy,time,hashlib,os
from pathlib import Path
from .policy import ROOT,read,write
from .reference_review import OUT
from harness.L3.MinecraftVillage.algorithm_scores import blend

def observable_reference(ref,eligibility):
    """Apply the same reference-only eligibility mask to every model."""
    if ref['checklist_sha256']!=eligibility['checklist_sha256']:raise ValueError('Eligibility checklist mismatch')
    output=copy.deepcopy(ref);checks=eligibility['criteria'];objects=[]
    for target in output['objects']:
        target['features']=[f for f in target['features'] if checks['object/'+target['id']+'/'+f['id']]['eligible']]
        if not target['features']:continue
        target['values']={f['id']:target['values'][f['id']] for f in target['features']}
        target['score']=sum(target['values'].values())/len(target['values']);objects.append(target)
    if not objects:raise ValueError('No observable reference object population')
    den=sum(o['weight'] for o in objects)
    for target in objects:target['weight']=target['weight']/den*100
    output['objects']=objects;output['objects_score']=sum(t['weight']/100*t['score'] for t in objects)
    output['environment_values']={k:v for k,v in output['environment_values'].items() if checks['environment/'+k]['eligible']}
    if not output['environment_values']:raise ValueError('No observable reference environment population')
    output['environment_score']=sum(output['environment_values'].values())/len(output['environment_values'])
    output['excluded_nonvisual_criteria']={k:v for k,v in checks.items() if not v['eligible']}
    return output

def applicable_motion(physical,roles,actions):
    """A light toggle or climbing a fixed ladder need not move that object.

    Inventory transitions are checked by real geometry/inventory predicates;
    no visible rigid trajectory is not itself a failed collision trajectory.
    Doors, lifts, carts and other prescribed moving mechanisms must move.
    """
    from collections import defaultdict
    optional={'switch','light','ladder','lever','valve','tap','fruit','consumable','key','keycard','filter','cargo','tool','part','movable'}
    values={};not_applicable={};groups=defaultdict(list)
    for key,row in physical['motion']['targets'].items():
        role=roles.get(key,key)
        inventory_container=role=='container' and not {'open','close'}.intersection(actions.get(key,[]))
        if not row['moving_components'] and not row['overlaps'] and not row['unresolved'] and (role in optional or inventory_container):
            not_applicable[key]='No visible rigid motion; electrical/navigation/inventory state change is scored by its physical outcome tests.';continue
        value=0. if row['overlaps'] else None if row['unresolved'] else float(bool(row['sampled_clear'] and row['moving_components']))
        values[key]=value;groups[role].append(value)
    scores={k:sum(v)/len(v) if all(x is not None for x in v) else None for k,v in groups.items()}
    return {'score':sum(scores.values())/len(scores) if scores and all(x is not None for x in scores.values()) else None,
            'targets':values,'roles':scores,'not_applicable':not_applicable,'method':'required_mechanism_motion_and_observed_carried_motion_v2'}

def summarize(task,run,include_reference=True):
    model=run['model'];slug=model.removeprefix('gpt-6-');key=task['key']
    old_folder=Path(os.environ['L3_EVAL_OUT'])/key if os.environ.get('L3_EVAL_OUT') else ROOT/'data/l3/evaluations'/('suite-'+slug+'-v1')/key
    original=read(old_folder/'summary.json')
    folder=OUT/key/model;physical=read(folder/'physical/physical-summary.json')
    from .physical_v2 import VERSION
    if physical['version']!=VERSION:raise ValueError('Physical policy refresh pending')
    result=copy.deepcopy(original);axes=result['axes']
    workflow=None
    wm=old_folder/'workflow-metadata.json'
    needs_replay=wm.exists() and any(r['reason']=='operation outside public contract' for r in read(wm).get('rejected',[]))
    if needs_replay:
        replay=folder/'workflow-replay'
        if read(replay/'run.json')['status']!='completed':raise ValueError('Workflow replay not complete')
        workflow=read(replay/'interaction-observations.json')
        physical['motion']=read(replay/'motion.json')
    values=dict(axes['layout']['values']);values.update(support=physical['support']['score'],penetration=physical['penetration']['score'])
    if workflow:values['navigation']=workflow['navigation']
    axes['layout']=blend(values,axes['layout']['weights'])
    from .physical_batch_v2 import inputs
    _,roles,_,_=inputs(key,slug)
    contract_path=old_folder/'contract.json'
    actions={e['id']:e['actions'] for e in read(contract_path)['entities']} if contract_path.exists() else {k:['open','close'] for k in roles}
    motion=applicable_motion(physical,roles,actions);write(folder/'motion-applicability.json',motion)
    values=dict(axes['interaction']['values']);values['motion']=motion['score']
    if workflow:values['state_and_workflow']=workflow['state_and_workflow']
    axes['interaction']=blend(values,axes['interaction']['weights'])
    if task['input_mode']=='image' and include_reference:
        ref=read(folder/'feature-review.json')
        if ref['method']!='l3-reference-core-features-v3':raise ValueError('Wrong frozen feature protocol')
        eligibility=read(OUT/'feature-v3-references'/key/'eligibility.json')
        if 'scope' not in eligibility:raise ValueError('Reference object-group eligibility audit pending')
        ref=observable_reference(ref,eligibility)
        write(folder/'reference-eligibility.json',eligibility);write(folder/'reference-score.json',ref)
        if ref['source_sha256']!=original['source']['source_sha256']:raise ValueError('Reference source does not match frozen submission')
        for name in ['environment','objects']:axes[name]={'score':ref[name+'_score'],'method':ref['method']}
        axes['objects'].update(values={o['id']:o['score'] for o in ref['objects']},weights={o['id']:o['weight']/100 for o in ref['objects']})
        axes['environment'].update(values=ref['environment_values'],weights={k:1/len(ref['environment_values']) for k in ref['environment_values']})
        result['reference_features']={'environment':[{'id':k,'score':v,'criterion':next(e['criterion'] for e in read(ref['reference_only_checklist'])['environment'] if e['id']==k)} for k,v in ref['environment_values'].items()],
            'objects':ref['objects'],'verdict':ref['verdict'],'checklist_sha256':ref['checklist_sha256']}
    observations=workflow or (read(old_folder/'interaction-observations.json') if (old_folder/'interaction-observations.json').exists() else None)
    if observations:
        result['playability']={'goals':observations['goals'],'walks':observations['walks'],'door_walks':observations['door_walks'],
            'continuous_workflow':observations['continuous_workflow'],'route_success_fraction':observations['route_success_fraction'],
            'resource_state':observations['resource_state'],'rejected_route_steps':observations['rejected_route_steps']}
        result.setdefault('counts',{}).update(required_entities=len(roles),navigation_segments=len(observations['walks']),
            workflow_passed_predicates=sum(x['passed'] for x in observations['goals']),workflow_predicates=len(observations['goals']))
    total=blend({k:v['score'] for k,v in axes.items()},original['weights'])
    result.update(protocol='l3-evidence-aligned-v2',score_100=total['score']*100 if total['score'] is not None else None,
                  missing_axes=total['missing'],status='measured' if total['score'] is not None else 'incomplete',
                  completed_unix=time.time(),evidence_files=['physical/physical-summary.json','physical/physical-input.json','motion-applicability.json']+
                  (['feature-review.json','reference-eligibility.json','reference-score.json'] if task['input_mode']=='image' and include_reference else [])+
                  (['workflow-replay/interaction-observations.json','workflow-replay/run.json','workflow-replay/motion.json'] if workflow else []),
                  aggregation_policy='Task-mode weights; asset-level physical measurements and observable reference fidelity.',
                  measurement_families=['independent physical geometry','local physical interactions','continuous workflow','reference features','anchored aesthetics/prompt/style rubrics'],
                  runtime_evidence_path=str(old_folder),
                  implementation_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [__import__('pathlib').Path(__file__),__import__('pathlib').Path(__file__).with_name('physical_v2.py'),__import__('pathlib').Path(__file__).with_name('feature_review_v3.py')]})
    result['evidence_sha256']={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in result['evidence_files']}
    write(folder/'summary.json',result);return result

if __name__=='__main__':
    data=read(OUT/'input-catalogue.json');rows=[];errors={}
    for task in data['tasks']:
        if task.get('level')!=3:continue
        for run in task['generation_runs']:
            try:rows.append(summarize(task,run))
            except Exception as exc:
                errors[task['key']+'/'+run['model']]=str(exc)
                stale=OUT/task['key']/run['model']/'summary.json'
                if stale.exists():stale.rename(stale.with_name('summary-incomplete-archive-'+str(time.time_ns())+'.json'))
    write(OUT/'aggregation-progress.json',{'completed':len(rows),'total':45,'errors':errors})
    print('complete',len(rows),'errors',errors)
