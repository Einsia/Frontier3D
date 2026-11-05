"""Versioned pilot aggregation; infrastructure missingness is never a zero.

Weights are task-mode constants, not adjusted to results. Measurements retain
their scope and raw diagnostics. No claim of independently calibrated scores.
"""
from collections import defaultdict
import math
from .protocol import DOORS, CHESTS, CROPS, BLOCKS, FURNACES, read_json

POLICY = {
    'version':'l3-algorithm-first-v1-weights2',
    'image_weights':{'layout':.20,'interaction':.15,'environment':.20,'objects':.30,'rubric':.15},
    'text_weights':{'layout':.25,'interaction':.35,'rubric':.40},
    'layout_weights':{'support':.25,'penetration':.25,'navigation':.30,'semantic':.20},
    'interaction_weights':{'local':.40,'motion':.25,'state_and_workflow':.35},
    'image_rubric_weights':{'beauty':.4,'prompt_alignment':1/3,'style_consistency':4/15},
    'text_rubric_weights':{'beauty':.25,'prompt_alignment':.5,'style_consistency':.25},
    'static_overlap_policy':'same-actor static assembly union; terrain/path/water composites; all moving mechanisms and independent actors checked',
    'formal_score_eligible':False,
}


def average(values):
    values=list(values)
    return sum(values)/len(values) if values and all(v is not None for v in values) else None


def blend(values, weights):
    if not math.isclose(sum(weights.values()),1,abs_tol=1e-9):raise ValueError('Weights must sum to one')
    known={k:values.get(k) for k in weights}
    if any(v is not None and (type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1) for v in known.values()):
        raise ValueError('Finite unit scores required')
    missing=[k for k,v in known.items() if v is None]
    lower=sum(weights[k]*v for k,v in known.items() if v is not None)
    return {'score':None if missing else lower,'lower_bound':lower,
            'upper_bound':lower+sum(weights[k] for k in missing),'missing':missing,
            'values':known,'weights':weights}


def group_name(actor):
    if actor.startswith('building.'):return 'buildings'
    if actor in DOORS:return 'doors_and_gate'
    if actor in CHESTS:return 'containers'
    if actor in CROPS:return 'crops'
    if actor in BLOCKS:return 'editable_blocks'
    if actor in FURNACES:return 'furnaces'
    return actor.split('.')[0]


def macro(rows):
    groups=defaultdict(list)
    for actor,value in rows.items():groups[group_name(actor)].append(value)
    values={k:average(v) for k,v in groups.items()}
    return {'score':average(values.values()),'groups':values,'actors':rows}


def rigid_coverage(static):
    """Classify engine drawing helpers separately from unexported solid meshes.

    Exact engine classes only, not names, tags or actor claims. Text glyphs and
    debugger draw proxies remain visual evidence; this metric measures solids.
    Unknown classes and unresolved mesh intersections stay incomplete.
    """
    non_solid={'GameplayDebuggerRenderingComponent':'engine debug drawing proxy',
               'TextRenderComponent':'engine planar text glyph renderer'}
    excluded=[];unknown=[]
    for row in static.get('unexported_components',[]):
        reason=non_solid.get(row.get('class'))
        if reason:excluded.append({**row,'scope_reason':reason})
        else:unknown.append(row)
    complete=(static.get('unresolved_pair_count')==0 and not unknown)
    return {'exported_solids_complete':complete,'non_solid_renderers':excluded,
            'unexported_unknown':unknown,'raw_export_complete':static.get('measurement_complete'),
            'scope':'exported solid volumes; planar text and engine debug drawings excluded'}


def layout(geometry, physical, workflow, visual, door_walk=None,journey=None):
    support=geometry.get('support',{})
    raw=support.get('raw_l2',{})
    support_rows={r['actor']:1-r['unsupported_piece_count']/max(1,r['connected_piece_count']) for r in support.get('actors',[])}
    support_score=macro(support_rows)
    if raw.get('status')!='measured':support_score['score']=None
    stat=geometry.get('static',{})
    roles={i['actor']:i.get('role','') for i in physical['instances']}
    moving=set(DOORS+CHESTS); composite={'terrain','path','water'}
    bad=set();excluded=[];violations=[]
    for row in stat.get('overlaps',[]):
        a,b=row['left'][0],row['right'][0]
        reason=None
        if a==b and a not in moving:reason='static assembly represented as union'
        elif roles.get(a) in composite and roles.get(b) in composite:reason='terrain/path/water composition'
        elif roles.get(a)=='water' or roles.get(b)=='water':reason='fluid visual volume is not a rigid obstacle'
        if reason:excluded.append({**row,'rule':reason})
        else:violations.append(row);bad.update([a,b])
    penetration=macro({a:float(a not in bad) for a in roles if roles[a]!='water'})
    coverage=rigid_coverage(stat)
    if not coverage['exported_solids_complete']:penetration['score']=None
    # Route outcome is independent pawn motion, not a claimed navmesh property.
    door_nav=average(float(door_walk['targets'][t]['opened_passage']) for t in DOORS) if door_walk and door_walk.get('status')=='measured' else None
    journey_nav=float(journey['passed']) if journey and 'passed' in journey else None
    nav=average([door_nav,journey_nav])
    semantic=visual.get('axes',{}).get('layout_semantics')
    result=blend({'support':support_score['score'],'penetration':penetration['score'],
                  'navigation':nav,'semantic':semantic},POLICY['layout_weights'])
    result.update(support=support_score,penetration={**penetration,'violations':violations,'allowed_composition':excluded,'coverage':coverage},
                  navigation={'door_traversal':door_nav,'public_journey':journey_nav,'continuous_workflow':workflow.get('route_success_fraction')},
                  limitations=['Support is connectivity, not load stability.',
                               'Static assembly internal volumes are union geometry; navigability checks usable voids separately.',
                               'Geometry extraction coverage, semantic grouping and tolerances require human calibration.'])
    return result


def interaction(run, geometry, workflow, resource, door_walk=None):
    categories=[DOORS,CHESTS,CROPS,BLOCKS,FURNACES];targets={}
    excluded={'real_geometry','negative_call_reached_candidate','action_path_accepted','harvest_accepted','remove_accepted',
              'sampled_intermediate_motion'}
    for group in categories:
        for target in group:
            key=target.replace('.','_');episode=run.get('episodes',{}).get(key,{})
            if key in run.get('submission_contract_failures',{}):
                targets[target]={'score':0.,'status':'submission_contract_failure'};continue
            if not episode.get('completed'):
                targets[target]={'score':None,'status':'not_measured'};continue
            d=episode.get('diagnostics',{});checks={k:v for k,v in d.get('checks',{}).items() if k not in excluded}
            if target in DOORS and door_walk and door_walk.get('status')=='measured':
                actual=door_walk['targets'][target]
                for k in ['closed_barrier','opened_passage','closed_again','actual_walk_through']:checks[k]=actual[k]
            # An invalid door probe is not relabelled as a physical failure.
            # Retain missingness; the independent walk test remains measurable.
            iv=episode.get('inventory',{}).get('checks',{})
            # These local snapshots test resource effects and negative conditions.
            inventory=average(None if r.get('passed') is None else float(r['passed']) for r in iv.values())
            geometry_value=average(None if v is None else float(v) for v in checks.values())
            value=average([geometry_value,inventory]) if target in CHESTS+CROPS+FURNACES else geometry_value
            targets[target]={'score':value,'checks':checks,'inventory_score':inventory,'status':'measured' if value is not None else 'partial'}
    category_scores={group_name(g[0]):average(targets[t]['score'] for t in g) for g in categories}
    local=average(category_scores.values())
    motion={}
    for t in DOORS+CHESTS:
        m=geometry.get('motion',{}).get('targets',{}).get(t,{})
        value=m.get('sampled_clear')
        if value is None and m.get('recorded_frames',0)>0 and not m.get('unresolved') and not m.get('moving_components'):
            # Adequate recorded evidence with no motion does not demonstrate a working mechanism.
            value=False
        motion[t]=None if value is None else float(value)
    motion_score=average([average(motion[t] for t in DOORS),average(motion[t] for t in CHESTS)])
    iv=resource.get('inventory',{})
    state=iv['passed']/iv['total'] if iv.get('total') and iv.get('unresolved',1)==0 else None
    flow=float(workflow['workflow_success']) if workflow.get('status')=='measured' else None
    sf=blend({'resource_state':state,'continuous_workflow':flow},{'resource_state':.5,'continuous_workflow':.5})
    state_flow=sf['score']
    result=blend({'local':local,'motion':motion_score,'state_and_workflow':state_flow},POLICY['interaction_weights'])
    if state_flow is None:
        weight=POLICY['interaction_weights']['state_and_workflow']
        result['lower_bound']+=weight*sf['lower_bound']
        result['upper_bound']-=weight*(1-sf['upper_bound'])
    result.update(targets=targets,categories=category_scores,motion=motion,local_resource_state=state,
                  continuous_workflow=flow,state_and_workflow=sf,continuous_clearance_certified=False,
                  limitations=['Motion uses recorded poses and actual mesh intersections, not a continuous-time proof.',
                               'A planner failure is unmeasured, not an interaction failure.'])
    return result


def summarize(run_path, physical_path, geometry_path, workflow, reference, visual, resource, mode='image',door_walk=None,journey=None):
    run=read_json(run_path);geometry=read_json(geometry_path);physical=read_json(physical_path)
    lay=layout(geometry,physical,workflow,visual,door_walk,journey);inter=interaction(run,geometry,workflow,resource,door_walk)
    rub=blend(visual.get('axes',{}),POLICY[mode+'_rubric_weights'])
    axes={'layout':lay,'interaction':inter,'rubric':rub}
    if mode=='image':
        for key in ['environment','objects']:
            value=reference.get(key+'_score')
            axes[key]={'score':value,'method':reference.get('method'),'scope':'algorithmic 2D proxy; human calibration pending'}
    total=blend({k:v['score'] for k,v in axes.items()},POLICY[mode+'_weights'])
    lo=sum(POLICY[mode+'_weights'][k]*(v.get('lower_bound',0) if v['score'] is None else v['score']) for k,v in axes.items())
    hi=sum(POLICY[mode+'_weights'][k]*(v.get('upper_bound',1) if v['score'] is None else v['score']) for k,v in axes.items())
    return {'protocol':POLICY['version'],'mode':mode,'policy':POLICY,'axes':axes,
            'pilot_score_100':None if total['score'] is None else 100*total['score'],
            'partial_bounds_100':[100*lo,100*hi],
            'missing_axes':total['missing'],'formal_score':None,'formal_score_eligible':False,
            'calibration':'provisional algorithmic pilot; reference annotations and cross-level human calibration pending'}
