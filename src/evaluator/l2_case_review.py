"""Validate a human response without modifying the automatic case report."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from .l2_requirements import digest
from .l2_visual import file_hash


def validate_response(packet, response):
    if packet.get('protocol') != 'l2-case-review-v1':
        raise ValueError('Unknown case review protocol')
    for item in (packet['report'], packet['evidence']):
        if file_hash(item['path']) != item['sha256']:
            raise ValueError('Bound report/evidence changed')
    report = json.loads(Path(packet['report']['path']).read_text())
    evidence = json.loads(Path(packet['evidence']['path']).read_text())
    expected = [r for r in report['requirements'] if r['implementation'] != 'complete']
    expected = [{k:v for k,v in r.items() if k not in {'passed','status'}} for r in expected]
    if (report['task_id'] != packet['task_id']
            or report['case_policy_sha256'] != packet['case_policy_sha256']
            or expected != packet['questions']):
        raise ValueError('Review questions differ from the bound case report')
    files = packet['files_sha256']
    for path, value in files.items():
        if file_hash(path) != value:
            raise ValueError('Bound review file changed: '+Path(path).name)
    for items in (evidence.get('artifacts',{}), evidence.get('reference_images',{})):
        for item in items.values():
            if item.get('path') and item.get('sha256'):
                if files.get(item['path']) != item['sha256']:
                    raise ValueError('Review does not bind the original artifact/reference')
    if (response.get('packet_sha256') != digest(packet)
            or set(response.get('decisions',{})) != {r['id'] for r in expected}):
        raise ValueError('Response must cover exactly this packet')
    pending, failed = [], []
    for key, value in response['decisions'].items():
        decision = value.get('decision')
        if decision not in {'pending','pass','fail','not_judgeable'}:
            raise ValueError('Unknown human decision')
        if decision != 'pending':
            if (not response.get('reviewer','').strip() or not value.get('rationale','').strip()
                    or not value.get('evidence_paths')
                    or any(p not in files for p in value['evidence_paths'])):
                raise ValueError('Decision needs reviewer, rationale and bound evidence paths')
            try:
                datetime.fromisoformat(response.get('reviewed_at','').replace('Z','+00:00'))
            except (ValueError,TypeError):
                raise ValueError('Review date must be ISO 8601') from None
        if decision in {'pending','not_judgeable'}:
            pending.append(key)
        elif decision == 'fail':
            failed.append(key)
    automatic = report['automatic_case_pass'] and report['execution_proof_valid']
    measured_only=bool(report.get('method_version')) and report.get('text_semantics_evaluated') is False
    completion='failed' if failed or not automatic else 'pending_human' if pending else 'passed'
    if measured_only and completion=='passed':completion='not_evaluated'
    return {'protocol':'l2-case-review-result-v1','task_id':packet['task_id'],
        'packet_sha256':digest(packet),'response_sha256':digest(response),
        'reviewer':response.get('reviewer',''),'reviewed_at':response.get('reviewed_at',''),
        'decisions':response['decisions'], 'pending':pending,'failed':failed,
        'automatic_case_pass':automatic,
        'human_status':'not_requested' if measured_only and not expected else 'failed' if failed else 'pending_human' if pending else 'passed',
        'task_completion':completion,
        'measured_scope_passed':bool(automatic and not failed),
        'formal_score_eligible':False,
        'note':'Operator-supplied review; hashes bind evidence, not reviewer identity. '
               'Does not override automatic failures or alter scores. A measured-only report cannot certify full task completion. '
               'Threshold calibration and release approval remain separate.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet',type=Path,required=True)
    parser.add_argument('--response',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args(argv)
    result = validate_response(json.loads(args.packet.read_text()),json.loads(args.response.read_text()))
    with args.output.open('x') as stream:
        stream.write(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ('task_id','human_status','task_completion')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
