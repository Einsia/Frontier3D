"""Trusted test driver; SIGINT the parent while its real baseline is running."""

import json
import sys
from pathlib import Path

args = json.loads(Path(sys.argv[1]).read_text())
sys.path.insert(0, args['project'])
from harness.L1.common.agent import run_refinement
from harness.L1.common.rerun import rerun_submission

try:
    def execute(source, _remaining=None):
        return rerun_submission(args['task_id'], Path(args['tasks']), Path(args['config']), source,
                                 Path(args['output']), trial_id='interrupted-round',
                                 repair_round=args.get('repair_round', 1),
                                 blender=Path(args['blender']), timeout=60, evaluate=False)

    if args.get('agent'):
        run_refinement(Path(args['agent']), Path(args['source']),
                       generate_round=lambda *_: {'status': 'success'}, execute_round=execute,
                       feedback_round=lambda *_: {'status': 'passed'})
    else:
        execute(Path(args['source']))
except KeyboardInterrupt:
    Path(args['interrupted']).write_text(json.dumps({'caught': 'KeyboardInterrupt', 'repair_round': args.get('repair_round', 1)}))
    raise SystemExit(130) from None
raise SystemExit('Expected test-only parent interruption')
