"""Evaluator-owned failure attribution and evidence dependencies, only for L1.

Availability is independent of whether a measurable candidate satisfies a
constraint. A missing tool/reference must never become a CAD defect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .spec import CheckSpec, EvalSpec

FAILURE_STATUSES = {"not_measurable", "not_implemented", "infrastructure_error"}
_PRIORITY = {"not_measurable": 1, "not_implemented": 2, "infrastructure_error": 3}


class InspectionFailure(RuntimeError):
    def __init__(self, status: str, code: str, reason: str):
        if status not in FAILURE_STATUSES:
            raise ValueError("Invalid inspection failure status")
        self.status, self.code, self.reason = status, code, reason
        super().__init__(f"{code}: {reason}")


def pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def dependencies(check: CheckSpec) -> set[str]:
    """Evidence reads for current L1 metrics; no speculative whole-scene blame."""
    params = check.params
    paths = {
        params[key]
        for key in ("path", "reference_path", "candidate", "reference")
        if key in params
        and isinstance(params[key], str)
        and params[key].startswith("/")
    }
    paths.update(params.get("paths", []))
    if check.metric in {'machined_sleeve', 'washer_edit', 'slot_plate_edit'}:
        paths.add(params['scene'])
        if check.metric in {'washer_edit', 'slot_plate_edit'}:
            paths.add(params['baseline'])
    if check.metric in {'native_image_pair', 'main_render_consistency'}:
        view = pointer_token(params['view'])
        paths.add(f'/views/{view}')
        if check.metric == 'native_image_pair':
            paths.update({f'/reference_images/{view}', f'/image_reference_masks/{view}'})
        else:
            paths.add('/artifacts/' + pointer_token(params['artifact']))
    if check.metric in {"occupancy", "hole_profile", "hole_pattern"}:
        paths.add(f"/probes/{pointer_token(check.id)}")
    elif check.metric == "seed_success":
        paths.add("/harness/seed_runs")
    elif check.metric == 'all_seed_checks':
        paths.update({'/harness/seed_quality', '/harness/seed_runs'})
    elif check.metric in {"mask_iou", "render_validity", "render_similarity"}:
        view = pointer_token(params["view"])
        if check.metric == "render_similarity":
            paths.update({f"/views/{view}/image", f"/reference_images/{view}/path"})
        else:
            paths.add(f"/views/{view}/mask")
            if check.metric == "mask_iou":
                paths.add(f"/reference_views/{view}/mask")
    elif check.metric in {
        "object_coverage",
        "semantic_inventory",
        "part_geometry",
        "relation",
        "coaxial",
        "ground_contact",
        "collision_free",
        "billboard_free",
    }:
        paths.add("/scene")
    return paths


def overlaps(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def record_failure(
    spec: EvalSpec,
    evidence: dict[str, Any],
    scopes: list[str],
    failure: InspectionFailure,
) -> None:
    item = {
        "status": failure.status,
        "code": failure.code,
        "reason": failure.reason,
        "scopes": scopes,
    }
    for key in ("inspector_execution", "inspector_persistence"):
        receipt = getattr(failure, key, None)
        if isinstance(receipt, dict):
            item[key] = receipt
    evidence.setdefault("inspection_failures", []).append(item)
    if failure.status == "infrastructure_error":
        evidence.setdefault("infrastructure_errors", []).append(item)
    failures = evidence.setdefault("measurement_failures", {})
    for checks in spec.checks.values():
        for check in checks:
            if check.applicable and any(
                overlaps(p, s) for p in dependencies(check) for s in scopes
            ):
                old = failures.get(check.id)
                if old is None or _PRIORITY[failure.status] > _PRIORITY[old["status"]]:
                    failures[check.id] = item


def scoped_failure(evidence: dict[str, Any], scope: str) -> dict[str, Any] | None:
    found = [
        f
        for f in evidence.get("inspection_failures", [])
        if any(overlaps(scope, s) for s in f["scopes"])
    ]
    return max(found, key=lambda f: _PRIORITY[f["status"]]) if found else None


def combine_outcomes(statuses: list[str]) -> str:
    """An observed failure is retained even when a different item is unmeasured."""
    for status in (
        "infrastructure_error",
        "failed",
        "not_implemented",
        "not_measurable",
    ):
        if status in statuses:
            return status
    return (
        "passed"
        if statuses and all(s == "passed" for s in statuses)
        else "not_measurable"
    )
