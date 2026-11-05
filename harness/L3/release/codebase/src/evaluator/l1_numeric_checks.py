"""Collect declared, case-specific L1 geometry checks in bounded CPU jobs."""
import time

from .l1_compute import run_compute
from .l1_failures import InspectionFailure, record_failure
from .metrics import MissingEvidence, resolve


def collect_numeric_checks(spec, evidence, output, *, deadline, assets_root=None):
    jobs = {}
    for group in spec.checks.values():
        for check in group:
            if check.applicable and check.metric in {'machined_sleeve', 'washer_edit', 'swept_bar', 'slot_plate_edit'}:
                jobs.setdefault(check.params['path'], (check.metric, check.params))
    if not jobs:
        return
    results = evidence.setdefault('numeric_checks', {})
    for index, (pointer, (operation, params)) in enumerate(jobs.items()):
        key = pointer.rsplit('/', 1)[-1]
        try:
            scene = resolve(evidence, params['scene'])
            payload = {'scene': scene, 'design': params['design'], 'trusted_root': str(output)}
            if operation in {'washer_edit', 'slot_plate_edit'}:
                payload.update(baseline=resolve(evidence, params['baseline']), material_scope=params['material_scope'])
            job_deadline = deadline
            if operation == 'slot_plate_edit':
                now = time.monotonic()
                # Share remaining work fairly across both actual formats, and
                # reserve 60 seconds for downstream scoring/publication.
                share = max(0., deadline-now-60)/(len(jobs)-index)
                if share <= 5:
                    raise InspectionFailure('not_measurable', 'PLATE_BUDGET_UNAVAILABLE',
                                            'No plate work budget before final scoring reserve')
                job_deadline = now+min(120., share)
                payload.update(material_tolerance=params['material_tolerance'], measurement_deadline=job_deadline-5,
                               quality_mode='l1_edit_quality' in spec.to_dict())
            if operation == 'swept_bar':
                if assets_root is None:
                    raise ValueError('Sweep reference assets root is required')
                payload['assets_root'] = str(assets_root)
            results[key] = run_compute(operation, payload, output=output / 'numeric_jobs', deadline=job_deadline)
        except (InspectionFailure, MissingEvidence, OSError, ValueError) as error:
            if isinstance(error, InspectionFailure):
                failure = error
            else:
                failure = InspectionFailure('not_measurable' if isinstance(error, MissingEvidence) else 'infrastructure_error',
                                            operation.upper()+'_MEASUREMENT_UNAVAILABLE', str(error))
            results[key] = {'status': failure.status, 'passed': False, 'reason': str(failure)}
            if hasattr(error, 'compute_execution'):
                results[key]['compute_execution'] = error.compute_execution
            record_failure(spec, evidence, [pointer], failure)
