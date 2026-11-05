"""Bind evaluator-owned L1 method designs to their exact task sources."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def load_design(task_root):
    root = Path(task_root)
    plan = json.loads((root / "harness/evaluation_design.json").read_text())
    if plan.get("version") != "l1-evaluation-design-v1":
        raise ValueError("Unsupported L1 case design")
    sources = plan.get("sources", {})
    if set(sources) != {"instruction.md", "solution/EVALUATION.md", "harness/eval_spec.json"}:
        raise ValueError("L1 case design source set mismatch")
    for name, expected in sources.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"L1 case design source changed: {name}")
    lines = (root / "solution/EVALUATION.md").read_text().splitlines()
    rows = plan.get("evaluation_rows", [])
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("L1 case design needs unique source rows")
    expected_lines = []
    for number, text in enumerate(lines, 1):
        if not text.startswith('|'):
            continue
        cells = [v.strip() for v in text.strip().strip('|').split('|')]
        if cells[0] != '维度' and not all(re.fullmatch(r'[-: ]+', v) for v in cells):
            expected_lines.append(number)
    if [row.get('line') for row in rows] != expected_lines:
        raise ValueError('L1 case design must cover every EVALUATION row in order')
    for row in rows:
        line = row.get("line")
        if type(line) is not int or not 1 <= line <= len(lines) or lines[line-1] != row.get("source_quote"):
            raise ValueError("L1 case design source quote mismatch")
        if not row.get("methods") or not set(row["methods"]) <= plan.get("method_definitions", {}).keys():
            raise ValueError("L1 case design method missing")
    if 'measurement_contract' in plan or 'measurement_contract_sha256' in plan:
        from .l1_measurement_design import validate_contract
        validate_contract(plan, json.loads((root / 'harness/eval_spec.json').read_text()))
    return plan
