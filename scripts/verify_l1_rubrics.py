"""Check released L1 rubrics, or explicitly repair recorded instruction digests.

The repair accepts only the historical-to-release instruction binding recorded
in l1-rubric-bindings.json. It never regenerates checklist text or accepts a
changed rubric by hashing it again. Ordinary verification is read-only.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmark.l1_contracts import verify_l1_rubrics
from orchestrator.tasks import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rebind-instruction-digests', action='store_true',
                        help='Apply only the documented instruction-binding repair')
    args = parser.parse_args()
    updates = verify_l1_rubrics(ROOT, allow_stale_instruction_digest=args.rebind_instruction_digests)
    for path, plan in updates:
        write_json(path, plan)
    verify_l1_rubrics(ROOT)
    print(json.dumps({'native_l1_tasks': 45, 'updated_alignment_files': len(updates),
                      'model_calls': 0, 'status': 'passed'}))


if __name__ == '__main__':
    main()
