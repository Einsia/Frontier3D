"""Same-process L2 execution capability; persisted JSON alone is never authority."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import weakref

from .tasks import regular, sha256
from src.evaluator.l2_requirements import digest

_ACTIVE = weakref.WeakKeyDictionary()


@dataclass(frozen=True, eq=False)
class ExecutionContext:
    record: Path
    trial_id: str
    model_call: bool


def issue_context(record, *, trial_id, model_call):
    context = ExecutionContext(Path(record).resolve(),trial_id,model_call)
    _ACTIVE[context] = sha256(context.record)
    return context


def validate_context(context, task_root, submission, spec, policy):
    if not isinstance(context,ExecutionContext) or context not in _ACTIVE:
        raise ValueError('An externally issued execution capability is required')
    if sha256(context.record) != _ACTIVE[context]:
        raise ValueError('Execution record changed after issue')
    record = json.loads(context.record.read_text())
    if (record['task_id'] != policy['task_id'] or record['spec_sha256'] != spec.digest
            or record['case_policy_sha256'] != digest(policy) or record['trial_id'] != context.trial_id
            or Path(record['submission']).resolve() != Path(submission).resolve()):
        raise ValueError('Execution task/spec/policy/submission binding mismatch')
    root = context.record.parent
    for name, expected in record['evidence_sha256'].items():
        if sha256(regular(root,name)) != expected:
            raise ValueError('Execution evidence changed: '+name)
    for name, expected in record['artifact_sha256'].items():
        if sha256(regular(Path(submission),name)) != expected:
            raise ValueError('Submission changed after execution')
    for name,expected in record['task_files_sha256'].items():
        if sha256(regular(Path(task_root),name)) != expected:
            raise ValueError('Task input/spec changed after execution')
    evidence = json.loads(regular(root,record['evidence_path']).read_text())
    if evidence['artifact_sha256'] != record['artifact_sha256']:
        raise ValueError('Evidence artifact binding mismatch')
    seeds = evidence.get('harness',{}).get('seed_runs',{})
    if set(seeds) != {str(s) for s in spec.seeds}:
        raise ValueError('Execution evidence must include all configured seeds')
    return evidence
