"""L1-only collection of independent per-seed evaluator reports."""
import time

from harness.L1.common.reproduction import frame_policy
from src.evaluator.l1_case import evaluate_case
from src.evaluator.l1_compute_receipt import validate_score_compute
from src.evaluator.l1_file_io import run_file_io
from src.evaluator.l1_seed_quality import PROTOCOL, quality_check, selected_checks

from .tasks import write_json


def collect_seed_quality(task, spec, outputs, record, *, blender, run, deadline,
                         scoring_reserve, timeout):
    check = quality_check(spec)
    if check is None:
        return None
    policy = frame_policy(task.id, spec)
    result = {'protocol': PROTOCOL, 'task_id': task.id, 'spec_sha256': spec.digest,
              'run_root': str(run), 'checks': sorted(selected_checks(spec)),
              'expected_seeds': list(spec.seeds), 'native_frames': policy['native_frames'],
              'glb_frames': policy['glb_frames'], 'per_seed': {}}
    end = deadline - scoring_reserve
    for position, seed in enumerate(spec.seeds):
        started = time.monotonic()
        seed_deadline = min(end, started + max(0., end - started) / (len(spec.seeds) - position))
        submission = outputs.get(f'seed-{seed}')
        row = {'status': 'not_measurable', 'deadline_monotonic': seed_deadline,
               'reason': 'Seed execution failed' if submission is None else 'Quality collection not started'}
        result['per_seed'][str(seed)] = row
        try:
            if submission is None:
                continue
            if policy['native_frames'] != check.params['native_frames'] or policy['glb_frames'] != check.params['glb_frames']:
                raise ValueError('Seed quality does not match this task state policy')
            if started >= seed_deadline:
                raise TimeoutError('No seed quality budget remains before final scoring')
            hashes = record['seed_runs'][str(seed)]['artifact_sha256']
            # No recursive aggregate record in a seed evaluation. Individual
            # measurements are consumed, not its incomplete overall verdict.
            seed_record = {**record, 'artifact_sha256': hashes}
            seed_record.pop('seed_quality', None)
            report = evaluate_case(task.root, submission, blender, harness_record=seed_record,
                                   timeout=timeout, deadline=seed_deadline)
            row.update(submission_root=str(submission), artifact_sha256=hashes,
                       report_path=report['report_path'], evidence_path=report['evidence_path'])
            if report.get('scoring_failed') or report.get('budget_exhausted'):
                raise RuntimeError('Seed evaluator unavailable; retain its failure report')
            validation = validate_score_compute(report, deadline=seed_deadline)
            row['compute_validation'] = validation
            for label in ('report', 'evidence'):
                row[label] = run_file_io('hash', {'path': report[label + '_path']},
                                        output=run / 'seed_quality' / str(seed) / 'binding', deadline=seed_deadline)
                row[label]['path'] = report[label + '_path']
            row.update(status='collected', reason=None)
        except (OSError, ValueError, RuntimeError) as error:
            row.update(status='not_measurable', reason=str(error)[:2048],
                       failure_code=getattr(error, 'code', type(error).__name__))
        finally:
            row['elapsed_seconds'] = time.monotonic() - started
            write_json(run / 'seed_quality' / f'seed-{seed}.json', row)
            write_json(run / 'seed_quality' / 'collection.json', result)
    return result
