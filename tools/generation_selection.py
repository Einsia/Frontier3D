"""Immutable first-success selection without taking ownership of live jobs."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import hashlib

import json

from pathlib import Path

def payload_digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

def index_path(queue):
    return Path(str(queue) + '.generation-selection.json')

def result_path(folder):
    selected = Path(folder) / 'selected-generation.json'
    return selected if selected.is_file() else Path(folder) / 'generate-result.json'

def project(queue, rows):
    path = index_path(queue)
    if not path.is_file():
        return rows
    selections = json.loads(path.read_text()).get('selections', {})
    result = []
    for row in rows:
        winner = selections.get(row['identity']) if row['resource'].startswith('generation:') else None
        if winner:
            if winner['payload_sha256'] != payload_digest(row['payload']):
                raise ValueError('Selected generation task inputs changed: ' + row['identity'])
            row = {**row, 'physical_status': row['status'], 'status': 'completed',
                   'finished': winner['finished'], 'result': json.dumps(winner['result']),
                   'generation_race_winner': winner['branch']}
        result.append(row)
    return result

def earliest(original, alternate):
    candidates = [(label, row) for label, row in [('original', original), ('new_key', alternate)]
                  if row and row['status'] == 'completed']
    return min(candidates, key=lambda x: (x[1]['finished'], x[0])) if candidates else None
