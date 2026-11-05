"""Versioned CodeEdit quality: numeric 40%, native target 40%, preservation 20%."""
from math import isfinite
from statistics import mean

from .l1_edit_validity import MATERIAL_METRICS, UNKNOWN, assignment_score, combine, gate, system_gate

PROFILE = 'l1-codeedit-quality-v1.2.0'
MEASUREMENT_PROFILES = {PROFILE, 'l1-codeedit-quality-v1.0.0', 'l1-codeedit-quality-v1.1.0'}
WEIGHTS = {'numeric':.4, 'target':.4, 'preservation':.2}
SYSTEM_METRICS = {'procedural_materials','procedural_material_sequence','main_render_consistency'}


def validate(policy, raw, checks):
    if (raw.get('profile') != 'L1' or raw.get('mode') != 'edit' or not raw.get('reference_scene')
            or not raw.get('baseline_scene') or 'l1_protocol' not in raw
            or set(policy) != {'version','weights','numeric_groups','target_checks','preservation_groups',
                              'system_checks','surface','pending_numeric_requirements','scope'}
            or policy['version'] not in MEASUREMENT_PROFILES or policy['weights'] != WEIGHTS):
        raise ValueError('Invalid CodeEdit quality policy')
    surface = policy['surface']
    if (set(surface) != {'dimension_m','preserve_m','samples'}
            or surface['dimension_m'] != raw['tolerances']['dimension_m']
            or surface['preserve_m'] != raw['tolerances']['preserve_m']
            or type(surface['samples']) is not int or not 256 <= surface['samples'] <= 16384):
        raise ValueError('Invalid edit surface precision/sampling policy')
    groups = [*policy['numeric_groups'].values(),policy['target_checks'],*policy['preservation_groups'].values(),policy['system_checks']]
    ids = [name for group in groups for name in group]
    if (not policy['numeric_groups'] or not policy['preservation_groups']
            or any(not group or len(group)!=len(set(group)) for group in groups)
            or len(ids)!=len(set(ids)) or any(name not in checks or not checks[name].applicable for name in ids)):
        raise ValueError('Quality checks must be unique, applicable and explicitly grouped')
    if any(checks[n].metric not in SYSTEM_METRICS | {'render_validity','seed_success'} for n in policy['system_checks']):
        raise ValueError('Content requirements cannot become CodeEdit system gates')
    if any(checks[n].metric != 'edit_surface' or checks[n].params['feature'] != 'target' for n in policy['target_checks']):
        raise ValueError('CodeEdit target requires native surface measurements')
    if not isinstance(policy['pending_numeric_requirements'],list):
        raise ValueError('Pending numeric requirements must remain explicit')


def selected_ids(policy):
    return set(policy['system_checks']+policy['target_checks']+
               [n for groups in ('numeric_groups','preservation_groups') for ids in policy[groups].values() for n in ids])


def components(policy, checks):
    def value(ids):
        values = []
        for name in ids:
            row = checks.get(name,{})
            score = row.get('score')
            if (row.get('measurement_status',row.get('status')) not in {'passed','failed'}
                    or type(score) not in (int,float) or not isfinite(score) or not 0 <= score <= 1):
                return None
            values.append(score)
        return min(values)
    numbers = {name:value(ids) for name,ids in policy['numeric_groups'].items()}
    preserved = {name:value(ids) for name,ids in policy['preservation_groups'].items()}
    # One explicit content group, paired across native/GLB and declared states.
    # Missing assignments deduct here, without diluting the numeric 40%.
    preserved['material_assignment'] = assignment_score(checks)
    average = lambda rows:mean(rows) if rows and all(v is not None for v in rows) else None
    return {'numeric':average(list(numbers.values())), 'target':value(policy['target_checks']),
            'preservation':average(list(preserved.values()))}


def apply(report, spec, evidence):
    policy = spec.to_dict()['l1_edit_quality']
    checks = {c['id']:c for module in report['modules'].values() for c in module['checks']}
    base = components(policy,checks)
    seed_check = next(c for c in checks.values() if c['metric']=='all_seed_checks')
    seeds = seed_check.get('details',{}).get('per_seed',{})
    complete_seeds = set(seeds)=={str(s) for s in spec.seeds}
    combined = {}
    for key in WEIGHTS:
        values = [base[key]]+[v.get('edit_components',{}).get(key) for v in seeds.values()]
        combined[key] = min(values) if complete_seeds and all(v is not None for v in values) else None
    gates = {k:v for k,v in report['gates'].items() if k in {'execution','artifacts','real_geometry','integrity','infrastructure'}}
    for name in policy['system_checks']:
        row = checks[name]
        gates[name] = system_gate(row)
    gates['all_seeds'] = gate(combine(v['status'] for v in seeds.values()) if complete_seeds
                             else 'not_measurable',
                             details=seed_check.get('details', {}),
                             meaning='All seed system checks; content errors only reduce quality')
    unavailable = any(v is None for v in combined.values()) or any(
        g.get('measurement_status') in {'not_measurable','infrastructure_error','not_implemented'} for g in gates.values())
    failed_system = any(g.get('measurement_status')=='failed' for g in gates.values())
    valid = all(g['passed'] for g in gates.values()) and not unavailable
    quality = sum(WEIGHTS[k]*v for k,v in combined.items()) if all(v is not None for v in combined.values()) else None
    score = sum(WEIGHTS[k]*v for k,v in combined.items()) if valid else 0. if failed_system else None
    quality_ids = selected_ids(policy)-set(policy['system_checks'])
    measurements = [{**c,'status':c['measurement_status'],
                     'affects_quality':c['id'] in quality_ids,
                     'affects_eligibility':c['id'] in policy['system_checks'] or c['metric']=='all_seed_checks',
                     **({'eligibility_status':system_gate(c)['measurement_status'],
                         'quality_scope':'See separate material_assignment content measurement'}
                        if c['metric'] in MATERIAL_METRICS else {})}
                    for c in checks.values()]
    assigned = assignment_score(checks)
    measurements.append({'id':'material_assignment','metric':'material_assignment',
        'status':'not_measurable' if assigned is None else 'passed' if assigned==1 else 'failed',
        'measurement_status':'not_measurable' if assigned is None else 'passed' if assigned==1 else 'failed',
        'score':assigned,'passed':None if assigned is None else assigned==1,
        'affects_quality':True,'affects_eligibility':False,
        'details':{'aggregation':'Minimum assigned material-use fraction across native, GLB and native states',
                   'preservation_group_count':len(policy['preservation_groups'])+1}})
    for row in measurements:
        if row['measurement_status'] in UNKNOWN:
            row.update(score=None,passed=None)
    content_failed = [c['id'] for c in measurements if c['affects_quality'] and c['measurement_status']=='failed']
    content_unverified = [c['id'] for c in measurements if c['affects_quality'] and c['measurement_status'] in UNKNOWN]
    for name,seed in seeds.items():
        if any(v is not None and v < 1-1e-8 for v in seed.get('edit_components',{}).values()):
            content_failed.append('seed_'+name+'_quality')
        content_unverified.extend('seed_'+name+'/'+n for n in seed.get('unverified_checks', []))
    rows = []
    for name,ids in policy['numeric_groups'].items():
        group_checks = [checks[i] for i in ids]
        measured = all(c['measurement_status'] in {'passed','failed'} for c in group_checks)
        rows.append({'id':name,'check_ids':ids,'status':'measured' if measured else 'not_measurable',
                     'passed':all(c['passed'] for c in group_checks) if measured else None,
                     'measurements':[{'id':c['id'],'params':c['params'],'details':c['details']} for c in group_checks]})
    report.update(method_version=PROFILE,score_policy=PROFILE,S_core=score,S_level=score,
                  case_pass=valid,score_valid=valid,G=int(valid),
                  status='scored' if valid else 'system_invalid' if failed_system else
                         'infrastructure_error' if any(g.get('measurement_status')=='infrastructure_error' for g in gates.values())
                         else 'not_measurable',
                  measurement_profile=policy['version'],
                  score_components={**combined,'numeric_weight':.4,'similarity_weight':.4,'preservation_weight':.2,
                                    'main_image_weight':0.,'main_image':None},
                  baseline_score_components=base,
                  material_assignment={'baseline_score':assignment_score(checks),
                      'aggregation':'One equal-weight group within preservation; minimum across formats/states/seeds',
                      'preservation_group_count':len(policy['preservation_groups'])+1},
                  quality_score=quality,quality_threshold=None,
                  case_pass_meaning='System validity only; edit content is continuously scored',
                  main_image_comparison={'status':'not_in_scope','score':None},
                  measurements=measurements,
                  content_requirements={'passed':not content_failed and not unavailable,
                      'failed':content_failed,'unverified':content_unverified,'count':len(quality_ids)+1,
                      'affects_eligibility':False,'affects_quality':True},
                  protocol={'evaluation_mode':'native_edit_target_quality',
                      'numeric_weight':.4,'similarity_weight':.4,'preservation_weight':.2,
                      'main_image_weight':0.,'minimum_quality':None,
                      'aggregation':'minimum_per_component_across_baseline_and_all_seeds'},
                  legacy_gates=report['gates'],gates=gates,
                  numeric_requirements={'status':'partial','supported':len(rows),
                      'total':len(rows)+len(policy['pending_numeric_requirements']),
                      'requirements':rows,'pending':policy['pending_numeric_requirements'],
                      'count_scope':'implemented_check_groups_plus_unmapped_design_landmarks_not_full_clause_count'},
                  score_scope=policy['scope'],formal_score_eligible=False,
                  score_interpretation='Pilot quality score; incomplete CAD coverage remains explicit.',
                  full_task_verified=report['task_completion']=='complete' and valid)
    report['system_failures'] = [name for name,g in gates.items() if g['measurement_status']=='failed']
    report['unverified_system_checks'] = [name for name,g in gates.items() if g['measurement_status'] in UNKNOWN]
    for name,weight in WEIGHTS.items():
        report['score_components'][name+'_contribution'] = weight*combined[name] if valid else 0. if failed_system else None
    report['limitations'].append('Finite surface samples do not prove exact CAD dimensions; pending measurements remain unverified.')
    return report
