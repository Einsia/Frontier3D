"""Independent auxiliary scores and trial/type macro aggregation."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean, median
from typing import Any

from .spec import IMPORTANCE, finite_number


def vlm_score(
    ratings: dict[str, list[int]], importance: dict[str, str] | None = None
) -> float:
    """Frozen criteria and repeated 0..4 ratings; median before aggregation."""
    if not ratings:
        raise ValueError("VLM ratings must declare at least one criterion")
    importance = importance or dict.fromkeys(ratings, "normal")
    if set(importance) != set(ratings) or any(
        v not in IMPORTANCE for v in importance.values()
    ):
        raise ValueError("VLM importance must match the frozen criterion set")
    weighted = []
    for criterion, values in ratings.items():
        if not values or any(type(v) is not int or not 0 <= v <= 4 for v in values):
            raise ValueError(
                "Each VLM criterion needs repeated integer ratings in [0, 4]"
            )
        weight = IMPORTANCE[importance[criterion]]
        weighted.append((median(values) / 4, weight))
    return sum(score * weight for score, weight in weighted) / sum(
        w for _, w in weighted
    )


def human_score(wins: int, ties: int, losses: int) -> float | None:
    if any(type(v) is not int or v < 0 for v in (wins, ties, losses)):
        raise ValueError("Human counts must be nonnegative integers")
    total = wins + ties + losses
    return (wins + 0.5 * ties) / total if total else None


def efficiency_metrics(
    *,
    initial_score: float,
    final_score: float,
    model_calls: int,
    total_tokens: int,
    total_seconds: float,
) -> dict[str, Any]:
    for name, value in (("initial_score", initial_score), ("final_score", final_score)):
        if not 0 <= finite_number(value, name) <= 1:
            raise ValueError(f"{name} must be in [0, 1]")
    if any(type(v) is not int or v < 0 for v in (model_calls, total_tokens)):
        raise ValueError("Calls and tokens must be nonnegative integers")
    if finite_number(total_seconds, "total_seconds") < 0:
        raise ValueError("total_seconds must be nonnegative")
    gain = final_score - initial_score
    return {
        "model_calls": model_calls,
        "total_tokens": total_tokens,
        "total_seconds": total_seconds,
        "gain_per_call": gain / model_calls if model_calls else None,
        "gain_per_1k_tok": 1000 * gain / total_tokens if total_tokens else None,
        "gain_per_min": 60 * gain / total_seconds if total_seconds else None,
    }


def summarize_l1(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """One protocol-selected final report per trial; never select the best round.

    The caller must include all scheduled trials, including execution failures.
    ``success_rate`` and ``quality_on_success`` use that full trial population.
    Different evaluation versions and single-shot/refinement boards cannot mix.
    """
    from .l1_finalization import is_finalized

    if not reports:
        raise ValueError("Cannot summarize an empty evaluation")
    cases: dict[tuple[str, str], list[float]] = defaultdict(list)
    seen = set()
    versions, boards = set(), set()
    policies, run_kinds = set(), set()
    successes = []
    task_types: dict[str, str] = {}
    task_specs: dict[str, str] = {}
    for report in reports:
        if report.get("profile") != "L1":
            raise ValueError("Only L1 reports may enter this summary")
        if not is_finalized(report) and not (
            report.get("scoring_failed") is True and report.get("case_pass") is False
            and report.get("S_core") == 0 and report.get("G") == 0
            and (report.get("finalization") or {}).get("status") in {"failed", "interrupted", "invalidated"}
        ):
            raise ValueError("L1 report has no accepted finalization receipt")
        versions.add(report["evaluator_version"])
        policies.add(report.get("score_policy", "legacy"))
        run_kinds.add(report.get("evaluation_kind", "legacy_unspecified"))
        board = report.get("board", "single-shot")
        if board not in {"single-shot", "auto-refinement"}:
            raise ValueError("Unknown leaderboard protocol")
        boards.add(board)
        task, kind, trial = report["task_id"], report["task_type"], report["trial_id"]
        key = (task, trial)
        if key in seen:
            raise ValueError(
                "Duplicate trial (round selection must precede aggregation)"
            )
        seen.add(key)
        if task in task_types and task_types[task] != kind:
            raise ValueError("A task cannot belong to multiple task types")
        task_types[task] = kind
        spec_hash = report["spec_sha256"]
        if task in task_specs and task_specs[task] != spec_hash:
            raise ValueError("All trials of a task must use the same frozen EvalSpec")
        task_specs[task] = spec_hash
        score = finite_number(report["S_core"], "S_core")
        if not 0 <= score <= 1 or type(report["case_pass"]) is not bool:
            raise ValueError("Invalid trial score or gate")
        if not report["case_pass"] and score != 0:
            raise ValueError("A failed gate must have zero core score")
        cases[(kind, task)].append(score)
        if report["case_pass"]:
            successes.append(score)
    if len(versions) != 1 or len(boards) != 1:
        raise ValueError("Cannot mix evaluator versions or leaderboard protocols")
    if len(policies) != 1 or len(run_kinds) != 1:
        raise ValueError("Cannot mix score policies, offline rescores and different experiment kinds")
    types: dict[str, list[float]] = defaultdict(list)
    task_scores = {}
    for (kind, task), scores in cases.items():
        task_scores[task] = median(scores)
        types[kind].append(task_scores[task])
    type_scores = {kind: mean(scores) for kind, scores in types.items()}
    return {
        "profile": "L1",
        "evaluator_version": next(iter(versions)),
        "board": next(iter(boards)),
        "score_policy": next(iter(policies)),
        "evaluation_kind": next(iter(run_kinds)),
        "task_scores": task_scores,
        "type_scores": type_scores,
        "S_level": mean(type_scores.values()),
        "trial_count": len(reports),
        "success_rate": len(successes) / len(reports),
        "quality_on_success": mean(successes) if successes else None,
    }


def summarize_l2(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the same frozen trial/type macro protocol to L2 reports."""
    if not reports:
        raise ValueError("Cannot summarize an empty evaluation")
    if any(report.get("profile") != "L2" for report in reports):
        raise ValueError("Only L2 reports may enter this summary")
    # Keep the implementation deliberately parallel to summarize_l1 while
    # preserving the profile-specific public entry point for audit tooling.
    identities = {(r.get('evaluation_kind', 'legacy'), r.get('harness_version'), r.get('generation_protocol'),
                   r.get('model'), r.get('reasoning_effort')) for r in reports}
    if len(identities) != 1 or any(r.get('evaluation_kind') in {'offline-rescore', 'unverified'} for r in reports):
        raise ValueError('Cannot mix L2 experiment kinds, Harness protocols, models or offline results')
    cases: dict[tuple[str, str], list[float]] = defaultdict(list)
    seen = set()
    versions, boards = set(), set()
    successes = []
    task_types: dict[str, str] = {}
    task_specs: dict[str, str] = {}
    task_requirements = {}
    for report in reports:
        versions.add(report["evaluator_version"])
        board = report.get("board", "single-shot")
        if board not in {"single-shot", "auto-refinement"}:
            raise ValueError("Unknown leaderboard protocol")
        boards.add(board)
        task, kind, trial = report["task_id"], report["task_type"], report["trial_id"]
        key = (task, trial)
        if key in seen:
            raise ValueError(
                "Duplicate trial (round selection must precede aggregation)"
            )
        seen.add(key)
        if task in task_types and task_types[task] != kind:
            raise ValueError("A task cannot belong to multiple task types")
        task_types[task] = kind
        if task in task_specs and task_specs[task] != report["spec_sha256"]:
            raise ValueError("All trials of a task must use the same frozen EvalSpec")
        task_specs[task] = report["spec_sha256"]
        requirements = report.get('requirements_coverage', {}).get('requirements_sha256')
        if task in task_requirements and task_requirements[task] != requirements:
            raise ValueError('Cannot mix L2 requirement/calibration revisions')
        task_requirements[task] = requirements
        score = finite_number(report["S_core"], "S_core")
        if not 0 <= score <= 1 or type(report["case_pass"]) is not bool:
            raise ValueError("Invalid trial score or gate")
        if not report["case_pass"] and score != 0:
            raise ValueError("A failed gate must have zero core score")
        cases[(kind, task)].append(score)
        if report["case_pass"]:
            successes.append(score)
    if len(versions) != 1 or len(boards) != 1:
        raise ValueError("Cannot mix evaluator versions or leaderboard protocols")
    task_scores = {task: median(scores) for (_, task), scores in cases.items()}
    type_scores: dict[str, list[float]] = defaultdict(list)
    for kind, task in cases:
        type_scores[kind].append(task_scores[task])
    type_means = {kind: mean(scores) for kind, scores in type_scores.items()}
    return {
        "profile": "L2",
        "evaluation_kind": reports[0].get("evaluation_kind", "legacy"),
        "model": reports[0].get("model"),
        "harness_version": reports[0].get("harness_version"),
        "evaluator_version": next(iter(versions)),
        "board": next(iter(boards)),
        "task_scores": task_scores,
        "type_scores": type_means,
        "S_level": mean(type_means.values()),
        "trial_count": len(reports),
        "success_rate": len(successes) / len(reports),
        "quality_on_success": mean(successes) if successes else None,
    }
