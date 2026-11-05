"""Small I/O helpers; production queues and services are not distributed."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from pathlib import Path

from orchestrator.tasks import write_json as atomic

import json

def load(path): return json.loads(Path(path).read_text())
