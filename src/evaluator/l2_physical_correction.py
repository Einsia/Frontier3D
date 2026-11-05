"""Replace only the physical measurement in an immutable scored L2 report."""
import copy
import math

from .l2_embodied_scoring import WEIGHTS


def replace_physics(original,physics):
    if (physics.get('status') not in {'measured','not_measurable','not_applicable'}
            or type(physics.get('score')) not in (int,float)
            or not math.isfinite(physics['score']) or not 0<=physics['score']<=1):
        raise ValueError('Finite physical measurement required')
    weights=WEIGHTS.get(original.get('method_version'))
    if original.get('method_version')=='l2-reference-embodied-v4.0.0':
        weights={'main_image':.8,'render_validity':.1,'physics':.1}
    if not weights or original['score_components'].get('physics_weight')!=.1:
        raise ValueError('Only published 10% L2 physical profiles may be corrected')
    result=copy.deepcopy(original);c=result['score_components'];valid=result['score_valid']
    c.update(physics=physics['score'],physics_contribution=.1*physics['score'] if valid else 0.)
    quality=sum(weight*(c[name] or 0.) for name,weight in weights.items())
    result.update(physical_plausibility=physics,S_core=quality if valid else 0.,
                  S_level=quality,S_diagnostic=quality)
    if 'automatic_S_core' in result:result['automatic_S_core']=result['S_core']
    for item in result.get('measurements',[]):
        if item['id']=='physical_plausibility':
            item.update(score=physics['score'],passed=physics['score']>=1-1e-8,
                        status=physics['status'],details=physics)
    return result


def validate_correction(original,report,data):
    if (data.get('kind')!='physical_surface_completion' or data.get('new_model_calls')!=0
            or data.get('new_candidate_executions')!=0):
        raise ValueError('Invalid physical correction scope')
    expected=replace_physics(original,report['physical_plausibility'])
    allowed={'source_provenance','evidence_path','report_path','evaluation_kind',
             'new_model_calls','new_candidate_executions','new_blender_inspections','physical_correction'}
    if {k:v for k,v in report.items() if k not in allowed}!={k:v for k,v in expected.items() if k not in allowed}:
        raise ValueError('Physical correction changed unrelated grading or validity')
    checks=data.get('surface_checks',{})
    if (not checks.get('candidate') or not checks['candidate'].get('inventory_verified')
            or not checks['candidate'].get('source_unchanged')):
        raise ValueError('Physical correction lacks independently verified surface inventory')
    for check in checks.values():
        if not check.get('source_unchanged') or not check.get('inventory_verified'):
            raise ValueError('Physical correction source/inventory changed')
