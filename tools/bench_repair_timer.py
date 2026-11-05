"""Directory helper only; no background timer in the release."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from pathlib import Path

def mkdir(path): Path(path).mkdir(parents=True,exist_ok=True)
