"""L1 round/seed/source/RNG binding, not an RNG-observability or sandbox proof."""

from __future__ import annotations

import json

from .attempt_log import sha256_bytes
from .rng_evidence import observation_scope

PROTOCOL = 'l1-round-execution-binding-v1'


def validate_repair_round(value):
    if type(value) is not int or value < 0:
        raise ValueError('repair_round must be a nonnegative integer')
    return value


def bind_execution(*, task_id, trial_id, repair_round, program_seed, source_digest,
                   execution, artifacts):
    """Bind the actual returned trace, including missing/invalid observations.

    A timeout is allowed to have no trace. The expected program seed and the
    observed trace seed remain separate; labels do not imply candidate RNG use.
    Candidate stdout is not an adversarially trusted trace transport (G08).
    """
    validate_repair_round(repair_round)
    trace = execution.rng_trace if execution is not None else None
    trace_digest, trace_seed = None, None
    rng_status = 'not_configured'
    if trace is not None:
        rng_status = 'invalid'
        if isinstance(trace, dict):
            raw_seed = trace.get('program_seed')
            trace_seed = raw_seed if type(raw_seed) is int else None
            try:
                trace_digest = sha256_bytes(json.dumps(trace, sort_keys=True, allow_nan=False).encode())
                if (trace.get('protocol') == 'l1-rng-trace-v1' and trace.get('status') == 'observed'
                        and type(trace_seed) is int and trace_seed == program_seed):
                    rng_status = 'observed'
            except (TypeError, ValueError):
                pass
    return {
        'protocol': PROTOCOL, 'task_id': task_id, 'trial_id': trial_id, 'repair_round': repair_round,
        'program_seed': program_seed, 'source_snapshot_digest': source_digest,
        'execution_status': execution.status if execution is not None else 'not_started',
        'artifact_sha256': dict(artifacts), 'rng_trace_sha256': trace_digest,
        'rng_trace_program_seed': trace_seed, 'rng_status': rng_status,
        'rng_observation_scope': observation_scope(trace, trace_status=rng_status),
        'scope': 'execution_return_bound_to_declared_round_seed_and_frozen_source',
        'not_assessed': ['unobserved_internal_rngs', 'adversarial_trace_authenticity'],
    }
