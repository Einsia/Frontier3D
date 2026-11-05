"""Opt-in v3 L2 evidence rubric. Legacy/L1 v2 scoring is intentionally unchanged."""
import copy
from pathlib import PurePosixPath

from jsonschema import Draft202012Validator

from . import l2_rubric

PROTOCOL = '3dbench-l2-rubric-v3'
POLICY = 'case_specific_reference_fidelity_no_registration_v1'
CAPS = {'none': 4, 'minor': 3, 'major': 2, 'wrong_or_absent': 0, 'not_demonstrated': 0}
PROMPT = l2_rubric.PROMPT + '''
STRICT FIDELITY v3 overrides generic historical rubric sections in instruction.md, NOT the task's
permitted design freedoms. Use the frozen judge_spec.json weights and case-specific questions.
For EACH criterion, record achieved (specific observed agreement), discrepancies (largest actual
deviation, or explicitly no material discrepancy), and discrepancy_severity BEFORE the grade.
none permits 0..4, minor at most 3, major at most 2, wrong_or_absent and not_demonstrated require 0.
A missing identifying structure or wrong object category is wrong_or_absent, not a minor cosmetic
issue. Several primitive shapes do not establish the required object identity. A vague same-category
resemblance is at most 1. These are criterion-local quality bounds, never system-invalid gates.
Grade 4 requires all important visible properties of THAT criterion positively supported; do not
grant it because the candidate is attractive, complex, neatly rendered, or has matching object names.
Report actual visual comparisons, not code/metadata claims. A generic plausible room or clean layout
is insufficient for a reference reconstruction. Do not reward a redesign. Materials, lighting and
framing grades are fidelity to the original reference, not generic aesthetics. An alternate/diagnostic
view must not replace candidate/main.png for main-view appearance, composition or localization.
Every criterion must cite every file in its required_evidence list with a concrete observation.
The cross_view criterion explicitly compares ALL supplied original public reference images and BOTH
candidate authored views. With a single original image, do not invent an unseen original backside;
evaluate 3D consistency/visible thickness with the candidate alternate, not nonexistent pixel matches.
Generated closeups may clarify a visible feature. Neutral tool renders can reveal geometry but cannot
earn authored lighting, color or composition credit. Never rotate, translate, fit, register, crop away
errors or rescale candidate images to manufacture similarity. Inspect existing coordinates as supplied.
BRIEF freedoms remain genuine: do not impose any private target scene or image. Check each public
object's distinctive structure and each named access/connection relation; labels/AABBs alone are not
proof. Rough placeholders are not complete objects. Exact dimensions stay with the numeric evaluator.
EDIT: cite before, native target, public image and candidate main for EVERY criterion, including
preservation. Judge the explicit delta: unchanged missing geometry or unchanged wrong lighting earns
zero for that requested change even if most background pixels match. Preserve non-target content;
legitimate induced shadows/reflections and explicitly permitted changes are not errors. Do not demand
hidden reconstruction details, movement, readable text or people when the task allows their omission.
Use the allowed read-only native tools when supplied views cannot resolve a material question.
Technical missing/corrupt evidence is infrastructure_error, not a quality zero. Genuine non-demonstration
is a local grade 0; explain that hidden properties are unproven, not proven absent. Do not rerun a low
valid answer. No arbitrary global cap or forced low score distribution. Return protocol v3 schema JSON.
'''


def legacy_spec(spec):
    result = copy.deepcopy(spec)
    result['protocol'] = l2_rubric.PROTOCOL
    result.pop('fidelity_policy', None)
    result.pop('reference_views', None)
    result.pop('authoring', None)
    for row in result['checks']:
        row.pop('required_evidence', None)
    return result


def validate_spec(spec):
    from .protocol import object_schema, array, enum, TEXT, RATIO
    check = object_schema({'id':TEXT,'question':TEXT,'dimension':TEXT,
        'units':array(TEXT,minItems=1,uniqueItems=True),'weight':RATIO,
        'required_evidence':array(TEXT,minItems=1,uniqueItems=True)})
    schema = object_schema({'protocol':enum([PROTOCOL]),'case_id':TEXT,
        'family':enum(['Brief2Scene','SceneEdit','Reference2Scene','Reference2Scene-RealPhoto']),
        'instruction_sha256':TEXT,'reference_policy':TEXT,'focus':TEXT,
        'missing_policy':enum([l2_rubric.MISSING_POLICY]),
        'anchors':object_schema({str(i):TEXT for i in range(5)}),
        'checks':array(check,minItems=1),'localization':{'anyOf':[{'type':'object'},{'type':'null'}]},
        'fidelity_policy':enum([POLICY]),'reference_views':array(TEXT,uniqueItems=True),
        'authoring':enum(['primary_assistant_reference_only_ai_draft_human_calibration_pending'])})
    Draft202012Validator(schema).validate(spec)
    l2_rubric.validate_spec(legacy_spec(spec))
    refs = spec['reference_views']
    for name in refs:
        p = PurePosixPath(name)
        if (len(p.parts)!=2 or p.parts[0]!='reference' or not p.name.startswith('reference-')
                or p.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}):
            raise ValueError('Only packet original reference images may define reference views')
    brief = spec['family']=='Brief2Scene'
    if (brief and refs) or (not brief and not refs):
        raise ValueError('Brief forbids private references; comparison requires public reference views')
    cross = [c for c in spec['checks'] if c['id']=='cross_view']
    if len(cross)!=1 or not {'candidate/main.png','candidate/alternate.png',*refs} <= set(cross[0]['required_evidence']):
        raise ValueError('cross_view must cover both candidate views and ALL public reference views')
    allowed = {'candidate/main.png','candidate/alternate.png','candidate/novel.png',*refs}
    if spec['family']=='SceneEdit': allowed |= {'reference/before.png','reference/target.png'}
    for row in spec['checks']:
        required = set(row['required_evidence'])
        if not required <= allowed or 'candidate/main.png' not in required:
            raise ValueError('Every criterion requires authored main-view evidence')
        if refs and refs[0] not in required:
            raise ValueError('Every comparison criterion requires the primary original reference')
        if spec['family']=='SceneEdit' and not {'reference/before.png','reference/target.png'} <= required:
            raise ValueError('Every edit criterion requires explicit before AND native target')
    expected = {'Brief2Scene':{'instruction_following':.6,'aesthetics':.4},
        'SceneEdit':{'edit_fulfilment':.5,'target_similarity':.3,'preservation':.2}}.get(
            spec['family'], {'reference_fidelity':.4,'reference_layout':.3,'reference_appearance':.3})
    actual = {}
    for c in spec['checks']: actual[c['dimension']] = actual.get(c['dimension'],0)+c['weight']
    if set(actual)!=set(expected) or any(abs(actual[k]-v)>1e-9 for k,v in expected.items()):
        raise ValueError('Category internal weights must remain unchanged')
    return spec


def response_schema(spec, evidence_paths):
    from .protocol import TEXT, enum
    schema = l2_rubric.response_schema(legacy_spec(spec), evidence_paths)
    schema['properties']['protocol'] = enum([PROTOCOL])
    check = schema['properties']['checks']['items']
    check['properties'].update(achieved=TEXT, discrepancies=TEXT, discrepancy_severity=enum(list(CAPS)))
    check['required'] += ['achieved','discrepancies','discrepancy_severity']
    return schema


def score(response, spec, evidence_paths):
    validate_spec(spec)
    Draft202012Validator(response_schema(spec,evidence_paths)).validate(response)
    if response['evidence_status']!='complete':
        raise ValueError('JUDGE_EVIDENCE_FAILURE: '+response['evidence_reason'])
    by_id = {c['id']:c for c in spec['checks']}
    enriched = {}
    for row in response['checks']:
        for field in ('achieved','discrepancies','reason'):
            if not row[field].strip(): raise ValueError('Specific positive/negative observations required')
        if any(not e['observation'].strip() for e in row['evidence']):
            raise ValueError('Blank file citations are not observations')
        severity = row['discrepancy_severity']
        if row['grade'] > CAPS[severity]:
            raise ValueError('Grade contradicts the declared discrepancy severity; no capped score is silently substituted')
        if (row['evidence_status']=='not_demonstrated') != (severity=='not_demonstrated'):
            raise ValueError('Non-demonstration status and severity must agree')
        missing = set(by_id[row['check_id']]['required_evidence']) - {e['file'] for e in row['evidence']}
        if missing: raise ValueError('Required original/authored comparison evidence missing: '+str(sorted(missing)))
        enriched[row['check_id']] = {k:row[k] for k in ('achieved','discrepancies','discrepancy_severity')}
    legacy = copy.deepcopy(response); legacy['protocol'] = l2_rubric.PROTOCOL
    for row in legacy['checks']:
        for k in ('achieved','discrepancies','discrepancy_severity'): row.pop(k)
    result = l2_rubric.score(legacy,legacy_spec(spec),evidence_paths)
    for row in result['criteria']:
        row.update(enriched[row['check_id']])
        row['question']=by_id[row['check_id']]['question']
    result.update(protocol=PROTOCOL, fidelity_policy=POLICY,
        grade_consistency='criterion_local_declared_severity_bounds_not_a_system_gate',
        human_calibrated=False)
    return result


def verify_packet_inputs(spec, manifest):
    """No omitted/additional public views or accidental private reference scene."""
    validate_spec(spec)
    paths = set(manifest['sha256'])
    originals = {p for p in paths if p.startswith('reference/reference-')}
    if originals != set(spec['reference_views']): raise ValueError('Frozen public reference population differs from packet')
    required = {p for c in spec['checks'] for p in c['required_evidence']}
    if not required <= paths: raise ValueError('Frozen required evidence absent from packet')
    if any(p.startswith('reference/') and p.endswith(('.blend','.glb')) for p in paths):
        raise ValueError('Private target native scene must not enter the strict visual packet')
