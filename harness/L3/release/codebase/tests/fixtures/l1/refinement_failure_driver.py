"""Trusted service driver with an explicit local CLI double, not a model."""

import json
import os
import sys
from pathlib import Path

args = json.loads(Path(sys.argv[1]).read_text())
sys.path.insert(0, args['project'])
from harness.L1.common import refinement, runner
from src.generator.client import GeneratorConfig

os.environ['FAKE_CODEX_MODE'] = args['mode']
runner.GeneratorConfig.from_env = lambda *_: GeneratorConfig(
    api_key='fixture-only', base_url='https://example.invalid/v1', model='process-fixture-no-model',
    max_attempts=1, codex_binary=args['binary'],
)
try:
    result = refinement.run_agent_pipeline(args['task_id'], Path(args['tasks']), Path(args['config']),
                                           Path(args['output']), trial_id='failure-boundary', max_rounds=1,
                                           blender=Path(args['blender']), timeout=30)
except KeyboardInterrupt:
    Path(args['interrupted']).write_text(json.dumps({'caught': 'KeyboardInterrupt'}))
    raise SystemExit(130) from None
Path(args['result']).write_text(json.dumps(result, indent=2))
raise SystemExit(0 if result['final_status'] == 'passed' else 1)
