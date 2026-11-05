"""Case-owned L2 grading over externally collected evidence. No process lifecycle here."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tomllib

from .l2 import score_l2
from .l2_requirements import digest
from .metrics import validate_metrics
from .spec import EvalSpec

CASE_VERSION = 'l2-case-v1.0.0'


def load_case(root):
    root = Path(root)
    from . import l2_case_metrics  # register case-specific atomic measurements
    manifest = tomllib.loads((root/'task.toml').read_text())
    spec = EvalSpec.load(root/'harness/eval_spec.json')
    policy = json.loads((root/'harness/case.json').read_text())
    if (manifest['level'] != 2 or spec.profile != 'L2' or policy.get('version') != CASE_VERSION
            or policy.get('task_id') != manifest['id'] or policy.get('spec_sha256') != spec.digest):
        raise ValueError('L2 case manifest/spec/policy mismatch')
    import hashlib
    instruction = (root/manifest['instruction']).read_text()
    if policy.get('instruction_sha256') != hashlib.sha256(instruction.encode()).hexdigest():
        raise ValueError('L2 case instruction changed')
    artifacts = {str(Path(n).relative_to('output')) for n in manifest['submission_files']}
    if artifacts != set(spec.required_artifacts):
        raise ValueError('L2 case deliverables disagree')
    checks = {c.id for group in spec.checks.values() for c in group}
    requirements = policy.get('requirements',[])
    ids = [r['id'] for r in requirements]
    if not requirements or len(set(ids)) != len(ids):
        raise ValueError('L2 case needs unique requirements')
    mapped = set()
    for rule in requirements:
        if (rule.get('implementation') not in {'complete','partial','manual'} or not rule.get('text')
                or not rule.get('source_quote') or rule['source_quote'] not in instruction
                or not set(rule.get('checks',[])) <= checks):
            raise ValueError('Invalid L2 requirement/source/check binding')
        if rule['implementation']=='complete' and not rule.get('checks'):
            raise ValueError('Complete requirements need measurements')
        mapped.update(rule.get('checks',[]))
    if mapped != checks:
        raise ValueError('Every L2 check needs a requirement source')
    validate_metrics(spec)
    if policy.get("scoring_profile"):
        from .l2_method_scoring import SUPPORTED_PROFILES,load_methods
        if policy["scoring_profile"] not in SUPPORTED_PROFILES:raise ValueError("Unknown case scoring profile")
        load_methods(root,policy)
    return manifest,spec,policy


def evaluate_case(task_root, submission, blender=None, *, evidence=None, execution_context=None,
                  output=None, timeout=900, deadline=None):
    """Untrusted/CLI callers cannot import arbitrary JSON as execution proof."""
    root,submission = Path(task_root),Path(submission)
    manifest,spec,policy = load_case(root)
    trusted = False
    if execution_context is not None:
        from orchestrator.l2_record import validate_context
        evidence = validate_context(execution_context,root,submission,spec,policy)
        trusted = True
    evidence = dict(evidence or {})
    if not trusted:
        evidence['harness'] = {}
    if policy.get('scoring_profile'):
        from .l2_method_scoring import load_methods,score_measured
        report=score_measured(spec,evidence,policy,load_methods(root,policy))
    else:
        report = score_l2(spec,evidence)
    by_id = {c['id']:c for m in report['modules'].values() for c in m['checks']}
    requirements = []
    for rule in policy['requirements']:
        passed = rule['implementation']=='complete' and bool(rule['checks']) and all(by_id[c]['passed'] for c in rule['checks'])
        requirements.append({**rule,'passed':passed,'status':'passed' if passed else
            'failed' if rule['implementation']=='complete' else 'pending_human' if rule['implementation']=='manual' else 'partial'})
    coverage = sum(r['passed'] for r in requirements)/len(requirements)
    automatic_pass = report['case_pass']
    report.update(case_version=CASE_VERSION,case_policy_sha256=digest(policy),task_id=manifest['id'],
        task_type=manifest['category'],trial_id=execution_context.trial_id if trusted else 'artifact-only',
        evaluation_kind='generation' if trusted and execution_context.model_call else 'replay' if trusted else 'artifact-only',
        board='single-shot',requirements=requirements,coverage=coverage,S_diagnostic=report['S_level'],
        automatic_case_pass=automatic_pass,automatic_S_core=report['S_core'],
        scope='Existing L2 methods integrated per case; partial/manual requirements stay in the denominator',
        pending_requirements=[r['id'] for r in requirements if r['implementation']!='complete'],
        artifact_sha256=evidence.get('artifact_sha256',{}),execution_proof_valid=trusted)
    if policy.get('scoring_profile'):
        report['requirements_legacy_diagnostic']=requirements
        report['requirements']=[]
        report['pending_requirements']=[]
        report['coverage']=sum(r['passed'] is True for r in report['measurements'])/len(report['measurements'])
    else:
        report['case_pass'] = automatic_pass and all(r['passed'] for r in requirements)
    report['G'] = int(report['case_pass'])
    report['S_core'] = report['automatic_S_core'] if policy.get('scoring_profile') else report['automatic_S_core']*coverage if report['case_pass'] else 0.
    if policy.get('scoring_profile'):
        report['scope']=report['score_scope']
    report['gates']['case_requirements'] = {'passed':report['gates']['measured_requirements']['passed'] if policy.get('scoring_profile') else all(r['passed'] for r in requirements),
                                          'required':len(report['measurements']) if policy.get('scoring_profile') else len(requirements),
                                          'passed_count':sum(r['passed'] is True for r in report['measurements']) if policy.get('scoring_profile') else sum(r['passed'] for r in requirements)}
    if 'score_valid' in report:
        # Do not present diagnostic failures as missing main-score coverage.
        report['diagnostic_coverage']=report['coverage']
        gate=report['gates']['measured_requirements']
        report['coverage']=(len(gate['required'])-len(gate['failed']))/len(gate['required'])
        report['gates']['case_requirements']={'passed':gate['passed'],'required':len(gate['required']),
            'passed_count':len(gate['required'])-len(gate['failed'])}
    failures=evidence.get('harness',{}).get('measurement_failures',[])
    if failures:
        report.update(S_core=None,automatic_S_core=None,score_valid=None,case_pass=None,G=None,automatic_case_pass=None,
                      status='not_measurable',measurement_failures=failures,
                      measurement_error='Evaluator inspection incomplete; no model zero grade is established')
        for gate in report['gates'].values():
            if gate.get('passed') is False:gate['measurement_status']='not_measured'
    output = Path(output) if output else submission/'evaluation/l2-case'
    output.mkdir(parents=True,exist_ok=False)
    report.update(report_path=str((output/'report.json').resolve()),evidence_path=str((output/'evidence.json').resolve()))
    from .l2_runner import _write_json
    _write_json(output/'evidence.json',evidence)
    _write_json(output/'report.json',report)
    return report


def main(task_root):
    parser = argparse.ArgumentParser(description='Case scoring; external orchestrator supplies trusted execution and inspection')
    parser.add_argument('--submission',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    report = evaluate_case(task_root,args.submission,output=args.output)
    print(json.dumps({k:report[k] for k in ('task_id','case_pass','S_core','S_diagnostic','execution_proof_valid','report_path')}))
    return 0
