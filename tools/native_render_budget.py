"""Explicit bounded render recovery for reviewed, hash-bound native scenes."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import json

from pathlib import Path

POLICY = Path(__file__).resolve().parents[1]/'configs/evaluation/native-render-recovery.json'

def budget(scene_sha256, default_seconds, default_threads):
    if not POLICY.exists():
        return default_seconds, default_threads
    policy = json.loads(POLICY.read_text())
    entry = policy.get('scenes', {}).get(scene_sha256)
    if entry is None:
        return default_seconds, default_threads
    seconds, threads = entry['seconds'], entry['threads']
    if (type(seconds) is not int or not default_seconds <= seconds <= 7200
            or type(threads) is not int or not default_threads <= threads <= 8):
        raise ValueError('Invalid reviewed native render budget')
    return seconds, threads
