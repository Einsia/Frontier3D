"""Fixed Level 2 scoring formula for large Blender scenes."""

from __future__ import annotations

import math
from typing import Any

from .l1 import _aggregate
from .metrics import evaluate_metric, validate_metrics
from .spec import EDIT_THRESHOLD, IMPORTANCE, L2_EVALUATOR_VERSION, L2_WEIGHTS, EvalSpec


def score_l2(spec: EvalSpec, evidence: dict[str, Any], excluded_metrics=()) -> dict[str, Any]:
    """Score trusted, evaluator-owned L2 evidence.

    ``S_vlm`` and ``S_human`` remain auxiliary fields. The six L2 module weights
    are frozen in :mod:`src.evaluator.spec` and cannot be supplied by a task.
    """
    if spec.profile != "L2":
        raise ValueError("score_l2 requires an L2 EvalSpec")
    validate_metrics(spec)
    modules: dict[str, Any] = {}
    by_id: dict[str, Any] = {}
    edited: dict[str, tuple[float, float]] = {}
    for module, checks in spec.checks.items():
        results = []
        for check in checks:
            result = {
                "id": check.id,
                "metric": check.metric,
                "group": check.group,
                "importance": check.importance,
                "role": check.role,
                "params": check.params,
                "pass_threshold": check.pass_threshold,
                **({'value': None, 'score': 0., 'passed': False, 'status': 'not_in_scope',
                    'details': {'reason': 'Excluded by the active versioned scoring profile'}}
                   if check.metric in excluded_metrics else evaluate_metric(check, evidence, spec).to_dict()),
            }
            results.append(result)
            by_id[check.id] = result
        target_checks = [r for r in results if r["role"] == "target"]
        if target_checks:
            target, target_groups = _aggregate(target_checks)
            preserve, preserve_groups = _aggregate(
                [r for r in results if r["role"] == "preserve"]
            )
            score = math.sqrt(target * preserve)
            edited[module] = target, preserve
            groups = {"target": target_groups, "preserve": preserve_groups}
            components = {"target": target, "preserve": preserve}
        else:
            score, groups = _aggregate(results)
            components = {}
        modules[module] = {
            "score": score,
            "weight": L2_WEIGHTS[module],
            "groups": groups,
            "checks": results,
            **components,
        }

    harness = evidence.get("harness", {})
    artifacts = evidence.get("artifacts", {})
    gates: dict[str, Any] = {
        "all_seeds": {
            "passed": all(all(harness.get("seed_runs", {}).get(str(seed), {}).get(field) is True
                              for field in ("execution_passed", "integrity_passed")) for seed in spec.seeds),
            "required": list(spec.seeds),
        },
        "all_seed_quality": {
            "passed": all(harness.get('seed_runs', {}).get(str(seed), {}).get('quality_passed') is True for seed in spec.seeds),
            "required": list(spec.seeds),
        },
        "execution": {
            "passed": harness.get("execution_passed") is True,
            "reason": "Requires a trusted execution record bound to this submission",
        },
        "artifacts": {
            "passed": all(
                artifacts.get(name, {}).get("loadable") is True
                for name in spec.required_artifacts
            ),
            "required": list(spec.required_artifacts),
            "failed": [
                name
                for name in spec.required_artifacts
                if artifacts.get(name, {}).get("loadable") is not True
            ],
        },
        "real_geometry": {
            "passed": evidence.get("scene", {}).get("has_real_geometry") is True
        },
        "integrity": {
            "passed": harness.get("integrity_passed") is True,
            "reason": "Requires a trusted scene integrity and anti-cheating audit",
        },
        "critical_constraints": {
            "passed": all(by_id[name]["passed"] for name in spec.critical_constraints),
            "failed": [
                name for name in spec.critical_constraints if not by_id[name]["passed"]
            ],
        },
    }
    if edited:
        total_weight = sum(L2_WEIGHTS[module] for module in edited)
        target = (
            sum(L2_WEIGHTS[m] * values[0] for m, values in edited.items())
            / total_weight
        )
        preserve = (
            sum(L2_WEIGHTS[m] * values[1] for m, values in edited.items())
            / total_weight
        )
        gates["edit_preservation"] = {
            "passed": target >= EDIT_THRESHOLD and preserve >= EDIT_THRESHOLD,
            "target": target,
            "preserve": preserve,
            "threshold": EDIT_THRESHOLD,
        }
    gate = all(item["passed"] for item in gates.values())
    quality_gates = {name: result for name, result in gates.items()
                     if name not in {'execution', 'integrity', 'all_seeds', 'all_seed_quality'}}
    level_score = sum(
        L2_WEIGHTS[name] * module["score"] for name, module in modules.items()
    )
    level_score = min(1.0, max(0.0, level_score))
    return {
        "schema_version": 2,
        "evaluator_version": L2_EVALUATOR_VERSION,
        "profile": "L2",
        "mode": spec.mode,
        "spec_sha256": spec.digest,
        "status": "passed" if gate else "failed",
        "G": int(gate),
        "case_pass": gate,
        "task_quality_pass": all(g['passed'] for g in quality_gates.values()),
        "S_core": level_score if gate else 0.0,
        "S_level": level_score,
        "S_vlm": None,
        "S_human": None,
        "efficiency": {},
        "gates": gates,
        "modules": modules,
        "protocol": {
            "weights": dict(L2_WEIGHTS),
            "importance": dict(IMPORTANCE),
            "edit_threshold": EDIT_THRESHOLD,
            "seeds": list(spec.seeds),
            "render_views": list(spec.render_views),
        },
        "limitations": [
            "Content and spatial assertions are only those declared by the frozen EvalSpec.",
            "VLM and human judgments are reported separately from S_core.",
        ],
    }


def evaluate_l2_submission(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .l2_runner import evaluate_l2_submission as run

    return run(*args, **kwargs)
