"""Actual L1 generation -> rerun -> allowlisted feedback service adapter."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from src.evaluator.l1_budget import BudgetExhausted, DeadlineBudget, positive_seconds
from src.evaluator.l1_parent_io import ensure_directory
from src.generator.task_adapter import load_benchmark_task

from . import runner
from .agent import MAX_ROUNDS, run_refinement
from .attempt_log import sha256, write_json_atomic
from .config import load_config
from .configuration import (
    configuration_snapshot,
    record_binding,
    save_configuration,
    task_spec,
)
from .feedback import public_feedback_from_report
from .rerun import rerun_submission
from .submission import stage_submission, validate_submission

PROTOCOL = 'l1-refinement-service-v1'


def _regular(path: Path, root: Path) -> Path:
    path, root = path.expanduser().absolute(), root.resolve()
    if not path.is_relative_to(root):
        raise ValueError('Refinement evidence path is outside its owned phase directory')
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Refinement evidence cannot be symlinked')
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError('Refinement evidence is missing or escapes its phase directory')
    return path


def _phase_record(result: dict[str, Any], root: Path, expected: dict[str, Any], *,
                  task_id: str, trial_id: str, round_index: int, deadline: float) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(Path(result['harness_record']), root / 'harness_records')
    record = json.loads(path.read_text())
    record_binding(record, expected)
    run_dir = Path(result['run_dir']).resolve()
    if run_dir.parent != (root / 'harness').resolve() or run_dir.name != record.get('run_id') or path.stem != run_dir.name:
        raise ValueError('Refinement record does not identify this phase run')
    if (record.get('task_id'), record.get('trial_id'), record.get('repair_round')) != (task_id, trial_id, round_index):
        raise ValueError('Refinement task/trial/repair_round binding mismatch')
    if result.get('final_status') != record.get('final_status'):
        raise ValueError('Refinement result disagrees with trusted phase record')
    budget = record.get('budget', {})
    if budget.get('inherited_deadline_monotonic') != deadline or budget.get('deadline_monotonic', float('inf')) > deadline:
        raise ValueError('Refinement child did not inherit the shared deadline')
    return record, {'record_path': str(path), 'record_sha256': sha256(path), 'run_dir': str(run_dir),
                    'status': record['final_status'], 'repair_round': round_index}


def run_agent_pipeline(task_id: str, tasks_root: Path, config_path: Path, output_dir: Path, *,
                       env_file: Path | None = None, trial_id: str = '0', blender: Path | None = None,
                       timeout: float | None = None, max_rounds: int = MAX_ROUNDS,
                       max_total_seconds: float | None = None, deadline: float | None = None) -> dict[str, Any]:
    """Opt-in refinement; single-shot pipeline and formal task specs are unchanged."""
    started = time.monotonic()
    if not isinstance(task_id, str) or not re.fullmatch(r'L1/[A-Za-z0-9_-]+', task_id):
        raise ValueError('Refinement requires an L1 task identifier')
    if not isinstance(trial_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', trial_id):
        raise ValueError('Refinement trial_id must be a safe identifier')
    if type(max_rounds) is not int or not 1 <= max_rounds <= MAX_ROUNDS:
        raise ValueError('Refinement supports one to three rounds')
    if timeout is not None:
        positive_seconds(timeout, 'timeout')
    task = load_benchmark_task(task_id, tasks_root)
    config = load_config(config_path)
    seconds = config.max_total_seconds
    if max_total_seconds is not None:
        seconds = min(seconds, positive_seconds(max_total_seconds, 'max_total_seconds'))
    budget = DeadlineBudget.start(seconds, deadline=deadline, started=started)
    spec_path, spec = task_spec(task)
    configuration = configuration_snapshot(task, config, spec_path, spec)
    directory = output_dir.expanduser().resolve() / 'refinements' / f'{task_id.replace("/", "__")}__{trial_id}__{time.time_ns()}'
    if directory.exists():
        raise FileExistsError(f'Refinement directory already exists: {directory}')
    ensure_directory(directory, deadline=budget.deadline, parents=True)
    initial = directory / 'initial_submission'
    ensure_directory(initial, deadline=budget.deadline, parents=False)
    save_configuration(directory / 'configuration', configuration, spec)
    manifest_path = directory / 'refinement_manifest.json'
    manifest: dict[str, Any] = {'protocol': PROTOCOL, 'task_id': task_id, 'trial_id': trial_id,
                                'configuration': configuration, 'max_rounds': max_rounds, 'rounds': [],
                                'status': 'running', 'phase': 'initializing',
                                'costs': {'wall_seconds': None, 'cli_attempt_count': None,
                                          'token_count': None, 'tool_calls': None,
                                          'unknown': ['model_service.token_count', 'model_service.tool_calls']},
                                'model_context': 'task_environment_plus_declared_prior_files_and_frozen_public_feedback',
                                'scope': 'service_wiring_not_a_complete_sandbox_or_task_quality_proof'}

    def checkpoint() -> None:
        manifest['budget'] = budget.record('refinement_service')
        manifest['elapsed_seconds'] = time.monotonic() - started
        manifest['costs']['wall_seconds'] = manifest['elapsed_seconds']
        manifest['costs']['completed_generation_records'] = sum('generation' in row for row in manifest['rounds'])
        manifest['costs']['cli_attempt_count'] = (sum(len(row['attempts']) for row in manifest['rounds'])
                                                  if all('attempts' in row for row in manifest['rounds']) else None)
        write_json_atomic(manifest_path, manifest)

    def generate(index: int, work: Path, previous: dict[str, Any], _remaining: float) -> dict[str, Any]:
        budget.check()
        child_root = directory / 'rounds' / f'round-{index:02d}'
        child_trial = f'{trial_id}-round-{index}'
        row: dict[str, Any] = {'repair_round': index, 'trial_id': child_trial,
                               'phase_dir': str(child_root), 'phase': 'generation',
                               'status': 'running', 'public_feedback_input': previous}
        manifest['rounds'].append(row)
        manifest['phase'] = 'generation'
        checkpoint()
        budget.check()
        prior = work if index > 0 and (work / 'solution.py').is_file() else None
        try:
            result = runner.run(task_id, tasks_root, config_path, child_root, env_file, child_trial, blender,
                                execute=False, deadline=budget.deadline, expected_binding=configuration,
                                repair_round=index, previous_submission=prior, public_feedback=previous)
        except (Exception, KeyboardInterrupt, SystemExit) as error:
            failure_result = getattr(error, 'l1_generation_result', None)
            if isinstance(failure_result, dict):
                try:
                    record, binding = _phase_record(failure_result, child_root, configuration, task_id=task_id,
                                                     trial_id=child_trial, round_index=index, deadline=budget.deadline)
                    if record['generation_passed'] is not False or record['final_status'] not in {'interrupted', 'invoker_error'}:
                        raise ValueError('Exception cannot carry successful generation evidence')
                    row['generation'], row['generation_costs'], row['attempts'] = binding, record['costs'], record['attempts']
                except (OSError, ValueError, KeyError, TypeError) as binding_error:
                    # Never hide the original cancellation or accept unverified
                    # exception metadata as provenance/costs.
                    row['generation_failure_binding_error'] = type(binding_error).__name__
            raise
        record, binding = _phase_record(result, child_root, configuration, task_id=task_id, trial_id=child_trial,
                                         round_index=index, deadline=budget.deadline)
        row['generation'] = binding
        row['generation_costs'] = record['costs']
        row['attempts'] = record['attempts']
        context = record.get('refinement_context')
        if not isinstance(context, dict) or context.get('feedback') != previous or context.get('repair_round') != index:
            raise ValueError('Generation did not consume this round public feedback')
        row['refinement_context'] = context
        checkpoint()
        budget.check()
        if record['final_status'] != 'generated' or record.get('generation_passed') is not True:
            row.update(phase='completed', status='generation_failed')
            checkpoint()
            return {'status': record['final_status'], 'repair_round': index, 'costs': record['costs']}
        generated = Path(result['run_dir'])
        metadata = validate_submission(generated, reserved_outputs=spec.required_artifacts, entrypoint_policy=config.entrypoint_policy)
        if record.get('submission') is not None and metadata['files'] != record['submission']['files']:
            raise ValueError('Generated submission changed before refinement staging')
        if sha256(generated / 'solution.py') != record['artifact_sha256'].get('solution.py'):
            raise ValueError('Generated canonical source changed before refinement staging')
        replacement = work.with_name('new_submission')
        stage_submission(generated, replacement, reserved_outputs=spec.required_artifacts,
                         entrypoint_policy=config.entrypoint_policy, deadline=budget.deadline)
        # Preserve the old input; do not merge deleted files into the new round.
        work.rename(work.with_name('previous_input'))
        replacement.rename(work)
        row.update(phase='generated', status='generated', submission=metadata)
        checkpoint()
        budget.check()
        return {'status': 'success', 'repair_round': index, 'costs': record['costs'],
                'generation_binding': binding}

    def execute(work: Path, _remaining: float) -> dict[str, Any]:
        budget.check()
        row = manifest['rounds'][-1]
        index, child_trial = row['repair_round'], row['trial_id']
        child_root = Path(row['phase_dir'])
        row['phase'], manifest['phase'] = 'execution', 'execution'
        checkpoint()
        budget.check()

        def event(phase: str, status: str, details: dict[str, Any]) -> None:
            row['execution_phase'] = {'phase': phase, 'status': status, 'details': details}
            checkpoint()

        result = rerun_submission(task_id, tasks_root, config_path, work, child_root,
                                   trial_id=child_trial, repair_round=index, blender=blender, timeout=timeout,
                                   evaluate=True, on_phase=event, deadline=budget.deadline, expected_binding=configuration)
        record, binding = _phase_record(result, child_root, configuration, task_id=task_id, trial_id=child_trial,
                                         round_index=index, deadline=budget.deadline)
        if record['submission']['files'] != row['submission']['files']:
            raise ValueError('Executed submission does not match the current generation')
        row['execution'], row['execution_costs'] = binding, record['costs']
        row['seed_bindings'] = {seed: run['execution_binding'] for seed, run in record['seed_runs'].items()}
        row['baseline'] = record['reconstruction_baseline']
        report = None
        if result.get('report_path') is not None:
            path = _regular(Path(result['report_path']), Path(result['run_dir']) / 'evaluation')
            accepted = record.get('evaluation_finalization')
            if isinstance(accepted, dict) and accepted.get('status') in {'completed', 'failed', 'interrupted'}:
                from src.evaluator.l1_finalization import load_finalized_report
                report = load_finalized_report(path, accepted, deadline=budget.deadline)
            else:
                # Legacy/failure reports retain their old loading policy.
                # A pending new report still fails the public-feedback gate.
                report = json.loads(path.read_text())
            if report != result.get('report'):
                raise ValueError('Persisted refinement report differs from the returned report')
            if (report.get('task_id'), report.get('trial_id'), report.get('spec_sha256')) != (task_id, child_trial, spec.digest):
                raise ValueError('Refinement report belongs to another task, round or specification')
            if any(report.get('artifact_sha256', {}).get(name) != digest for name, digest in record['artifact_sha256'].items()):
                raise ValueError('Refinement report does not bind the executed artifacts')
            row['report'] = {'path': str(path), 'sha256': sha256(path)}
        row['public_feedback'] = public_feedback_from_report(report, spec, execution_status=record['final_status'])
        row.update(phase='completed', status=record['final_status'])
        checkpoint()
        budget.check()
        canonical = record['seed_runs'][str(spec.seeds[0])]
        return {'status': record['final_status'], 'repair_round': index, 'program_seed': spec.seeds[0],
                'rng_trace': canonical.get('rng_trace'), 'execution_binding': binding,
                'seed_bindings': row['seed_bindings'], 'costs': record['costs']}

    def feedback(index: int, _execution: dict[str, Any]) -> dict[str, Any]:
        row = manifest['rounds'][index]
        if row['repair_round'] != index:
            raise ValueError('Feedback round mismatch')
        report_binding = row.get('report')
        if report_binding and sha256(Path(report_binding['path'])) != report_binding['sha256']:
            raise ValueError('Trusted report changed before feedback delivery')
        return row['public_feedback']

    checkpoint()
    result: dict[str, Any] = {'manifest_path': str(manifest_path), 'run_dir': str(directory)}
    try:
        budget.check()
        result['agent'] = run_refinement(directory / 'agent', initial, generate_round=generate,
                                         execute_round=execute, feedback_round=feedback,
                                         max_rounds=max_rounds, max_total_seconds=seconds,
                                         deadline=budget.deadline, feedback_spec=spec)
        manifest['status'] = result['agent']['status']
        manifest['phase'] = 'completed'
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        interrupted = isinstance(error, (KeyboardInterrupt, SystemExit))
        manifest['status'] = 'interrupted' if interrupted else 'budget_exhausted' if isinstance(error, BudgetExhausted) else 'failed'
        manifest['failure'] = {'phase': manifest['phase'], 'exception_type': type(error).__name__}
        if manifest['rounds']:
            manifest['rounds'][-1]['status'] = manifest['status']
        checkpoint()
        if interrupted:
            raise
    manifest['costs'] = {
        'wall_seconds': time.monotonic() - started,
        'completed_generation_records': sum('generation' in row for row in manifest['rounds']),
        'cli_attempt_count': sum(len(row['attempts']) for row in manifest['rounds'])
        if all('attempts' in row for row in manifest['rounds']) else None,
        'token_count': None, 'tool_calls': None,
        'unknown': ['model_service.token_count', 'model_service.tool_calls'],
        'accounting': 'Per-round generation and execution costs retained; inclusive phase times are not added twice',
    }
    if budget.exhausted and manifest['status'] not in {'interrupted', 'failed'}:
        manifest['status'] = 'budget_exhausted'
    result.update(final_status=manifest['status'], round_count=len(manifest['rounds']))
    checkpoint()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description='Opt-in L1 real-service refinement, at most three rounds')
    parser.add_argument('--task', required=True)
    parser.add_argument('--tasks-root', type=Path, default=Path('data/3dbench/task'))
    parser.add_argument('--harness-config', type=Path)
    parser.add_argument('--output-dir', type=Path, default=Path('data/task_runs'))
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--trial-id', default='0')
    parser.add_argument('--blender', type=Path)
    parser.add_argument('--timeout', type=float)
    parser.add_argument('--max-rounds', type=int, default=MAX_ROUNDS)
    parser.add_argument('--max-total-seconds', type=float)
    args = parser.parse_args()
    result = run_agent_pipeline(args.task, args.tasks_root, args.harness_config or runner._task_config_default(args.task, args.tasks_root),
                                args.output_dir, env_file=args.env_file, trial_id=args.trial_id, blender=args.blender,
                                timeout=args.timeout, max_rounds=args.max_rounds, max_total_seconds=args.max_total_seconds)
    print(json.dumps({key: value for key, value in result.items() if key != 'agent'}, indent=2))
    return 0 if result['final_status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
