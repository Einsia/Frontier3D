"""This case owns its specification; process lifecycle lives in orchestrator."""
from pathlib import Path
import sys

TASK_ROOT = Path(__file__).resolve().parents[1]
for parent in TASK_ROOT.parents:
    if (parent / 'src/evaluator/l1_case.py').is_file():
        sys.path.insert(0, str(parent))
        break

from src.evaluator.l1_case import evaluate_case, main


def evaluate(submission, blender, **kwargs):
    return evaluate_case(TASK_ROOT, submission, blender, **kwargs)


if __name__ == '__main__':
    raise SystemExit(main(TASK_ROOT))
