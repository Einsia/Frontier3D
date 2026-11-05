"""Usage aggregation helpers; missing provider counters remain explicit."""

from __future__ import annotations
import os

import argparse

from collections import Counter

import csv

from datetime import datetime, timezone

from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from src.agent_judge.protocol import digest, read_json, write_json

from src.run_usage import estimate_cost, normalize_usage

TOKEN_FIELDS = ['input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
                'output_tokens', 'reasoning_output_tokens', 'total_tokens']

def summarize_calls(calls, pricing):
    unique = {}
    for call in calls:
        identity = call['id']
        if identity in unique and call != unique[identity]:
            raise ValueError('Conflicting records for one call')
        unique[identity] = call
    selected = list(unique.values())
    usage = [normalize_usage(c.get('usage')) for c in selected]
    costs = [estimate_cost(u, c.get('model'), pricing) for c, u in zip(selected, usage)]
    known_usage = [u for u in usage if u is not None]
    known_cost = [c for c in costs if c is not None]
    partial=sum(u is not None and c.get('usage_coverage')=='partial' for c,u in zip(selected,usage))
    def known_sum(values):
        values = [v for v in values if v is not None]
        return sum(values) if values else None
    return {'calls': len(selected), 'usage_calls': len(known_usage), 'priced_calls': len(known_cost),
        'complete_usage_calls':len(known_usage)-partial,'partial_usage_calls':partial,
        'usage_complete': bool(selected) and len(known_usage) == len(selected) and not partial,
        'pricing_complete': bool(selected) and len(known_cost) == len(selected) and not partial,
        'tokens': {k: known_sum(u[k] for u in known_usage) for k in TOKEN_FIELDS},
        'token_field_coverage': {k: sum(u[k] is not None for u in known_usage) for k in TOKEN_FIELDS},
        'legacy_cli_reported_tokens': known_sum(c.get('cli_reported_tokens') for c in selected if not c.get('usage')),
        'known_cost_lower_usd': known_sum(c['lower_usd'] for c in known_cost),
        'known_cost_upper_usd': known_sum(c['upper_usd'] for c in known_cost),
        'seconds': known_sum(c.get('seconds') for c in selected),
        'session_ids': sorted({s for c in selected for s in c.get('session_ids', [])}),
        'rollout_calls': sum(c.get('rollout_retained', False) for c in selected),
        'cost_scope': 'observed_priced_calls_only', 'actual_charge': False}

def select_active(registry, index, task_ids, batch_reader):
    """Registry order and explicit task_ids/levels define selection, never score."""
    selected = {}
    for model in registry['models']:
        for pointer in model.get('batches', []):
            batch = batch_reader(pointer)
            if batch['model'] != model['id']: raise ValueError('Model/batch mismatch')
            allowed = set(pointer.get('task_ids', task_ids)) & set(task_ids)
            for row in batch.get('cases', []):
                task_id = row['task_id']
                if task_id not in allowed: continue
                level = int(task_id.split('/')[0][1:])
                if pointer.get('levels') and level not in pointer['levels']: continue
                identity = (model['id'], task_id)
                if identity in selected: continue
                observation = index.get('records', {}).get('\n'.join([batch['id'], model['id'], task_id]))
                anchor = row.get('run_sha256') or row.get('report_sha256')
                if observation and (not anchor or observation.get('anchor') != anchor):
                    raise ValueError('Usage observation does not match selected result')
                selected[identity] = {'observation': observation, 'cohort': pointer.get('cohort'),
                                      'batch_id': batch['id'], 'anchor': anchor}
    return selected
