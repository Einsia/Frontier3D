"""L1 image reconstruction: L2 appearance quality with independent validity gates."""
from math import isfinite
from statistics import mean

from .l1_edit_validity import UNKNOWN, MATERIAL_METRICS, combine, gate, system_gate
from .l2_reference_image import METHOD

PROFILE = 'l1-reference-visual-v2.0.0'
PROFILES = {'l1-reference-visual-v1.0.0', PROFILE}
WEIGHTS = {'main_image': .8, 'render_validity': .2}
PREREQUISITES = ('execution', 'artifacts', 'real_geometry', 'integrity')
SYSTEM_METRICS = MATERIAL_METRICS | {'main_render_consistency', 'render_validity', 'seed_success'}
SYSTEM_PATHS = {'/scene/has_real_geometry', '/scene/render_settings/has_camera',
                '/scene/render_settings/effective_resolution', '/artifacts/main.png/loadable',
                '/artifacts/main.png/validation_io/size', '/artifacts/main.png/validation_io/format',
                '/artifacts/scene.glb/loadable', '/artifacts/README.md/loadable'}


def visual_only(raw):
    return raw.get('l1_image_quality', {}).get('version') == PROFILE


def validate(policy, raw, checks):
    if (raw.get('profile') != 'L1' or raw.get('mode') != 'reference' or 'l1_edit_quality' in raw
            or not raw.get('l1_protocol') or set(policy) != {'version', 'weights', 'method',
                'image_checks', 'system_checks', 'scope', 'seed_aggregation'}
            or policy['version'] not in PROFILES or policy['weights'] != WEIGHTS
            or policy['method'] != METHOD or policy['seed_aggregation'] != 'minimum'
            or policy['scope'] != 'declared_primary_view_only'):
        raise ValueError('Invalid L1 reference visual scoring policy')
    images, systems = policy['image_checks'], policy['system_checks']
    ids = images + systems
    if (not images or not systems or len(set(ids)) != len(ids)
            or any(n not in checks or not checks[n].applicable for n in ids)):
        raise ValueError('Image and validity checks must be explicit, unique and applicable')
    expected_images = {n for n,c in checks.items() if c.applicable and c.metric == 'native_image_pair'}
    mandatory_systems = {n for n,c in checks.items() if c.applicable and
                        (c.metric in SYSTEM_METRICS or c.metric == 'equals' and c.params.get('path') in SYSTEM_PATHS)}
    if set(images) != expected_images or set(systems) != mandatory_systems:
        raise ValueError('Image quality cannot omit measured views or mandatory validity checks')
    if any(checks[n].pass_threshold != 0 for n in images):
        raise ValueError('Image similarity has no passing threshold')
    seeds = [n for n,c in checks.items() if c.applicable and c.metric == 'all_seed_checks']
    if len(seeds) != 1 or set(raw['critical_constraints']) != set(systems + seeds):
        raise ValueError('Only delivery/system checks and seed validity may gate image quality')


def selected_ids(policy):
    return set(policy['image_checks'] + policy['system_checks'])


def image_score(policy, checks):
    values = []
    for name in policy['image_checks']:
        row = checks.get(name, {})
        score = row.get('score')
        if (row.get('measurement_status', row.get('status')) not in {'passed', 'failed'}
                or type(score) not in (int, float) or not isfinite(score) or not 0 <= score <= 1
                or row.get('details', {}).get('method') != METHOD):
            return None
        values.append(score)
    return mean(values)


def apply(report, spec, evidence):
    policy = spec.to_dict()['l1_image_quality']
    checks = {c['id']: c for m in report['modules'].values() for c in m['checks']}
    base = image_score(policy, checks)
    seed_check = next(c for c in checks.values() if c['metric'] == 'all_seed_checks')
    seeds = seed_check.get('details', {}).get('per_seed', {})
    complete = set(seeds) == {str(s) for s in spec.seeds}
    values = [base] + [s.get('image_score') for s in seeds.values()]
    similarity = min(values) if complete and all(type(v) in (int,float) and isfinite(v) and 0 <= v <= 1 for v in values) else None
    gates = {k: report['gates'][k] for k in PREREQUISITES}
    gates.update({n: system_gate(checks[n]) for n in policy['system_checks']})
    gates['image_measurement'] = gate('passed' if similarity is not None else 'not_measurable')
    gates['all_seeds'] = gate(combine(s['status'] for s in seeds.values()) if complete else 'not_measurable')
    failed = any(g.get('measurement_status') == 'failed' for g in gates.values())
    valid = all(g.get('passed') is True for g in gates.values())
    status = 'scored' if valid else 'system_invalid' if failed else 'infrastructure_error' if any(
        g.get('measurement_status') == 'infrastructure_error' for g in gates.values()) else 'not_measurable'
    score = .8 * similarity + .2 if valid else 0. if failed else None
    measurements = []
    for row in checks.values():
        system = row['id'] in policy['system_checks'] or row['metric'] == 'all_seed_checks'
        item = {**row, 'status': row['measurement_status'], 'affects_eligibility': system,
                'affects_quality': row['id'] in policy['image_checks']}
        if row['id'] in policy['system_checks']:
            item['eligibility_status'] = gates[row['id']]['measurement_status']
        if row['measurement_status'] in UNKNOWN:
            item.update(score=None, passed=None)
        measurements.append(item)
    diagnostic = [r for r in measurements if not r['affects_eligibility'] and not r['affects_quality']]
    report.update(method_version=policy['version'], score_policy=policy['version'], status=status,
        score_valid=valid, case_pass=valid, G=int(valid), S_core=score, S_level=score,
        quality_threshold=None, similarity_threshold=None, full_task_verified=False,
        case_pass_meaning='System validity only; no image similarity or CAD completion threshold',
        main_image_comparison={'status':'measured' if similarity is not None else 'not_measurable',
            'score':similarity, 'baseline_score':base, 'method':METHOD,
            'per_view':{n:checks[n]['details'] for n in policy['image_checks']},
            'per_seed':{s:r.get('image_score') for s,r in seeds.items()},
            'aggregation':'minimum of baseline and all seeds; mean over declared scored views'},
        score_components={'main_image':similarity, 'main_image_weight':.8, 'data_weight':0.,
            'render_validity':1. if valid else 0. if failed else None, 'render_validity_weight':.2,
            'main_image_contribution':.8*similarity if valid else 0. if failed else None,
            'render_validity_contribution':.2 if valid else 0. if failed else None},
        legacy_gates=report['gates'], gates=gates, measurements=measurements,
        diagnostic_requirements={'count':len(diagnostic), 'affects_main_score':False,
            'failed':[r['id'] for r in diagnostic if r['status']=='failed'],
            'unverified':[r['id'] for r in diagnostic if r['status'] in UNKNOWN]},
        system_failures=[n for n,g in gates.items() if g.get('measurement_status')=='failed'],
        unverified_system_checks=[n for n,g in gates.items() if g.get('measurement_status') in UNKNOWN],
        protocol={'evaluation_mode':'render_and_reference_similarity', 'quality':METHOD,
            'main_image_weight':.8, 'render_validity_weight':.2, 'data_weight':0.,
            'minimum_similarity':None, 'seed_aggregation':'minimum',
            'seeds':list(spec.seeds), 'render_views':list(spec.render_views)},
        score_scope='80% declared primary-view native appearance + 20% render/delivery validity',
        score_interpretation='Pilot visual reconstruction score, not complete CAD verification',
        formal_score_eligible=False)
    report['limitations'] += ['Only the declared primary assembled view contributes; additional input views remain unscored.',
        'Appearance uses L2 native-appearance-v1; no semantic understanding or hidden-geometry guarantee.',
        'Dimensions, topology, assembly, non-bitmap material assignment and other content checks are diagnostic only.']
    if visual_only(spec.to_dict()):
        report['protocol'].update(reproduction='independent_render_and_integrity_per_seed',
            geometry_equivalence='not_measured', cross_format_appearance='not_measured')
        report['limitations'].append('CAD/GLB equivalence, numerical and assembly diagnostics were not collected in visual v2.')
    return report
