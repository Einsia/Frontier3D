#!/usr/bin/env python3
"""Process-level CLI double, explicitly not a model service or scoring oracle."""

import json
import re
import sys
from pathlib import Path

prompt = sys.stdin.read()
index = int(re.search(r'Harness repair round: (\d+)', prompt).group(1))
output = Path(sys.argv[sys.argv.index('--output-last-message') + 1])
workspace = Path.cwd()
seen = sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob('*') if p.is_file())
(output.parent / 'cli-observation.json').write_text(json.dumps({
    'repair_round': index, 'seen_files': seen, 'prompt': prompt, 'workspace': str(workspace),
    'kind': 'test_only_cli_double_no_model_service',
}))
if index == 0 and output.parent.name == 'attempt-0001':
    (workspace / 'stale-attempt.txt').write_text('Do not carry this into a retry')
    raise SystemExit(7)
if 'stale-attempt.txt' in seen:
    raise SystemExit('Attempt input leaked from an earlier call')
if index == 1 and 'previous_submission/obsolete.txt' not in seen:
    raise SystemExit('Prior declared source was not staged')
count = 1 if index == 0 else 2
source = (
    'import bpy\n'
    'bpy.ops.wm.read_factory_settings(use_empty=True)\n'
    f'for i in range({count}):\n'
    '    bpy.ops.mesh.primitive_cube_add(size=.01, location=(.03*i,0,0))\n'
    "bpy.ops.export_scene.gltf(filepath='scene.glb', export_format='GLB')\n"
)
files = [{'path': 'solution.py', 'encoding': 'utf-8', 'content': source}]
if index == 0:
    files.append({'path': 'obsolete.txt', 'encoding': 'utf-8', 'content': 'Removed in the next full replacement'})
output.write_text(json.dumps({'protocol': 'l1-submission-bundle-v1', 'entrypoint': 'solution.py', 'files': files,
                             'runtime': 'Blender Python', 'dependencies': ['bpy (bundled)'],
                             'run_instructions': 'Run solution.py inside Blender.'}))
