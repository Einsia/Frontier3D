"""Shared released L1/L2 generation policy; judge effort is independent."""
import hashlib
import json
import math
from pathlib import Path
from src.generator.harnesses import model_effort

PATH = Path(__file__).resolve().parents[2] / 'configs/release/experiment-policy.json'
POLICY = json.loads(PATH.read_text())
POLICY_SHA256 = hashlib.sha256(PATH.read_bytes()).hexdigest()
EFFORT = POLICY['generation_effort']
ATTEMPTS = POLICY['generation_attempts']
GENERATION_TIMEOUT = POLICY['generation_attempt_timeout_seconds']
GENERATION_TOTAL_TIMEOUT = POLICY['generation_total_timeout_seconds']
EXECUTION_TIMEOUT = POLICY['execution_timeout_seconds']
EVALUATION_TIMEOUT = POLICY['evaluation_timeout_seconds']

def validate_options(options):
    expected = model_effort(options.get('model'))
    if options.get('effort') != expected:
        raise ValueError('Released model generation effort must be '+expected)
    if options.get('attempts') != ATTEMPTS:
        raise ValueError('Released L1/L2 uses six total attempts (five retries)')
    for name, ceiling in [('generation_timeout', GENERATION_TIMEOUT),
                          ('generation_total_timeout', GENERATION_TOTAL_TIMEOUT),
                          ('execution_timeout', EXECUTION_TIMEOUT),
                          ('evaluation_timeout', EVALUATION_TIMEOUT)]:
        value=options.get(name,ceiling)
        if type(value) not in (int,float) or not math.isfinite(value) or not 0 < value <= ceiling:
            raise ValueError(name+' must be positive, finite and at most '+str(ceiling))
    if options['generation_timeout'] > options.get('generation_total_timeout',GENERATION_TOTAL_TIMEOUT):
        raise ValueError('Generation attempt limit exceeds the shared generation budget')

def binding(options):
    return {'version':POLICY['version'],'policy_sha256':POLICY_SHA256,
            **{k:options[k] for k in ['effort','attempts','generation_timeout','execution_timeout','evaluation_timeout']},
            'generation_total_timeout':options.get('generation_total_timeout',GENERATION_TOTAL_TIMEOUT)}
