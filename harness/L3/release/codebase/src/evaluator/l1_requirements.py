"""L1-only instruction coverage; implementation presence is not measurement proof."""

# External protocol validation consistently uses ValueError, including bad types.
# ruff: noqa: TRY004

from __future__ import annotations

from collections import Counter
from typing import Any

PROTOCOL_VERSION = "l1-requirements-v1"
OUTCOMES = (
    "passed",
    "failed",
    "not_measurable",
    "not_implemented",
    "infrastructure_error",
    "not_applicable",
)

_GEOMETRY_COMPARISONS = {
    "native_reference",
    "native_baseline",
    "native_glb",
    "seed_reproduction",
}
_GEOMETRY_PREDICATES = {"geometry_match", "reproduction_match"}


def _validate_geometry_bindings(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate evaluator-owned geometry-to-requirement bindings.

    A binding is deliberately stricter than an arbitrary JSON pointer: it may
    refer only to a named comparison produced by the trusted
    ``l1-geometry-v1`` layer and to a predicate implemented by this evaluator.
    ``calibrated`` is maintainer-owned and must be explicit; a measured scene
    comparison never becomes a task gate merely because it exists.
    """
    bindings = item.get("geometry_bindings", [])
    if not isinstance(bindings, list):
        raise ValueError("geometry_bindings must be a list")
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {
            "comparison",
            "predicate",
            "calibrated",
            "required",
            "reason",
        }:
            raise ValueError("Invalid geometry binding fields")
        comparison = binding["comparison"]
        predicate = binding["predicate"]
        if comparison not in _GEOMETRY_COMPARISONS:
            raise ValueError("Unknown geometry comparison")
        if predicate not in _GEOMETRY_PREDICATES:
            raise ValueError("Unknown geometry predicate")
        key = f"{comparison}:{predicate}"
        if key in seen:
            raise ValueError("Duplicate geometry binding")
        seen.add(key)
        if type(binding["calibrated"]) is not bool:
            raise ValueError("Geometry binding calibrated must be boolean")
        if type(binding["required"]) is not bool:
            raise ValueError("Geometry binding required must be boolean")
        if not isinstance(binding["reason"], str) or (
            not binding["calibrated"] and not binding["reason"].strip()
        ):
            raise ValueError("Uncalibrated geometry bindings need a reason")
        validated.append(binding)
    return validated


def _supplemental_geometry_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Bind shared geometry evidence to a requirement without scoring it.

    The shared geometry worker compares complete scenes and is not, by itself,
    a semantic proof of a task-specific requirement (for example a hole,
    support relation or material role).  Keeping this binding in the coverage
    row makes that limitation explicit while preserving the evidence for later
    calibrated task adapters.  In particular, this function never changes a
    requirement status or its denominator.
    """
    report = evidence.get("geometry_protocol")
    if not isinstance(report, dict):
        return {
            "protocol": "l1-geometry-v1",
            "status": "not_configured",
            "role": "supplemental_diagnostic",
            "hard_gate": False,
            "contributes_to_requirement": False,
            "comparisons": [],
            "reason": "No evaluator-owned geometry protocol report was attached",
        }
    comparisons = report.get("comparisons", {})
    if not isinstance(comparisons, dict):
        comparisons = {}
    return {
        "protocol": report.get("protocol", "l1-geometry-v1"),
        "status": report.get("status", "not_measurable"),
        "role": "supplemental_diagnostic",
        "hard_gate": False,
        "contributes_to_requirement": False,
        "comparisons": sorted(str(name) for name in comparisons),
        "report_path": report.get("report_path"),
        "reason": (
            "Scene-level evidence is attached for audit; calibrated semantic "
            "mapping is still required before this can affect the requirement"
        ),
    }


def _requirement_geometry_evidence(
    requirement: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate the explicit geometry bindings for one requirement.

    The returned statuses are evidence-layer statuses, not a replacement for
    the requirement's declared implementation state.  A binding can therefore
    be measurable and passing while the parent requirement remains
    ``not_implemented`` until its semantic checks and calibrated policy are
    complete.
    """
    base = _supplemental_geometry_evidence(evidence)
    bindings = requirement.get("geometry_bindings", [])
    if not bindings:
        return {**base, "bindings": [], "binding_status": "not_configured"}
    report = evidence.get("geometry_protocol")
    comparisons = report.get("comparisons", {}) if isinstance(report, dict) else {}
    if not isinstance(comparisons, dict):
        comparisons = {}
    rows: list[dict[str, Any]] = []
    for binding in bindings:
        comparison = binding["comparison"]
        predicate = binding["predicate"]
        measured = comparisons.get(comparison)
        row: dict[str, Any] = {
            "comparison": comparison,
            "predicate": predicate,
            "calibrated": binding["calibrated"],
            "required": binding["required"],
        }
        if not isinstance(measured, dict):
            row.update(
                status="not_measurable",
                reason="The evaluator-owned comparison was not produced",
            )
        elif measured.get("status") in {"infrastructure_error", "not_measurable"}:
            row.update(
                status=measured["status"],
                reason=measured.get("reason") or measured.get("failure"),
            )
        elif measured.get("status") != "ok":
            row.update(
                status="failed",
                reason=measured.get("reason", "Geometry comparison failed"),
            )
        else:
            geometry = measured.get("evidence", measured)
            predicate_key = (
                "reproduction_match"
                if predicate == "reproduction_match"
                else "geometry_match"
            )
            predicate_passed = geometry.get(predicate_key) is True
            if not predicate_passed:
                row.update(
                    status="failed",
                    reason="The bound geometry predicate did not pass",
                )
            elif not binding["calibrated"]:
                row.update(
                    status="not_implemented",
                    reason=binding["reason"],
                )
            else:
                row.update(status="passed", reason=None)
        rows.append(row)
    required_rows = [row for row in rows if row["required"]]
    statuses = {row["status"] for row in required_rows}
    binding_status = next(
        (
            status
            for status in (
                "infrastructure_error",
                "not_measurable",
                "not_implemented",
                "failed",
            )
            if status in statuses
        ),
        "passed",
    )
    return {
        **base,
        "role": "formal_component",
        "bindings": rows,
        "binding_status": binding_status,
        "hard_gate": requirement["implementation"] == "complete"
        and binding_status in {"passed", "failed"},
        "contributes_to_requirement": requirement["implementation"] == "complete"
        and binding_status in {"passed", "failed"},
        "reason": (
            "Bindings are evaluator-owned, but they contribute only after the "
            "declared task calibration is frozen and the parent requirement is complete"
        ),
    }


def validate_protocol(raw: Any, checks: dict[str, Any]) -> None:
    """Validate maintainer-owned requirements before candidate code is executed."""
    if not isinstance(raw, dict) or set(raw) != {"version", "requirements"}:
        raise ValueError("l1_protocol requires version and requirements")
    if raw["version"] != PROTOCOL_VERSION:
        raise ValueError("Unsupported L1 requirements protocol version")
    entries = raw["requirements"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("L1 requirements must be a nonempty list")
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict) or set(item) not in ({
            "id",
            "text",
            "source",
            "required",
            "applicable",
            "implementation",
            "check_ids",
            "reason",
        }, {
            "id",
            "text",
            "source",
            "required",
            "applicable",
            "implementation",
            "check_ids",
            "reason",
            "geometry_bindings",
        }):
            raise ValueError("Invalid L1 requirement fields")
        for key in ("id", "text", "source"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"Requirement {key} must be nonempty")
        if item["id"] in seen:
            raise ValueError("Duplicate requirement id")
        seen.add(item["id"])
        if type(item["required"]) is not bool or type(item["applicable"]) is not bool:
            raise ValueError("Requirement required/applicable must be boolean")
        if item["required"] and not item["applicable"]:
            raise ValueError("An inapplicable requirement cannot be required")
        if item["implementation"] not in {"complete", "partial", "missing"}:
            raise ValueError("Unknown requirement implementation status")
        ids = item["check_ids"]
        if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids):
            raise ValueError("Requirement check_ids must be a string list")
        if len(ids) != len(set(ids)) or any(key not in checks for key in ids):
            raise ValueError("Requirement check_ids must be unique declared checks")
        if item["applicable"] and any(not checks[key].applicable for key in ids):
            raise ValueError("Applicable requirements cannot use inapplicable checks")
        if item["implementation"] in {"complete", "partial"} and not ids:
            raise ValueError("Complete/partial requirements need evidence checks")
        if item["implementation"] == "missing" and ids:
            raise ValueError("Missing requirements cannot claim implemented checks")
        if not isinstance(item["reason"], str):
            raise ValueError("Requirement reason must be a string")
        _validate_geometry_bindings(item)
        if (
            not item["applicable"] or item["implementation"] != "complete"
        ) and not item["reason"].strip():
            raise ValueError("Incomplete/inapplicable requirements need a reason")


def check_outcome(result: dict[str, Any], evidence: dict[str, Any]) -> str:
    """Convert measurements into outcomes without treating tool faults as CAD errors."""
    if result["status"] == "not_applicable":
        return "not_applicable"
    failure = evidence.get("measurement_failures", {}).get(result["id"])
    if failure:
        if failure.get("status") not in {
            "not_measurable",
            "not_implemented",
            "infrastructure_error",
        }:
            raise ValueError("Invalid evaluator-owned measurement failure status")
        return failure["status"]
    if result["status"] == "ok":
        # CodeEdit seed metrics now emit explicit availability. The same
        # outcome must reach both scoring gates and requirement coverage.
        if result.get('metric') in {'seed_success', 'all_seed_checks'}:
            status = result.get('details', {}).get('measurement_status')
            if status in {'passed','failed','not_measurable','not_implemented','infrastructure_error'}:
                return status
        return "passed" if result["passed"] else "failed"
    return "not_measurable"


def requirement_coverage(
    protocol: dict[str, Any] | None,
    checks: dict[str, dict[str, Any]],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Use an explicit denominator frozen in the EvalSpec, never a metric heuristic."""
    if protocol is None:
        return {
            "status": "undeclared",
            "requirements": [],
            "counts": {},
            "required_count": None,
            "required_passed": None,
            "required_satisfaction": None,
            "core_complete": False,
            "reason": "Legacy spec has no instruction-to-measurement mapping.",
        }
    entries = []
    for requirement in protocol["requirements"]:
        outcomes = {
            key: check_outcome(checks[key], evidence)
            for key in requirement["check_ids"]
        }
        geometry_evidence = _requirement_geometry_evidence(requirement, evidence)
        if requirement["implementation"] == "complete":
            for binding in geometry_evidence["bindings"]:
                if binding["required"]:
                    outcomes[
                        f"geometry:{binding['comparison']}:{binding['predicate']}"
                    ] = binding["status"]
        if not requirement["applicable"]:
            status = "not_applicable"
        elif requirement["implementation"] != "complete":
            # Partial evidence is retained, but cannot establish the whole
            # requirement (e.g. AABB dimensions are not a hole measurement).
            status = "not_implemented"
        else:
            statuses = set(outcomes.values())
            status = next(
                (
                    s
                    for s in (
                        "infrastructure_error",
                        "not_implemented",
                        "not_measurable",
                        "failed",
                    )
                    if s in statuses
                ),
                "passed",
            )
        entries.append(
            {
                **requirement,
                "status": status,
                "check_outcomes": outcomes,
                "geometry_evidence": geometry_evidence,
            }
        )
    required = [r for r in entries if r["required"]]
    counts = Counter(r["status"] for r in entries)
    applicable = [r for r in entries if r["applicable"]]
    measured = sum(r["status"] in {"passed", "failed"} for r in applicable)
    passed = sum(r["status"] == "passed" for r in required)
    complete = bool(required) and all(
        r["status"] in {"passed", "failed"} for r in required
    )
    return {
        "status": "complete"
        if applicable and measured == len(applicable)
        else "partial",
        "protocol_version": protocol["version"],
        "requirements": entries,
        "counts": {key: counts[key] for key in OUTCOMES},
        "requirement_count": len(entries),
        "applicable_count": len(applicable),
        "implemented_count": sum(r["implementation"] == "complete" for r in applicable),
        "measured_count": measured,
        "required_count": len(required),
        "required_passed": passed,
        "required_satisfaction": passed / len(required) if required else None,
        "core_complete": complete,
    }
