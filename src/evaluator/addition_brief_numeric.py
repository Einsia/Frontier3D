'''Final native numeric score for the added Brief2Scene tasks.

A frozen check counts only when the native audit marks it satisfied. Partial,
observed and violated rows stay in the denominator. Unavailable measurements
block the component, following the original unmeasured-no-redistribution policy.
'''

STATUSES = {'satisfied', 'violated', 'partial', 'observed', 'not_measurable'}
UNRESOLVED = {'partial', 'observed', 'not_measurable'}


def numeric_data_score(report, plan):
    checks = [c['id'] for c in plan['native_content_checks']]
    if not checks or len(set(checks)) != len(checks):
        raise ValueError('Frozen numeric checks must be unique and nonempty')
    if report.get('status') != 'audited' or report.get('case_id') != plan['task_id']:
        raise ValueError('Accepted native numeric audit required')
    rows = {r['id']: r for r in report['requirements']}
    if set(rows) != set(checks) or len(rows) != len(report['requirements']):
        raise ValueError('Numeric audit does not match the frozen checks')
    counts = {}
    for row in rows.values():
        counts[row['status']] = counts.get(row['status'], 0) + 1
    if set(counts) - STATUSES:
        raise ValueError('Unknown numeric audit status')
    missing = sorted(i for i, r in rows.items() if r['status'] == 'not_measurable')
    return {'status': 'not_measurable' if missing else 'measured',
            'score': None if missing else counts.get('satisfied', 0) / len(checks), 'counts': counts,
            'checks': len(checks),
            'missing_checks': missing,
            'unresolved': sorted(i for i, r in rows.items() if r['status'] in UNRESOLVED)}
