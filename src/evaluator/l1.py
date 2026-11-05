"""Fixed L1 scoring formula and hard gates from dev_docs/scoring_rules.md."""

from __future__ import annotations

import copy
import math
from collections import defaultdict
from statistics import mean
from typing import Any

from .l1_failures import (
    InspectionFailure,
    combine_outcomes,
    pointer_token,
    scoped_failure,
)
from .l1_requirements import check_outcome, requirement_coverage
from .metrics import evaluate_metric, validate_metrics
from .spec import EDIT_THRESHOLD, EVALUATOR_VERSION, IMPORTANCE, L1_WEIGHTS, EvalSpec


def _aggregate(checks: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for check in checks:
        if check["status"] != "not_applicable" and check.get("score_contribution", True):
            groups[check["group"]].append(check)
    details = {
        name: {
            "score": mean(c["score"] for c in members),
            "weight": IMPORTANCE[members[0]["importance"]],
            "check_ids": [c["id"] for c in members],
        }
        for name, members in groups.items()
    }
    total = sum(group["weight"] for group in details.values())
    score = (
        sum(group["score"] * group["weight"] for group in details.values()) / total
        if total
        else 0.0
    )
    return score, details


def score_l1(
    spec: EvalSpec, evidence: dict[str, Any], *, _failure: InspectionFailure | None = None,
) -> dict[str, Any]:
    """Score trusted evaluator evidence. Missing evidence never changes weights.

    This is an offline scoring API, not an authenticity check for arbitrary JSON.
    Use ``evaluate_l1_submission`` to collect geometry and bind harness records to
    the submitted artifact hashes. Model-authored JSON must never enter this API.
    """
    if spec.profile != "L1":
        raise ValueError("score_l1 requires an L1 EvalSpec")
    validate_metrics(spec)
    requirements_protocol = spec.to_dict().get("l1_protocol")
    modules: dict[str, Any] = {}
    by_id: dict[str, Any] = {}
    edited: dict[str, tuple[float, float]] = {}
    for module, checks in spec.checks.items():
        results = []
        for check in checks:
            from .l1_image_quality import visual_only, selected_ids
            skip_visual_diagnostic = (visual_only(spec.to_dict())
                and check.id not in selected_ids(spec.to_dict()['l1_image_quality'])
                and check.metric != 'all_seed_checks')
            result = {
                "id": check.id,
                "metric": check.metric,
                "group": check.group,
                "importance": check.importance,
                "role": check.role,
                "params": check.params,
                "pass_threshold": check.pass_threshold,
                # No-bitmap compliance is a gate, not extra appearance quality.
                # Keep its measurement/coverage, but do not dilute image scores.
                **({"score_contribution": False} if check.metric in {
                    'procedural_materials', 'procedural_material_sequence', 'native_image_pair',
                    'main_render_consistency', 'all_seed_checks',
                } else {}),
                **({'score': 0., 'passed': False, 'status': 'not_measurable',
                    'details': {'reason': 'Outside visual v2 scope; not collected', 'not_collected': True}}
                    if skip_visual_diagnostic and _failure is None else
                    evaluate_metric(check, evidence, spec).to_dict() if _failure is None else {
                    "score": 0.0, "passed": False,
                    "status": _failure.status if check.applicable else "not_applicable",
                    "details": {"code": _failure.code, "reason": _failure.reason},
                }),
            }
            results.append(result)
            result["measurement_status"] = check_outcome(result, evidence)
            failure = evidence.get("measurement_failures", {}).get(check.id)
            if requirements_protocol is not None and failure and check.applicable:
                # A failed measurement must not retain a score from stale or
                # partial facts, even if those facts happen to look plausible.
                result.update(score=0.0, passed=False, status=failure["status"])
                result["details"]["measurement_failure"] = failure
            by_id[check.id] = result
        if any(c.role == "target" and c.applicable for c in checks):
            target, target_groups = _aggregate(
                [r for r in results if r["role"] == "target"]
            )
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
            "weight": L1_WEIGHTS[module],
            "groups": groups,
            "checks": results,
            **components,
        }

    harness = evidence.get("harness", {})
    artifacts = evidence.get("artifacts", {})
    gates: dict[str, Any] = {
        "execution": {
            "passed": harness.get("execution_passed") is True,
            "reason": "Requires a trusted execution record for this submission",
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
            "reason": "Requires trusted provenance/immutability checks; not a complete anti-cheating proof",
        },
        "critical_constraints": {
            "passed": all(by_id[name]["passed"] for name in spec.critical_constraints),
            "failed": [
                name for name in spec.critical_constraints if not by_id[name]["passed"]
            ],
        },
    }
    if edited:
        total_weight = sum(L1_WEIGHTS[module] for module in edited)
        target = (
            sum(L1_WEIGHTS[m] * scores[0] for m, scores in edited.items())
            / total_weight
        )
        preserve = (
            sum(L1_WEIGHTS[m] * scores[1] for m, scores in edited.items())
            / total_weight
        )
        gates["edit_preservation"] = {
            "passed": target >= EDIT_THRESHOLD and preserve >= EDIT_THRESHOLD,
            "target": target,
            "preserve": preserve,
            "threshold": EDIT_THRESHOLD,
        }
        if requirements_protocol is not None:
            edited_checks = [
                r for r in by_id.values() if r["role"] in {"target", "preserve"}
            ]
            gates["edit_preservation"] = {
                "passed": all(
                    r["measurement_status"] == "passed" for r in edited_checks
                ),
                "target": target,
                "preserve": preserve,
                "policy": "all_declared_edit_constraints_within_their_own_tolerances",
                "failed": [
                    r["id"]
                    for r in edited_checks
                    if r["measurement_status"] != "passed"
                ],
            }
    gate = all(item["passed"] for item in gates.values())
    level_score = sum(
        L1_WEIGHTS[name] * module["score"] for name, module in modules.items()
    )
    level_score = min(1.0, max(0.0, level_score))
    image_quality = [r for r in by_id.values() if r['metric'] == 'native_image_pair'
                     and r['status'] != 'not_applicable']
    quality_policy = None
    if image_quality:
        reference_score = mean(r['score'] for r in image_quality)
        seed_quality = next((r for r in by_id.values() if r['metric'] == 'all_seed_checks'
                             and r['status'] != 'not_applicable'), None)
        baseline_reference_score = reference_score
        if seed_quality is not None:
            seed_score = seed_quality['details'].get('minimum_image_score')
            reference_score = min(reference_score, seed_score) if seed_score is not None else 0.
        quality_policy = {
            'version': 'l1-native-image-main-v2' if seed_quality is not None else 'l1-native-image-main-v1',
            'base_checks_score': level_score,
            'reference_image_score': reference_score,
            'formula': 'base_checks_score * min(baseline_image, all_seed_images)' if seed_quality is not None
                       else 'base_checks_score * reference_image_score',
            'baseline_reference_image_score': baseline_reference_score,
            'check_ids': [r['id'] for r in image_quality],
            'formal_score_eligible': False, 'calibration_status': 'pilot_not_calibrated',
        }
        level_score *= reference_score
    coverage = requirement_coverage(requirements_protocol, by_id, evidence)
    diagnostic_gate = gate
    if requirements_protocol is not None:
        infrastructure_ok = not evidence.get("infrastructure_errors") and not any(
            r["measurement_status"] == "infrastructure_error" for r in by_id.values()
        )
        gates["infrastructure"] = {
            "passed": infrastructure_ok,
            "measurement_status": "passed"
            if infrastructure_ok
            else "infrastructure_error",
            "reason": "Tool/reference failures invalidate this measurement run, not the candidate design",
        }
        for name, field in (
            ("execution", "execution_passed"),
            ("integrity", "integrity_passed"),
        ):
            failure = scoped_failure(evidence, f"/harness/{field}")
            gates[name]["measurement_status"] = (
                failure["status"]
                if failure
                else (
                    "passed"
                    if harness.get(field) is True
                    else "failed"
                    if harness.get(field) is False
                    else "not_measurable"
                )
            )
        artifact_outcomes = []
        for name in spec.required_artifacts:
            failure = scoped_failure(evidence, f"/artifacts/{pointer_token(name)}")
            artifact_outcomes.append(
                failure["status"]
                if failure
                else "passed"
                if artifacts.get(name, {}).get("loadable") is True
                else "failed"
            )
        gates["artifacts"]["measurement_status"] = combine_outcomes(artifact_outcomes)
        gates["artifacts"]["failed"] = [
            name
            for name, outcome in zip(
                spec.required_artifacts, artifact_outcomes, strict=True
            )
            if outcome == "failed"
        ]
        gates["artifacts"]["unverified"] = [
            name
            for name, outcome in zip(
                spec.required_artifacts, artifact_outcomes, strict=True
            )
            if outcome not in {"passed", "failed"}
        ]
        failure = scoped_failure(evidence, "/scene")
        gates["real_geometry"]["measurement_status"] = (
            failure["status"]
            if failure
            else (
                "passed"
                if gates["real_geometry"]["passed"]
                else "failed"
                if "scene" in evidence
                else "not_measurable"
            )
        )
        gates["critical_constraints"]["measurement_status"] = (
            combine_outcomes(
                [by_id[n]["measurement_status"] for n in spec.critical_constraints]
            )
            if spec.critical_constraints
            else "passed"
        )
        if "edit_preservation" in gates:
            gates["edit_preservation"]["measurement_status"] = combine_outcomes(
                [
                    r["measurement_status"]
                    for r in by_id.values()
                    if r["role"] in {"target", "preserve"}
                ]
            )
        gate_checks = {"critical_constraints": list(spec.critical_constraints)}
        if "edit_preservation" in gates:
            gate_checks["edit_preservation"] = [
                r["id"] for r in by_id.values() if r["role"] in {"target", "preserve"}
            ]
        for name, ids in gate_checks.items():
            gates[name]["failed"] = [
                n for n in ids if by_id[n]["measurement_status"] == "failed"
            ]
            gates[name]["unverified"] = [
                n
                for n in ids
                if by_id[n]["measurement_status"] not in {"passed", "failed"}
            ]
        for item in gates.values():
            item["passed"] = item["measurement_status"] == "passed"
        diagnostic_gate = all(item["passed"] for item in gates.values())
        required = [r for r in coverage["requirements"] if r["required"]]
        requirements_pass = bool(required) and all(
            r["status"] == "passed" for r in required
        )
        gates["requirements"] = {
            "passed": requirements_pass,
            "failed": [r["id"] for r in required if r["status"] == "failed"],
            "unverified": [
                r["id"] for r in required if r["status"] not in {"passed", "failed"}
            ],
        }
        gate = diagnostic_gate and requirements_pass
        if not infrastructure_ok:
            status = "infrastructure_error"
        elif any(r["status"] == "failed" for r in required) or any(
            item.get("measurement_status") == "failed" for item in gates.values()
        ):
            status = "failed"
        else:
            status = "passed" if gate else "incomplete"
    else:
        status = "passed" if gate else "failed"
    report = {
        "schema_version": 2,
        "evaluator_version": EVALUATOR_VERSION,
        "profile": "L1",
        "mode": spec.mode,
        "spec_sha256": spec.digest,
        "evaluation_kind": "offline_rescore",
        "score_policy": (
            "l1-requirements-v1"
            + (
                "+geometry:" + spec.to_dict()["l1_geometry"]["version"]
                if "l1_geometry" in spec.to_dict()
                else ""
            )
            if requirements_protocol
            else "legacy"
        ),
        "status": status,
        "G": int(gate),
        "case_pass": gate,
        "S_core": level_score if gate else 0.0,
        "S_level": level_score,
        "S_diagnostic": level_score if diagnostic_gate else 0.0,
        **({'protected_area_diagnostics': copy.deepcopy(evidence['protected_area_diagnostics'])}
           if 'protected_area_diagnostics' in evidence else {}),
        **({'image_quality_policy': quality_policy, 'formal_score_eligible': False} if quality_policy else {}),
        **({'numeric_quality_policy': {'version': 'l1-washer-edit-v1', 'scope': 'baseline_native_and_glb',
                                      'calibration_status': 'pilot_not_calibrated'},
            'formal_score_eligible': False} if any(c.metric == 'washer_edit' for cs in spec.checks.values() for c in cs) else {}),
        **({'numeric_quality_policy': {'version': 'l1-swept-bar-measurement-v1',
                                      'scope': 'native_and_glb_surface_and_finite_sections',
                                      'calibration_status': 'pilot_not_calibrated'},
            'formal_score_eligible': False} if any(c.metric == 'swept_bar' for cs in spec.checks.values() for c in cs) else {}),
        "score_interpretation": "Uncalibrated diagnostic weights; not a task completion percentage.",
        "declared_checks_pass": diagnostic_gate,
        "coverage": coverage,
        "task_completion": "complete"
        if coverage["core_complete"] and gate
        else "incomplete",
        "S_vlm": None,
        "S_human": None,
        "efficiency": {},
        "gates": gates,
        "modules": modules,
        "protocol": {
            "geometry": spec.to_dict().get("l1_geometry"),
            "requirements_version": requirements_protocol["version"]
            if requirements_protocol
            else None,
            "weights": dict(L1_WEIGHTS),
            "importance": dict(IMPORTANCE),
            "edit_threshold": None if requirements_protocol else EDIT_THRESHOLD,
            "edit_policy": "all_constraints_within_own_tolerances"
            if requirements_protocol
            else "legacy_0.8",
            "seeds": list(spec.seeds),
            "render_views": list(spec.render_views),
        },
        "limitations": [
            "Only declared checks are measured; undeclared CAD requirements are not inferred.",
            "VLM and human judgments are separate from the reproducible core score.",
            "The attached l1-geometry-v1 scene comparisons are supplemental diagnostics until task-specific thresholds and semantic bindings are calibrated.",
        ],
        "geometry_protocol": evidence.get(
            "geometry_protocol",
            {
                "protocol": "l1-geometry-v1",
                "status": "not_configured",
                "comparisons": {},
            },
        ),
    }
    if 'l1_edit_quality' in spec.to_dict():
        from .l1_edit_quality import apply
        report = apply(report, spec, evidence)
    if 'l1_image_quality' in spec.to_dict():
        from .l1_image_quality import apply
        report = apply(report, spec, evidence)
    return report


def failed_l1_report(spec: EvalSpec, failure: InspectionFailure) -> dict[str, Any]:
    """Build a bounded-by-spec failure report without inspecting candidate data.

    In particular this never calls a metric, opens an image or retries the
    interrupted calculation. All applicable requirements retain their slots.
    """
    detail = {"status": failure.status, "code": failure.code, "reason": failure.reason}
    report = score_l1(spec, {
        "infrastructure_errors": [detail],
        "measurement_failures": {
            check.id: detail for checks in spec.checks.values() for check in checks if check.applicable
        },
    }, _failure=failure)
    report.update(
        status="infrastructure_error", G=0, case_pass=False, S_core=0.0,
        declared_checks_pass=False, task_completion="incomplete", scoring_status="unavailable",
        score_interpretation="Scoring unavailable: zero core is an infrastructure gate, not measured model quality.",
    )
    report["gates"]["compute"] = {"passed": False, **detail}
    return report


def evaluate_l1_submission(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Inspect a Blender submission and save its evidence and L1 report."""
    from .l1_runner import evaluate_l1_submission as run

    return run(*args, **kwargs)
