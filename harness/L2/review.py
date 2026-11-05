"""Prepare and validate human review/calibration; optional VLM remains auxiliary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.evaluator.l2_requirements import digest, calibration_template, validate_calibration, apply_calibration
from src.evaluator.l2_visual import file_hash, image_ref, annotation_template, visual_diagnostics


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def prepare(report_path, requirements, evidence, output, *, annotations=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    expected_annotations = annotation_template(evidence)
    if annotations is not None:
        if set(annotations.get('views', {})) != set(expected_annotations['views']):
            raise ValueError('Annotations must cover exactly the report views')
        for name, view in expected_annotations['views'].items():
            if any(annotations['views'][name].get(key) != view[key] for key in ('reference','candidate')):
                raise ValueError('Annotations refer to different report images')
    else:
        annotations = expected_annotations
    visual = visual_diagnostics(annotations,output/'visual')
    write(output/'annotations.template.json', annotations)
    write(output/'calibration.template.json', calibration_template(requirements))
    report = json.loads(Path(report_path).read_text())
    if (report.get('task_id') != requirements['task_id'] or report.get('spec_sha256') != requirements['spec_sha256']
            or report.get('requirements_coverage', {}).get('requirements_sha256', digest(requirements)) != digest(requirements)):
        raise ValueError('Review requirements do not match report task/spec')
    files = {}
    for view in annotations['views'].values():
        for kind in ('reference','candidate'):
            if view.get(kind):
                item = view[kind]
                files[item['path']] = item['sha256']
    for path in output.rglob('*'):
        if path.is_file():
            files[str(path.resolve())] = file_hash(path)
    for key in ('evidence_path','diagnostics_path'):
        if report.get(key):
            path = Path(report[key])
            files[str(path.resolve())] = file_hash(path)
    packet = {'schema_version': 1, 'task_id': report['task_id'],
        'report': image_ref(report_path), 'requirements_sha256': digest(requirements),
        'requirements': requirements, 'evidence_sha256': files,
        'automatic_case_pass': report['case_pass'], 'formal_score_eligible': False,
        'pending_calibration': calibration_template(requirements)['decisions'],
        'questions': requirements['manual_requirements'],
        'visual_status': visual['annotation_status'],
        'visual_report': image_ref(output/'visual/visual_diagnostics.json'),
        'notice': 'This is an evidence binding, not authentication of a human identity. Never treat candidate-authored decisions as trusted review.'}
    write(output/'packet.json', packet)
    response = {'packet_sha256': digest(packet), 'reviewer': '', 'reviewed_at': '',
        'decisions': {q['id']: {'decision': 'pending', 'rationale': '', 'evidence_paths': []} for q in packet['questions']}}
    write(output/'response.template.json', response)
    return packet


def verify_packet(packet):
    report = packet['report']
    if file_hash(report['path']) != report['sha256']:
        raise ValueError('Review report changed')
    raw = json.loads(Path(report['path']).read_text())
    requirements = packet['requirements']
    if (raw['task_id'] != packet['task_id'] or raw['case_pass'] is not packet['automatic_case_pass']
            or raw['spec_sha256'] != requirements['spec_sha256']
            or raw.get('requirements_coverage', {}).get('requirements_sha256', digest(requirements)) != digest(requirements)
            or packet['pending_calibration'] != calibration_template(requirements)['decisions']
            or packet['questions'] != requirements['manual_requirements']):
        raise ValueError('Review packet differs from its bound report/requirements')
    visual = packet['visual_report']
    if (file_hash(visual['path']) != visual['sha256']
            or json.loads(Path(visual['path']).read_text())['annotation_status'] != packet['visual_status']):
        raise ValueError('Visual review status differs from bound evidence')
    if digest(packet['requirements']) != packet['requirements_sha256']:
        raise ValueError('Review requirements changed')
    for path, expected in packet['evidence_sha256'].items():
        if file_hash(path) != expected:
            raise ValueError('Review evidence missing or changed: '+Path(path).name)


def validate_response(packet, response):
    verify_packet(packet)
    expected = {q['id'] for q in packet['questions']}
    if response.get('packet_sha256') != digest(packet) or set(response.get('decisions',{})) != expected:
        raise ValueError('Human response must bind the exact packet and cover all questions')
    pending, failed = [], []
    for key, item in response['decisions'].items():
        decision = item.get('decision')
        if decision not in {'pending','pass','fail','not_judgeable'}:
            raise ValueError('Invalid human decision')
        if decision == 'pending':
            pending.append(key)
            continue
        if (not response.get('reviewer','').strip() or not response.get('reviewed_at','').strip()
                or not item.get('rationale','').strip() or not item.get('evidence_paths')
                or any(p not in packet['evidence_sha256'] for p in item['evidence_paths'])):
            raise ValueError('Human decisions need reviewer, date, rationale and packet evidence')
        if decision == 'not_judgeable':
            pending.append(key)
        elif decision == 'fail':
            failed.append(key)
    human = 'failed' if failed else 'pending_human' if pending else 'passed'
    calibration_pending = list(packet['pending_calibration'])
    annotations_pending = 'reference_annotations' in expected and packet['visual_status'] != 'available'
    return {'schema_version': 1, 'packet_sha256': digest(packet), 'response_sha256': digest(response),
        'human_status': human, 'pending': pending, 'failed': failed,
        'pending_calibration': calibration_pending, 'pending_annotations': annotations_pending, 'automatic_case_pass': packet['automatic_case_pass'],
        'task_completion': 'failed' if failed or not packet['automatic_case_pass'] else
            'pending_human' if pending or calibration_pending or annotations_pending else 'passed',
        'formal_score_eligible': not calibration_pending and not pending and not annotations_pending,
        'note': 'Human review never overrides automatic integrity failures or silently changes thresholds.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare','apply','visual','calibration','publish-calibration','vlm'])
    parser.add_argument('--packet', type=Path)
    parser.add_argument('--response', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--requirements', type=Path)
    parser.add_argument('--annotations', type=Path)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--tested-model')
    parser.add_argument('--instruction', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('Output already exists; choose a new review version')
    if args.operation == 'prepare':
        report = json.loads(args.report.read_text())
        evidence = json.loads(Path(report['evidence_path']).read_text())
        prepare(args.report,json.loads(args.requirements.read_text()),evidence,args.output,
                annotations=json.loads(args.annotations.read_text()) if args.annotations else None)
    elif args.operation == 'visual':
        visual_diagnostics(json.loads(args.annotations.read_text()),args.output)
    elif args.operation == 'calibration':
        write(args.output, validate_calibration(json.loads(args.response.read_text()),json.loads(args.requirements.read_text())))
    elif args.operation == 'publish-calibration':
        write(args.output, apply_calibration(json.loads(args.requirements.read_text()),json.loads(args.response.read_text())))
    elif args.operation == 'apply':
        write(args.output,validate_response(json.loads(args.packet.read_text()),json.loads(args.response.read_text())))
    else:
        from dataclasses import replace
        from src.evaluator.vlm import VLMConfig, evaluate_with_vlm
        packet = json.loads(args.packet.read_text())
        verify_packet(packet)
        if not args.tested_model or not args.instruction:
            parser.error('VLM requires --tested-model and --instruction; unknown self-judging is not allowed')
        instruction = args.instruction.read_text()
        import hashlib
        if hashlib.sha256(instruction.encode()).hexdigest() != packet['requirements']['instruction_sha256']:
            raise ValueError('VLM instruction does not match task requirements')
        report = json.loads(Path(packet['report']['path']).read_text())
        if report.get('model') and report['model'] != args.tested_model:
            raise ValueError('VLM tested-model does not match the generation record')
        evidence = json.loads(Path(report['evidence_path']).read_text())
        refs = [Path(v['path']) for v in evidence.get('reference_images',{}).values()]
        candidates = [Path(v['path']) for k,v in evidence['artifacts'].items() if k.endswith('.png') and v.get('loadable')]
        config = replace(VLMConfig.from_env(args.env_file),tested_model=args.tested_model)
        result = evaluate_with_vlm(config,instruction,refs,candidates)
        write(args.output,{'packet_sha256': digest(packet), 'auxiliary_only': True,
            'human_status': 'pending_human', 'model': config.model, 'self_judge': config.self_judge, 'result': result})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
