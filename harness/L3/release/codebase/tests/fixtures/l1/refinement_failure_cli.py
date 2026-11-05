#!/usr/bin/env python3
"""Real subprocess failure fixture; never contacts a model service."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

prompt = sys.stdin.read()
output = Path(sys.argv[sys.argv.index('--output-last-message') + 1])
mode = os.environ['FAKE_CODEX_MODE']
if mode in {'generation_interrupt', 'timeout_retry'} and output.parent.name == 'attempt-0001':
    child_path = output.parent / 'fixture-child.json'
    child_source = (
        'import os, signal, time; from pathlib import Path; '
        'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
        f'Path({str(child_path)!r}).write_text(str(os.getpid())); time.sleep(60)'
    )
    child = subprocess.Popen([sys.executable, '-c', child_source], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    while not child_path.exists():
        time.sleep(.01)
    (Path.cwd() / 'dirty-retry-file').write_text('must not survive attempt staging')
    (output.parent / 'fixture-process.json').write_text(json.dumps({
        'pid': os.getpid(), 'child_pid': child.pid, 'workspace': str(Path.cwd()), 'mode': mode,
    }))
    time.sleep(60)

assert not (Path.cwd() / 'dirty-retry-file').exists(), 'prior attempt leaked'
source = 'import bpy\nbpy.ops.wm.read_factory_settings(use_empty=True)\n'
if mode == 'execution_interrupt':
    source += (
        'import os, json, time\nfrom pathlib import Path\n'
        "Path('fixture-baseline.json').write_text(json.dumps({'pid':os.getpid()}))\n"
        'time.sleep(60)\n'
    )
source += 'bpy.ops.mesh.primitive_cube_add(size=.01)\n'
source += "bpy.ops.export_scene.gltf(filepath='scene.glb', export_format='GLB')\n"
output.write_text(json.dumps({
    'protocol': 'l1-submission-bundle-v1', 'entrypoint': 'solution.py',
    'files': [{'path': 'solution.py', 'encoding': 'utf-8', 'content': source}],
    'runtime': 'Blender Python', 'dependencies': ['bpy (bundled)'],
    'run_instructions': 'Run solution.py in Blender.',
}))
