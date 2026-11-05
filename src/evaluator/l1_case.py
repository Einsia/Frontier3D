"""Artifact-only entry point shared by independently specified L1 cases.

Execution records may enter through the trusted orchestrator Python API only.
The CLI deliberately does not accept candidate-authored execution JSON.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import tomllib

from .l1_runner import evaluate_l1_submission
from .spec import EvalSpec


def load_case(task_root: Path):
    manifest = tomllib.loads((task_root / 'task.toml').read_text())
    spec = EvalSpec.load(task_root / 'harness/eval_spec.json')
    required = [str(Path(name).relative_to('output')) for name in manifest['submission_files']]
    if spec.profile != 'L1' or set(spec.required_artifacts) != set(required):
        raise ValueError('Case EvalSpec and manifest deliverables disagree')
    needs_design = any(c.metric == 'procedural_materials' for group in spec.checks.values() for c in group)
    if needs_design or (task_root / 'harness/evaluation_design.json').exists():
        from .l1_case_design import load_design
        design = load_design(task_root)
        if design['task_id'] != manifest['id'] or design['category'] != manifest['category']:
            raise ValueError('L1 case design identity mismatch')
    return manifest, spec


def evaluate_case(task_root, submission, blender, *, harness_record=None, deadline=None, timeout=900):
    task_root = Path(task_root).resolve()
    manifest, spec = load_case(task_root)
    return evaluate_l1_submission(spec, Path(submission), Path(blender), assets_root=task_root,
                                  task_id=manifest['id'], task_type=manifest['category'],
                                  harness_record=harness_record, deadline=deadline, timeout=timeout)


def main(task_root):
    parser = argparse.ArgumentParser(description='Inspect a case submission; execution requires external orchestrator')
    parser.add_argument('--submission', type=Path, required=True)
    parser.add_argument('--blender', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=900)
    args = parser.parse_args()
    report = evaluate_case(task_root, args.submission, args.blender, timeout=args.timeout)
    print(json.dumps({key: report.get(key) for key in ('task_id', 'case_pass', 'S_core', 'S_diagnostic', 'report_path')}))
    return 2 if report.get('scoring_failed') or report.get('budget_exhausted') else 0
