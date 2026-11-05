"""Run from the repository: python -m orchestrator list|run."""
import argparse
import json
from pathlib import Path

from .runner import run_case
from .feedback import DEFAULT_ATTEMPTS
from harness.common.experiment_policy import GENERATION_TIMEOUT, GENERATION_TOTAL_TIMEOUT, EXECUTION_TIMEOUT, EVALUATION_TIMEOUT, validate_options
from .tasks import PROJECT, TASKS, inventory


def main():
    parser = argparse.ArgumentParser(description='External L1/L2 case generation, execution and evaluation')
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('list')
    listing.add_argument('--level', type=int, choices=(1,2), default=1)
    listing.add_argument('--tasks-root', type=Path, default=TASKS)
    run = commands.add_parser('run')
    run.add_argument('--task', required=True)
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument('--submission', type=Path)
    source.add_argument('--generate', action='store_true', dest='generate_code')
    run.add_argument('--tasks-root', type=Path, default=TASKS)
    run.add_argument('--output-root', type=Path, default=PROJECT / 'data/task_runs')
    run.add_argument('--blender', type=Path)
    run.add_argument('--runtime', choices=('docker', 'local'), default='docker')
    run.add_argument('--image', default='3dbench-l1-blender:mvp')
    run.add_argument('--timeout', type=float, default=None)
    run.add_argument('--attempt-timeout', type=float, default=EXECUTION_TIMEOUT)
    run.add_argument('--attempts', type=int, choices=[DEFAULT_ATTEMPTS], default=DEFAULT_ATTEMPTS,
                     help='Total model calls per task and executions per seed, including the first (default: 6 = 5 retries)')
    run.add_argument('--skip-reproduction', action='store_false', dest='reproduction')
    run.add_argument('--generator-runtime', choices=('docker', 'local'), default='docker')
    run.add_argument('--generator-image')
    run.add_argument('--generation-timeout', type=float, default=GENERATION_TIMEOUT)
    run.add_argument('--reproduction-timeout', type=float, default=EXECUTION_TIMEOUT)
    run.add_argument('--generation-total-timeout', type=float, default=GENERATION_TOTAL_TIMEOUT)
    run.add_argument('--env-file', type=Path)
    options = vars(parser.parse_args())
    command = options.pop('command')
    if command == 'list':
        print(json.dumps(list(inventory(**options)), ensure_ascii=False, indent=2))
        return 0
    try:
        validate_options({'effort':'max','attempts':options['attempts'],
            'generation_timeout':options['generation_timeout'],
            'generation_total_timeout':options['generation_total_timeout'],
            'execution_timeout':options['attempt_timeout'],'evaluation_timeout':EVALUATION_TIMEOUT})
        if not 0 < options['reproduction_timeout'] <= EXECUTION_TIMEOUT:
            raise ValueError('Reproduction timeout exceeds the released execution cap')
        limit=EVALUATION_TIMEOUT+(options['generation_total_timeout'] if options['generate_code'] else 0)
        if options['timeout'] is not None and not 0 < options['timeout'] <= limit:
            raise ValueError('Combined task timeout exceeds the released stage budgets')
    except ValueError as error:parser.error(str(error))
    options['task_id'] = options.pop('task')
    if options['task_id'].startswith('L2/'):
        from .l2_runner import run_case as run_l2_case
        result = run_l2_case(**options)
    else:
        result = run_case(**options)
    print(json.dumps({k: result.get(k) for k in ('status', 'run_dir', 'case_pass', 'S_core', 'S_diagnostic', 'error')}, ensure_ascii=False))
    return 0 if result['status'] == 'scored' else 2


if __name__ == '__main__':
    raise SystemExit(main())
