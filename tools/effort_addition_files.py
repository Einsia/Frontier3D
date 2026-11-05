"""Check complete retained files and public PNG dimensions for new tasks."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from pathlib import Path

import re

import tomllib

from PIL import Image

from src.evaluator.l1_edit_validity import gate

from tools.evaluate_linear_candidate import pin

def file_contract(task, manifest, generation):
    metadata = tomllib.loads((task / 'task.toml').read_text())
    required = [str(Path(name).relative_to('output')) for name in metadata['submission_files']]
    sizes = set(re.findall(r'(\d+)\s*[x×]\s*(\d+) pixels', (task / 'instruction.md').read_text()))
    match = next(iter(sizes)) if len(sizes) == 1 else None
    if not match:
        raise ValueError('One explicit image dimension contract required')
    expected_size = tuple(map(int, match))
    results = {}
    for seed in ('primary', 'seed-0', 'seed-1', 'seed-2'):
        artifacts = manifest['variants'][seed]
        execution = generation['execution'] if seed == 'primary' else manifest['executions'][seed]
        trusted = (execution.get('status') == 'success' and execution.get('inputs_unchanged') is True
                   and execution.get('source_unchanged') is True)
        complete = all(name in artifacts for name in required)
        for pointer in artifacts.values():
            pin(pointer['path'], pointer['sha256'])
        bound = all(execution.get('artifact_sha256', {}).get(name) == artifacts[name]['sha256']
                    for name in required if name in artifacts)
        files_ok = complete and all(Path(artifacts[name]['path']).stat().st_size > 0 for name in required)
        image_checks = {}
        for name in required:
            if not name.endswith('.png'):
                continue
            image_ok = False
            if name in artifacts:
                with Image.open(artifacts[name]['path']) as image:
                    image.load()
                    image_ok = image.format == 'PNG' and image.size == expected_size
            image_checks[name] = image_ok
        image_ok = bool(image_checks) and all(image_checks.values())
        results[seed] = {
            'execution': gate('passed' if trusted and bound else 'not_measurable'),
            'required_files': gate('passed' if files_ok else 'failed', required=required),
            'image_format_dimensions': gate('passed' if image_ok else 'failed', expected_size=list(expected_size), images=image_checks),
        }
    return results
