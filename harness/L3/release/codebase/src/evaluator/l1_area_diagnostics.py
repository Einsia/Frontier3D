"""Code015 protected-area diagnostics, independent of score-bearing gates.

Run after mandatory inspection/geometry. Each direction and format retains
its own bounds. Missing evidence or a diagnostic timeout is never zero area,
and cannot erase the already collected target/preservation measurements.
"""
from __future__ import annotations

import copy
import math
import time
from pathlib import Path

from .l1_compute import run_compute
from .l1_failures import InspectionFailure

PROTOCOL = 'l1-washer-area-diagnostic-v1'
FINAL_SCORE_RESERVE = 60.
JOB_LIMIT = 120.
RESULT_RESERVE = 5.
MINIMUM_JOB_BUDGET = 10.


def parameters(design):
    from .l1_washer_edit import validate_design
    validate_design(design)
    precision = design['preservation_tolerance_m']
    return {'center_xy': [0., 0.], 'radius': design['bore_radius_m']+design['dimension_tolerance_m'],
            'span': [-precision, design['height_m']+precision], 'tolerance': precision,
            'area_precision_m2': 1e-8, 'max_patches': 32768, 'max_depth': 12}


def measure(payload):
    """Called only by the trusted, killable compute worker."""
    from .l1_changed_area import compare_changed_area
    from .l1_surface import load_surface
    source = payload['source']
    deadline = payload['measurement_deadline']
    if (source.get('trusted_solid') is not True or type(deadline) not in (int, float)
            or not math.isfinite(deadline)):
        raise ValueError('Area diagnostics require bound valid-solid evidence and a finite deadline')
    policy = parameters(payload['design'])
    root = Path(payload['trusted_root'])
    candidate = load_surface(source['mesh_payload'], root)
    baseline = load_surface(source['baseline_mesh_payload'], root)
    result = compare_changed_area(candidate, baseline, **policy, deadline=deadline)
    return {'protocol': PROTOCOL, 'status': result['status'], 'hard_gate': False,
            'design': copy.deepcopy(payload['design']), 'source': copy.deepcopy(source),
            'parameters': policy, 'measurement': result,
            'scope': 'Two directed protected-surface areas only; not an edit, material or whole-task verdict'}


def collect_area_diagnostics(spec, evidence, output, *, deadline):
    jobs = {}
    for group in spec.checks.values():
        for check in group:
            if check.applicable and check.metric == 'washer_edit':
                jobs.setdefault(check.params['path'].rsplit('/', 1)[-1], check.params)
    if not jobs:
        return
    now = time.monotonic()
    # A caller without a global deadline still receives a finite local cap.
    parent_end = deadline if deadline is not None else now+JOB_LIMIT*len(jobs)+FINAL_SCORE_RESERVE
    if type(parent_end) not in (int, float) or not math.isfinite(parent_end):
        raise ValueError('Area diagnostics require a finite parent deadline')
    diagnostics_end = min(parent_end-FINAL_SCORE_RESERVE, now+JOB_LIMIT*len(jobs))
    results = evidence.setdefault('protected_area_diagnostics', {})
    for position, (key, params) in enumerate(jobs.items()):
        started = time.monotonic()
        share = min(JOB_LIMIT, max(0., diagnostics_end-started)/(len(jobs)-position))
        job_end = started+share
        budget = {'parent_deadline_monotonic': parent_end, 'diagnostics_deadline_monotonic': diagnostics_end,
                  'job_deadline_monotonic': job_end, 'measurement_deadline_monotonic': job_end-RESULT_RESERVE,
                  'final_score_reserve_seconds': FINAL_SCORE_RESERVE, 'maximum_job_seconds': JOB_LIMIT,
                  'minimum_job_seconds': MINIMUM_JOB_BUDGET, 'result_reserve_seconds': RESULT_RESERVE}
        row = {'protocol': PROTOCOL, 'status': 'not_measurable', 'hard_gate': False,
               'reason': 'Diagnostic not started', 'measurement': None, 'budget': budget,
               'design': copy.deepcopy(params['design']), 'source': None}
        results[key] = row
        try:
            numeric = evidence.get('numeric_checks', {}).get(key, {})
            source = numeric.get('source', {})
            if (numeric.get('protocol') != 'l1-washer-edit-v1' or numeric.get('design') != params['design']
                    or numeric.get('material_scope') != params['material_scope']
                    or source.get('trusted_solid') is not True
                    or not isinstance(source.get('mesh_payload'), dict)
                    or not isinstance(source.get('baseline_mesh_payload'), dict)):
                raise ValueError('Missing or mismatched washer geometry/design/format source')
            row['source'] = copy.deepcopy(source)
            if share < MINIMUM_JOB_BUDGET:
                row.update(reason='Insufficient diagnostic budget; final scoring reserve retained',
                           failure_code='AREA_DIAGNOSTIC_BUDGET_UNAVAILABLE')
                continue
            payload = {'source': copy.deepcopy(source), 'design': copy.deepcopy(params['design']),
                       'trusted_root': str(output), 'measurement_deadline': job_end-RESULT_RESERVE}
            measured = run_compute('washer_changed_area', payload, output=output/'area_jobs', deadline=job_end)
            if isinstance(measured, dict) and 'compute_execution' in measured:
                row['compute_execution'] = measured['compute_execution']
            if (not isinstance(measured, dict) or measured.get('protocol') != PROTOCOL or measured.get('source') != source
                    or measured.get('design') != params['design'] or measured.get('hard_gate') is not False):
                raise ValueError('Area result does not match the requested source/design/diagnostic scope')
            row.update(measured, reason=None if measured['status'] == 'measured' else
                       'Area precision not reached; retain directed bounds and per-direction reasons')
        except (InspectionFailure, OSError, ValueError) as error:
            row.update(status='not_measurable', reason=str(error), failure_code=getattr(error, 'code', type(error).__name__))
            if hasattr(error, 'compute_execution'):
                row['compute_execution'] = error.compute_execution
            # Deliberately do not call record_failure: this auxiliary job is
            # not a hard check, and must not poison successful numeric gates.
        except (KeyboardInterrupt, SystemExit) as error:
            row.update(status='interrupted', reason=type(error).__name__)
            if hasattr(error, 'compute_execution'):
                row['compute_execution'] = error.compute_execution
            raise
        finally:
            row['elapsed_seconds'] = time.monotonic()-started
