"""Revalidate each confirmed reproduction observation at publication consumption.

Unavailable slots remain unavailable; no file is read to manufacture their ACK.
This is trusted-record consistency, not storage isolation or geometry rescoring.
"""

from __future__ import annotations

import time
from pathlib import Path

from src.evaluator.l1_failures import InspectionFailure
from src.evaluator.l1_inspection_receipt import reload_inspection

from .reproduction import frame_policy


def _require(condition, reason):
    if not condition:
        raise ValueError(f"Reproduction publication: {reason}")


def _guard(deadline):
    if time.monotonic() >= deadline:
        raise InspectionFailure("infrastructure_error", "EVALUATION_BUDGET_EXHAUSTED",
                                "Reproduction publication exhausted its inherited deadline")


def _expected(root, original, candidate, frames):
    """Task-owned slots, not a candidate/record-provided list of what to verify."""
    layout = {}
    for side, artifacts in (("original", original), ("seed", candidate)):
        layout[str(root / 'scene-blend/session' / side)] = (artifacts.get('scene.blend'), tuple(frames))
        layout[str(root / 'scene-glb/frame-00' / side)] = (artifacts.get('scene.glb'), None)
    for side, artifacts in (("original", original), ("candidate", candidate)):
        for fmt, name in (("native", "scene.blend"), ("glb", "scene.glb")):
            layout[str(root / 'cross-format' / side / 'frame-00' / fmt)] = (artifacts.get(name), None)
    return layout


def _old_proof(proof, record, work_deadline):
    _require(isinstance(proof, dict) and proof.get('protocol') == 'l1-inspection-validation-v1'
             and proof.get('status') == 'verified', 'missing original consumption validation')
    _require(proof.get('deadline_monotonic') == work_deadline
             and type(proof.get('finished_monotonic')) in (int, float)
             and proof['finished_monotonic'] <= work_deadline, 'late original consumption')
    _require(proof.get('record_path') == record.get('record_path'), 'original record path mismatch')
    rows = proof.get('reads')
    _require(isinstance(rows, list) and len(rows) == 2, 'original reads missing')
    for row, path, digest in zip(rows,
                                  (proof['record_path'], str(Path(proof['record_path']).with_name('facts.json'))),
                                  (proof.get('record_sha256'), proof.get('facts_sha256'))):
        _require(isinstance(row, dict) and row.get('protocol') == 'l1-result-reception-v1'
                 and row.get('status') == 'completed' and row.get('source_path') == path
                 and row.get('received_sha256') == digest, 'original read binding mismatch')
        _require(type(row.get('pid')) is int and row['pid'] > 0 and row.get('process_group') == row['pid']
                 and row.get('leader_reaped') is True and row.get('group_kill_sent') is True
                 and type(row.get('return_code')) is int and row['return_code'] == 0,
                 'original read cleanup missing')
        _require(row.get('deadline_monotonic') == work_deadline
                 and type(row.get('finished_monotonic')) in (int, float)
                 and row['finished_monotonic'] <= work_deadline, 'original read deadline mismatch')


def validate_reproduction_publication(record, run_dir: Path, *, deadline: float, receipts=None):
    """Reject missing successful slots, mismatched seeds, stale ACKs or drift."""
    proof = {'protocol': 'l1-reproduction-publication-v1', 'deadline_monotonic': deadline,
             'status': 'validating', 'observations': {}, 'verified_count': 0, 'unavailable_count': 0}
    try:
        _guard(deadline)
        summary = record.get('reproduction_consistency')
        _require(isinstance(summary, dict), 'reproduction summary missing')
        seeds, runs = summary.get('expected_seeds'), record.get('seed_runs')
        _require(isinstance(seeds, list) and 0 < len(seeds) <= 256
                 and all(type(seed) is int for seed in seeds) and len(set(seeds)) == len(seeds), 'invalid seeds')
        keys = {str(seed) for seed in seeds}
        _require(isinstance(runs, dict) and set(runs) == keys, 'seed execution slots mismatch')
        items = summary.get('per_seed')
        _require(isinstance(items, dict) and set(items) == keys and summary.get('denominator') == len(seeds),
                 'reproduction denominator mismatch')
        policy = frame_policy(record['task_id'])
        work_deadline = record['budget']['deadline_monotonic']
        original = record.get('reconstruction_baseline', {}).get('resources', {}).get('artifacts', {})
        resources = record.get('resource_snapshots', {}).get('per_seed', {})
        spec = run_dir / 'configuration/eval_spec.json'
        measured = passed = 0
        for seed in seeds:
            _guard(deadline)
            item = items[str(seed)]
            _require(isinstance(item, dict), 'invalid seed summary')
            status = item.get('status')
            _require(status in {'ok', 'failed', 'not_measurable', 'not_configured'}, 'unknown reproduction state')
            passed += status == 'ok'
            measured += status in {'ok', 'failed'}
            observations = item.get('inspections')
            if observations is None:
                _require(status in {'not_measurable', 'not_configured'}
                         and item.get('execution_attempted') is not True, 'attempted comparison lost inspections')
                continue
            _require(isinstance(observations, dict) and len(observations) <= 8, 'invalid observation collection')
            candidate = (resources.get(str(seed)) or {}).get('artifacts', {})
            layout = _expected(run_dir / 'reproduction' / str(seed), original, candidate, policy['native_frames'])
            _require(set(observations) <= set(layout), 'observation path/seed mismatch')
            if status in {'ok', 'failed'}:
                _require(set(observations) == set(layout), 'measured comparison missing observation')
            for path, observation in observations.items():
                _guard(deadline)
                _require(isinstance(observation, dict), 'observation is not object')
                observed_status = observation.get('status')
                if observed_status != 'verified':
                    _require(status in {'not_measurable', 'not_configured'}
                             and observed_status in {'unavailable', 'interrupted'}
                             and isinstance(observation.get('failure'), dict), 'unconfirmed observation counted as measured')
                    proof['observations'][path] = {'status': 'unavailable', 'metadata_ack': False,
                                                    'failure': observation['failure']}
                    proof['unavailable_count'] += 1
                    continue
                scene, frames = layout[path]
                _require(isinstance(scene, str) and observation.get('scene_path') == scene
                         and observation.get('spec_path') == str(spec), 'resource/spec binding mismatch')
                execution = observation.get('inspector_execution')
                _require(isinstance(execution, dict)
                         and execution.get('record_path') == str(Path(path) / 'inspector_record.json')
                         and execution.get('shared_deadline_monotonic') == work_deadline,
                         'inspection identity or original deadline mismatch')
                old = observation.get('validation')
                _old_proof(old, execution, work_deadline)
                fresh = reload_inspection(execution, observation.get('inspector_persistence'),
                                          scene=Path(scene), spec=spec, deadline=deadline, frames=frames)
                for name in ('record_sha256', 'facts_sha256'):
                    _require(old.get(name) == fresh[name], 'original consumption hash mismatch')
                proof['observations'][path] = fresh
                proof['verified_count'] += 1
                if receipts is not None:
                    receipts.extend({'label': 'reproduction inspector ACK reload', **row} for row in fresh['reads'])
        _require(summary.get('passed_count') == passed and summary.get('measured_count') == measured,
                 'summary counts do not match fixed seed slots')
        _guard(deadline)
        proof.update(status='verified', finished_monotonic=time.monotonic())
        return proof
    except (InspectionFailure, KeyboardInterrupt, SystemExit) as error:
        extra = getattr(error, 'inspection_validation_io', [])
        if receipts is not None:
            receipts.extend({'label': 'reproduction inspector ACK reload', **row} for row in extra)
        proof.update(status='interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit)) else 'failed',
                     failure_code=getattr(error, 'code', type(error).__name__), failed_reads=extra)
        error.reproduction_publication = proof
        raise
    except (ValueError, TypeError, KeyError) as error:
        failure = InspectionFailure('infrastructure_error', 'REPRODUCTION_PUBLICATION_INVALID', str(error))
        proof.update(status='failed', failure_code=failure.code)
        failure.reproduction_publication = proof
        raise failure from error
