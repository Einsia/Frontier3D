"""Validate L2 evidence from an explicitly trusted controller-owned run root."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .spec import L2_EVALUATOR_VERSION, relative_path


def file_hash(root, name):
    path = root / relative_path(name)
    cursor = root
    if root.is_symlink():
        raise ValueError("Symlink trusted root")
    for part in Path(name).parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("Symlink in trusted evidence")
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError(f"Missing or linked evidence: {name}")
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_record(record, spec, hashes, *, record_path=None, trusted_runs_root=None, submission=None,
                    assets_root=None, task_id=None, harness_config=None):
    from harness.L2.audit import AUDIT_VERSION, record_digest
    from harness.L2.config import load_policy
    from src.generator.task_adapter import load_benchmark_task

    if record_path is None or trusted_runs_root is None:
        raise ValueError("L2 record requires an explicit trusted run root and record path")
    record_path, trusted_runs_root = Path(record_path).absolute(), Path(trusted_runs_root).absolute()
    run = record_path.parent
    if (run.parent.resolve() != trusted_runs_root.resolve() or record_path.name != 'harness_record.json'
            or run.name != record.get('run_id') or Path(submission).resolve() != (run/'submission').resolve()):
        raise ValueError("Record/submission must belong to the declared trusted run")
    file_hash(trusted_runs_root, f'{run.name}/harness_record.json')
    if json.loads(record_path.read_text()) != record:
        raise ValueError("Record differs from the trusted on-disk record")
    if record.get('schema_version') != 3 or record.get('integrity_version') != AUDIT_VERSION:
        raise ValueError("Unsupported L2 execution/integrity record version")
    if record.get('record_sha256') != record_digest(record):
        raise ValueError("L2 record self-hash is invalid")
    if (record.get('task_id') != task_id or record.get('evaluator_version') != L2_EVALUATOR_VERSION
            or record.get('spec_sha256') != spec.digest or record.get('artifact_sha256') != hashes):
        raise ValueError("L2 task, evaluator, spec or artifacts do not match")
    task = load_benchmark_task(Path(assets_root))
    if task.task_id != task_id:
        raise ValueError("Unexpected task assets")
    config = Path(harness_config) if harness_config else task.root/'harness/harness.toml'
    policy = load_policy(config, task_id, spec)
    if record.get('harness_config_sha256') != policy.digest or record.get('harness_version') != policy.version:
        raise ValueError("Harness configuration does not match")
    expected_inputs = {str(p): file_hash(task.environment_dir, str(p)) for p in task.environment_files}
    if tuple(map(str, task.environment_files)) != policy.environment_files or record.get('input_sha256') != expected_inputs:
        raise ValueError("Task input hashes/allowlist do not match")
    generation = record.get('generation')
    if generation and generation.get('input_sha256') != expected_inputs:
        raise ValueError('Generation used different task inputs')
    if record.get('source_code_sha256') != file_hash(run, 'evidence/solution.py'):
        raise ValueError("Frozen source hash does not match")
    copied_policy = load_policy(run/'evidence/harness.toml', task_id, spec)
    from .l2_requirements import digest
    expected_requirements = digest(policy.requirements) if policy.requirements else None
    if (record.get('requirements_sha256') != expected_requirements
            or copied_policy.requirements != policy.requirements):
        raise ValueError('Frozen requirements differ from expected requirements')
    if copied_policy.digest != policy.digest:
        raise ValueError("Frozen policy differs from expected policy")
    from .spec import EvalSpec
    frozen_specs = list((run/'evidence').glob('eval_spec.*'))
    if len(frozen_specs) != 1 or EvalSpec.load(frozen_specs[0]).digest != spec.digest:
        raise ValueError('Frozen EvalSpec differs from expected specification')
    actual_evidence = {p.relative_to(run).as_posix(): file_hash(run, p.relative_to(run).as_posix())
                       for p in (run/'evidence').rglob('*') if p.is_file() or p.is_symlink()}
    if actual_evidence != record.get('evidence_sha256'):
        raise ValueError("Trusted evidence files/hashes do not match")
    runs = record.get('seed_runs')
    if not isinstance(runs, dict) or set(runs) != {str(s) for s in spec.seeds}:
        raise ValueError("Record must contain all frozen seeds")
    for seed, result in runs.items():
        if not isinstance(result, dict) or any(type(result.get(f)) is not bool for f in ('passed', 'execution_passed', 'integrity_passed', 'quality_passed', 'quality_evaluated')):
            raise ValueError("Invalid seed status")
        if json.loads((run/f'evidence/{seed}/result.json').read_text()) != result:
            raise ValueError("Seed summary differs from trusted seed evidence")
        if result['passed'] != (result['execution_passed'] and result['integrity_passed']):
            raise ValueError("Inconsistent seed aggregate")
        if result['integrity_passed'] and (result.get('execution', {}).get('status') != 'success'
                or result.get('audit', {}).get('version') != AUDIT_VERSION
                or result.get('audit', {}).get('passed') is not True
                or not result.get('input_unchanged') or not result.get('code_unchanged')
                or not result.get('artifacts_unchanged')
                or set(result.get('rerender', {})) != {v['artifact'] for v in policy.views}
                or any(v.get('passed') is not True for v in result['rerender'].values())):
            raise ValueError("Seed success lacks execution/audit/rerender evidence")
        for name, digest in result.get('artifact_sha256', {}).items():
            if file_hash(run, f'seed_runs/{seed}/workspace/{name}') != digest:
                raise ValueError("Seed artifact was changed")
        if result.get('input_unchanged'):
            for name, digest in expected_inputs.items():
                if file_hash(run, f'seed_runs/{seed}/workspace/{name}') != digest:
                    raise ValueError('Seed input was changed')
        if result.get('code_unchanged') and result.get('artifact_sha256', {}).get('solution.py') != record['source_code_sha256']:
            raise ValueError('Seed did not execute the frozen source')
    first = runs[str(spec.seeds[0])]
    bound = hashes == first['artifact_sha256'] and set(hashes) == set(spec.required_artifacts)
    for field in ('execution_passed', 'integrity_passed'):
        if record.get(field) is not bool(bound and all(r[field] for r in runs.values())):
            raise ValueError("Top-level status does not aggregate every seed")
    expected_status = 'verified' if bound and all(r['passed'] for r in runs.values()) else 'failed'
    if record.get('final_status') != expected_status:
        raise ValueError("Inconsistent final status")
    return record
