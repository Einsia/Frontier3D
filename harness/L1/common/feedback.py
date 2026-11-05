"""Allowlisted model feedback; never forward free-form evaluator evidence."""

from __future__ import annotations

from typing import Any

from src.evaluator.spec import EvalSpec

PUBLIC_FEEDBACK_PROTOCOL = 'l1-public-feedback-v1'
GUIDANCE = {
    'passed': 'All required checks passed.',
    'failed': 'Review the listed requirements in the task instructions and revise the submission.',
    'incomplete': 'Some required checks are not fully assessed. Do not infer task completion.',
    'unavailable': 'Assessment is unavailable. Check that the submission follows the declared execution instructions.',
}
OUTCOMES = {'passed', 'failed', 'not_implemented', 'not_measurable', 'infrastructure_error', 'not_applicable'}


def _requirements(spec: EvalSpec) -> dict[str, Any]:
    raw = spec.to_dict()
    protocol = raw.get('l1_protocol')
    if spec.profile != 'L1' or not protocol or protocol['version'] != 'l1-requirements-v1':
        raise ValueError('Public feedback requires a frozen L1 requirements protocol')
    return {row['id']: row for row in protocol['requirements']}


def validate_public_feedback(feedback: dict[str, Any], spec: EvalSpec) -> dict[str, Any]:
    """Strict service transport, unlike the legacy callback's shape validation.

    IDs come only from the frozen task policy. No arbitrary numeric metrics,
    error strings, coordinates, paths or user-provided guidance can be relayed.
    """
    declared = _requirements(spec)
    if not isinstance(feedback, dict) or set(feedback) != {'status', 'failed_requirements', 'public_metrics', 'guidance'}:
        raise ValueError('Public feedback must use exactly the allowlisted fields')
    status = feedback['status']
    if not isinstance(status, str) or status not in GUIDANCE:
        raise ValueError('Public feedback status is not allowlisted')
    failed = feedback['failed_requirements']
    if not isinstance(failed, list) or any(not isinstance(item, str) for item in failed):
        raise ValueError('Public feedback requires declared requirement IDs')
    if len(failed) != len(set(failed)) or any(item not in declared or not declared[item]['applicable'] for item in failed):
        raise ValueError('Public feedback contains duplicate, unknown or inapplicable requirement IDs')
    if (status != 'failed' and failed) or (status == 'failed' and not failed):
        raise ValueError('Public feedback status contradicts failed requirement IDs')
    if feedback['public_metrics'] != {} or feedback['guidance'] != GUIDANCE[status]:
        raise ValueError('Public feedback metrics and guidance must match the frozen allowlist')
    if status == 'passed' and any(row['required'] and row['implementation'] != 'complete' for row in declared.values()):
        raise ValueError('Incomplete task implementation cannot produce passed feedback')
    return {'status': status, 'failed_requirements': sorted(failed), 'public_metrics': {}, 'guidance': GUIDANCE[status]}


def public_feedback_from_report(report: dict[str, Any] | None, spec: EvalSpec, *, execution_status: str) -> dict[str, Any]:
    """Reduce a trusted evaluator report to public coarse outcomes only.

    Callers must bind the trusted report to the current run before invoking this
    function. A matching digest is a configuration check, not authentication.
    """
    from src.evaluator.l1_finalization import is_finalized

    declared = _requirements(spec)
    status, failed = 'unavailable', []
    if report is not None:
        if not isinstance(report, dict) or report.get('spec_sha256') != spec.digest:
            raise ValueError('Feedback report does not match the frozen EvalSpec')
        coverage = report.get('coverage')
        rows = coverage.get('requirements') if isinstance(coverage, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get('id'), str) for row in rows):
            raise ValueError('Feedback report lacks complete requirement coverage')
        observed = {row['id']: row for row in rows}
        if len(observed) != len(rows) or set(observed) != set(declared):
            raise ValueError('Feedback report has missing, duplicate or unknown requirements')
        for key, row in observed.items():
            outcome = row.get('status')
            if not isinstance(outcome, str) or outcome not in OUTCOMES:
                raise ValueError('Feedback report has unknown requirement outcome')
            if (outcome == 'not_applicable') == declared[key]['applicable']:
                raise ValueError('Feedback report changed requirement applicability')
            if declared[key]['implementation'] != 'complete' and declared[key]['applicable'] and outcome != 'not_implemented':
                raise ValueError('Feedback report treats incomplete implementation as measured')
        required = [observed[key]['status'] for key, row in declared.items() if row['required']]
        failed = [key for key, row in observed.items() if row['status'] == 'failed' and declared[key]['required']]
        if (execution_status not in {'success', 'executed', 'evaluated', 'scored'} or report.get('scoring_failed')
                or report.get('budget_exhausted') or report.get('scoring_status') == 'unavailable'
                or not is_finalized(report)):
            failed = []
        elif failed:
            status = 'failed'
        elif required and all(outcome == 'passed' for outcome in required) and report.get('case_pass') is True and report.get('task_completion') == 'complete':
            status = 'passed'
        else:
            status = 'incomplete'
    return validate_public_feedback({'status': status, 'failed_requirements': failed,
                                     'public_metrics': {}, 'guidance': GUIDANCE[status]}, spec)
