"""Collect registered native evidence for frozen Brief2Scene numeric checks.

No total or numeric quality score is inferred from audit status labels.
"""
import os

import argparse

import fcntl

from pathlib import Path

import sys

import tempfile

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from dotenv import dotenv_values

from jsonschema import ValidationError

from src.agent_judge.protocol import read_json as read

from src.agent_judge.runtime import run_codex

from tools.audit_new_task_constraints import prepare_packet, validate_response, PROTOCOL

from tools.evaluate_linear_candidate import atomic, pin

from tools.evaluate_new_task import worker

from tools.experiment_identity import tested_model

from tools.run_new_tasks import jobdir, verify_task, record_call

from tools.watch_effort_historical import affected

def attempt_limit(folder, bindings, attempts):
    policy_path = folder / 'recovery.json'
    if not policy_path.exists():
        return 3
    policy = read(policy_path)
    if policy['source_bindings'] != bindings:
        raise ValueError('Numeric recovery candidate or contract changed')
    pointer = policy['previous_attempts']
    pin(pointer['path'], pointer['sha256'])
    previous = read(Path(pointer['path']))
    if attempts[:len(previous)] != previous:
        raise ValueError('Numeric recovery history changed')
    if (len(previous) != 3 or policy['maximum_attempts'] != 4
            or any(a['status'] != 'technical_failure' for a in previous)
            or 'Measurement not bound to this requirement:' not in previous[-1].get('error', '')):
        raise ValueError('Recovery requires reviewed evidence-binding failure')
    for evidence in policy['evidence']:
        pin(evidence['path'], evidence['sha256'])
    return 4

def run(root, task_id):
    campaign = read(root / 'campaign.json')
    row = next(r for r in campaign['records'] if r['task_id'] == task_id)
    verify_task(root, row)
    if row['category'] != 'Brief2Scene':
        raise ValueError('Brief numeric contract required')
    source = jobdir(root, tested_model(root), task_id)
    generation = read(source / 'generation_state.json')
    if generation['status'] != 'completed' or affected(source):
        raise ValueError('Clean accepted generation required')
    config = resource('addition_config') / Path(task_id).name
    plan = read(config / 'plan.json')
    pin(plan['rules']['path'], plan['rules']['sha256'])
    pin(plan['instruction']['path'], plan['instruction']['sha256'])
    for name, expected in generation['artifact_sha256'].items():
        pin(Path(generation['output']) / name, expected)
    spec = {'protocol': PROTOCOL, 'case_id': task_id,
        'instruction_sha256': row['instruction_sha256'],
        'requirements': [{'id': check['id'], 'numeric': True,
            'text': check['source_quote'] + '\nNative measurement definition: ' + check['measurement_definition'],
            'frozen_numeric_check': check} for check in plan['native_content_checks']]}
    if not spec['requirements']:
        raise ValueError('Explicit numeric requirements required')
    folder = source / 'legacy_numeric'
    folder.mkdir(parents=True, exist_ok=True)
    bindings = {'generation': pin(source / 'generation_state.json'), 'plan': pin(config / 'plan.json')}
    with (folder / 'case.lock').open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (folder / 'report.json').exists():
            result = read(folder / 'report.json')
            if result['source_bindings'] != bindings:
                raise ValueError('Numeric audit source changed')
            return result
        native = worker(campaign, pin(Path(generation['output']) / 'scene.blend', generation['artifact_sha256']['scene.blend']),
                        folder / 'native', inspect_only=True, level=2)
        atomic(folder / 'native/catalogue.json', native)
        catalogue = pin(folder / 'native/catalogue.json')
        packet, manifest = prepare_packet(root, row, generation, spec, folder)
        attempts = read(folder / 'attempts.json') if (folder / 'attempts.json').exists() else []
        maximum = attempt_limit(folder, bindings, attempts)
        key = judge_key()
        with tempfile.TemporaryDirectory(prefix='effort-native-auth-') as temporary:
            import json
            auth = Path(temporary)
            atomic(auth / 'auth.json', {'OPENAI_API_KEY': key})
            (auth / 'auth.json').chmod(0o600)
            (auth / 'config.toml').write_text('model_provider="judge"\n[model_providers.judge]\nname="Judge"\nwire_api="responses"\nrequires_openai_auth=true\nbase_url=' + json.dumps(campaign['provider_url']) + '\n')
            for number in range(len(attempts) + 1, maximum + 1):
                directory = folder / f'attempt-{number}'
                attempt = {'attempt': number, 'status': 'running'}
                feedback = attempts[-1].get('error') if attempts else None
                attempts.append(attempt)
                atomic(folder / 'attempts.json', attempts)
                execution = run_codex(packet, directory, model=judge_model(), effort='medium',
                    codex=campaign['codex'], codex_home=auth, timeout=1800,
                    blender=campaign['blender'], api_key=key, measurement_catalogue=catalogue,
                    retry_feedback=feedback)
                record_call(root, role='judge', model=judge_model(), tested_model=tested_model(root),
                            task_id=task_id, directory=directory, execution=execution)
                try:
                    if execution.get('returncode') != 0 or execution.get('modified_inputs') or execution.get('timed_out'):
                        raise ValueError('Native audit runtime failed')
                    result = validate_response(read(directory / 'response.json'), spec, manifest, directory, catalogue)
                    result.update(source_bindings=bindings, judge_model=judge_model(), judge_effort='medium',
                        accepted_attempt=number, catalogue=catalogue, response=pin(directory / 'response.json'),
                        measurement_manifest=pin(directory / 'measurements/manifest.json'),
                        numeric_score=None, score_status='native_observations_require_scoring_validation')
                    attempt['status'] = 'accepted'
                    atomic(folder / 'attempts.json', attempts)
                    atomic(folder / 'report.json', result)
                    return result
                except (ValueError, KeyError, OSError, ValidationError) as error:
                    attempt.update(status='technical_failure', error=str(error).replace(key, '<redacted>'))
                    atomic(folder / 'attempts.json', attempts)
        raise ValueError('Native audit attempts exhausted; preserve evidence for recovery')
