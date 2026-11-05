"""Strict issue protocol and deterministic, independently replayable scoring."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator

from . import PROTOCOL, L2_PROTOCOL

SEVERITY = {"minor": 0.02, "moderate": 0.08, "major": 0.20, "fatal": 1.0}
ISSUE_TYPES = {
    "content": [
        "missing_object",
        "extra_object",
        "wrong_part_identity",
        "missing_required_feature",
        "wrong_label_or_state",
    ],
    "spatial_layout": [
        "wrong_position",
        "wrong_orientation",
        "wrong_scale",
        "wrong_spacing",
        "wrong_grouping",
        "wrong_path_or_opening",
        "occlusion",
    ],
    "assembly_geometry": [
        "wrong_profile",
        "wrong_hole_or_opening",
        "wrong_thickness",
        "wrong_contact_gap",
        "misaligned_axis",
        "non_reversible_explosion",
    ],
    "appearance": [
        "material_mismatch",
        "color_mismatch",
        "lighting_mismatch",
        "style_incoherence",
        "insufficient_readability",
    ],
    "render_integrity": [
        "render_failure",
        "severe_artifact",
        "clipping",
        "empty_region",
        "inconsistent_views",
    ],
}


def read_json(path: Path):
    return json.loads(
        path.read_text(encoding="utf-8-sig"),
        parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f"Nonfinite {s}")),
    )


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def digest(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def contract_hash(text: str):
    return hashlib.sha256(text.replace("\r\n", "\n").strip().encode()).hexdigest()


def object_schema(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def array(items, **kwargs):
    return {"type": "array", "items": items, **kwargs}


def enum(values):
    return {"type": "string", "enum": list(values)}


TEXT = {"type": "string", "minLength": 1}
RATIO = {"type": "number", "minimum": 0, "maximum": 1}


def validate_spec(spec):
    from . import strict_continuous
    if spec.get('protocol') == strict_continuous.PROTOCOL:
        return strict_continuous.validate_spec(spec)
    from . import task_continuous
    if spec.get('protocol') == task_continuous.PROTOCOL:
        return task_continuous.validate_spec(spec)
    from . import image_continuous
    if spec.get('protocol') == image_continuous.PROTOCOL:
        return image_continuous.validate_spec(spec)
    from . import l2_rubric, l2_fidelity
    if spec.get('protocol') == l2_fidelity.PROTOCOL:
        return l2_fidelity.validate_spec(spec)
    if spec.get('protocol') == l2_rubric.PROTOCOL:
        return l2_rubric.validate_spec(spec)
    schema = object_schema(
        {
            "protocol": enum([PROTOCOL, L2_PROTOCOL]),
            "case_id": TEXT,
            "family": enum(["Text2Code", "Brief2Scene", "Reference2Scene", "Reference2Scene-RealPhoto", "SceneEdit"]),
            "instruction_sha256": TEXT,
            "reference_policy": TEXT,
            "focus": TEXT,
            "checks": array(
                object_schema(
                    {
                        "id": TEXT,
                        "question": TEXT,
                        "dimension": enum(ISSUE_TYPES),
                        "units": array(TEXT, minItems=1, uniqueItems=True),
                        "critical": {"type": "boolean"},
                    }
                ),
                minItems=1,
            ),
        }
    )
    Draft202012Validator(schema).validate(spec)
    ids = [c["id"] for c in spec["checks"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate checklist IDs")
    if spec['protocol'] == L2_PROTOCOL and any(c['critical'] and c['dimension'] != 'render_integrity' for c in spec['checks']):
        raise ValueError('L2 semantic differences cannot be fatal checks')
    return spec


def response_schema(spec, evidence_paths):
    from . import strict_continuous
    if spec.get('protocol') == strict_continuous.PROTOCOL:
        return strict_continuous.response_schema(spec, evidence_paths)
    from . import task_continuous
    if spec.get('protocol') == task_continuous.PROTOCOL:
        return task_continuous.response_schema(spec, evidence_paths)
    from . import image_continuous
    if spec.get('protocol') == image_continuous.PROTOCOL:
        return image_continuous.response_schema(spec, evidence_paths)
    from . import l2_rubric, l2_fidelity
    if spec.get('protocol') == l2_fidelity.PROTOCOL:
        return l2_fidelity.response_schema(spec, evidence_paths)
    if spec.get('protocol') == l2_rubric.PROTOCOL:
        return l2_rubric.response_schema(spec, evidence_paths)
    check_ids = [c["id"] for c in spec["checks"]]
    evidence = object_schema(
        {
            "file": enum(evidence_paths),
            "observation": TEXT,
            "bbox": {"anyOf": [array(RATIO, minItems=4, maxItems=4), {"type": "null"}]},
        }
    )
    issue = object_schema(
        {
            "check_id": enum(check_ids),
            "root_cause_id": TEXT,
            "issue_type": enum([v for values in ISSUE_TYPES.values() for v in values]),
            "dimension": enum(ISSUE_TYPES),
            "severity": enum(SEVERITY),
            "location": TEXT,
            "candidate": TEXT,
            "reference_or_requirement": TEXT,
            "affected_units": array(
                enum(
                    sorted(
                        {unit for check in spec["checks"] for unit in check["units"]}
                    )
                ),
                minItems=1,
                uniqueItems=True,
            ),
            "affected_count": {"type": "integer", "minimum": 1},
            "denominator": {"type": "integer", "minimum": 1},
            "affected_ratio": RATIO,
            "confidence": enum(["high", "medium", "low"]),
            "evidence": array({"$ref": "#/$defs/evidence"}, minItems=1),
        }
    )
    branches = []
    for check in spec["checks"]:
        properties = dict(issue["properties"])
        properties.update(
            {
                "check_id": enum([check["id"]]),
                "dimension": enum([check["dimension"]]),
                "issue_type": enum(ISSUE_TYPES[check["dimension"]]),
                "affected_units": array(
                    enum(check["units"]), minItems=1, uniqueItems=True
                ),
                "affected_count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": len(check["units"]),
                },
                "denominator": {"type": "integer", "enum": [len(check["units"])]},
            }
        )
        branches.append(object_schema(properties))
    result = object_schema(
        {
            "protocol": enum([spec['protocol']]),
            "case_id": enum([spec["case_id"]]),
            "vlm_gate": object_schema({"passed": {"type": "boolean"}, "reason": TEXT}),
            "checks": array(
                object_schema(
                    {
                        "check_id": enum(check_ids),
                        "status": enum(["pass", "fail", "unobservable"]),
                        "reason": TEXT,
                    }
                ),
                minItems=len(check_ids),
                maxItems=len(check_ids),
            ),
            "issues": array({"anyOf": branches}),
            "summary": TEXT,
        }
    )
    result["$defs"] = {"evidence": evidence}
    return result


def validate_response(response, spec, evidence_paths):
    validate_spec(spec)
    Draft202012Validator(response_schema(spec, evidence_paths)).validate(response)
    checks = {c["id"]: c for c in spec["checks"]}
    statuses = {c["check_id"]: c["status"] for c in response["checks"]}
    if len(statuses) != len(checks) or set(statuses) != set(checks):
        raise ValueError("Each checklist item must be answered exactly once")
    roots, failed, fatal = set(), set(), False
    for issue in response["issues"]:
        check = checks[issue["check_id"]]
        if issue["root_cause_id"] in roots:
            raise ValueError(
                "Merge repeated views/types of a root cause into one issue"
            )
        roots.add(issue["root_cause_id"])
        failed.add(check["id"])
        units = set(issue["affected_units"])
        if not units <= set(check["units"]):
            raise ValueError(
                "Affected units must be selected from the frozen checklist"
            )
        if issue["denominator"] != len(check["units"]) or issue[
            "affected_count"
        ] != len(units):
            raise ValueError("Counts/denominator disagree with frozen units")
        if not math.isclose(
            issue["affected_ratio"], len(units) / len(check["units"]), abs_tol=1e-6
        ):
            raise ValueError(
                "affected_ratio must equal affected_count / frozen denominator"
            )
        if issue["dimension"] != check["dimension"]:
            raise ValueError("Issue dimension differs from frozen check")
        if issue["issue_type"] not in ISSUE_TYPES[issue["dimension"]]:
            raise ValueError("Issue type does not belong to its dimension")
        if not any(e["file"].startswith("candidate/") for e in issue["evidence"]):
            raise ValueError("Every issue needs candidate evidence")
        for evidence in issue["evidence"]:
            box = evidence["bbox"]
            if box is not None and not (box[0] < box[2] and box[1] < box[3]):
                raise ValueError("bbox must be normalized [left, top, right, bottom]")
        if issue["severity"] == "fatal":
            if not check["critical"] or issue["confidence"] != "high":
                raise ValueError(
                    "Fatal requires a frozen critical check and high confidence"
                )
            if issue["dimension"] == "render_integrity":
                if "scene_visibility" not in units:
                    raise ValueError(
                        "Fatal rendering failure must affect overall scene visibility"
                    )
            elif len(units) != len(check["units"]):
                raise ValueError(
                    "Partial inventory/relation failures are not whole-task fatal errors"
                )
            fatal = True
    if failed != {k for k, v in statuses.items() if v == "fail"}:
        raise ValueError("Failed checks and issue check_ids must agree")
    if response["vlm_gate"]["passed"] == fatal:
        raise ValueError("Gate failure must be backed by an eligible fatal issue")
    return response


def score(response, spec, evidence_paths):
    from . import strict_continuous
    if spec.get('protocol') == strict_continuous.PROTOCOL:
        return strict_continuous.score(response, spec, evidence_paths)
    from . import task_continuous
    if spec.get('protocol') == task_continuous.PROTOCOL:
        return task_continuous.score(response, spec, evidence_paths)
    from . import image_continuous
    if spec.get('protocol') == image_continuous.PROTOCOL:
        return image_continuous.score(response, spec, evidence_paths)
    from . import l2_rubric, l2_fidelity
    if spec.get('protocol') == l2_fidelity.PROTOCOL:
        return l2_fidelity.score(response, spec, evidence_paths)
    if spec.get('protocol') == l2_rubric.PROTOCOL:
        return l2_rubric.score(response, spec, evidence_paths)
    """v1: union/max per frozen unit; no double deduction for overlapping defects.

    Feishu freezes severity coefficients but not dimension weights. Use its
    coefficients directly on the total (0..1), with no invented family weights.
    Low-confidence observations are review-only. Unobservability remains explicit
    and suppresses S_vlm rather than silently awarding a perfect score.
    """
    validate_response(response, spec, evidence_paths)
    by_unit, review = {}, []
    for issue in response["issues"]:
        if issue["confidence"] == "low":
            review.append(issue["root_cause_id"])
            continue
        for unit in issue["affected_units"]:
            key = (issue["check_id"], unit)
            by_unit[key] = max(
                by_unit.get(key, 0), SEVERITY[issue["severity"]] / issue["denominator"]
            )
    deductions = {dim: 0.0 for dim in ISSUE_TYPES}
    checks = {c["id"]: c for c in spec["checks"]}
    for (check_id, _), value in by_unit.items():
        deductions[checks[check_id]["dimension"]] += value
    observed = sum(c["status"] != "unobservable" for c in response["checks"])
    gate = response["vlm_gate"]["passed"]
    diagnostic = round(max(0.0, 1 - sum(deductions.values())), 6) if gate else 0.0
    complete = observed == len(checks) and not review
    return {
        "protocol": spec['protocol'],
        "case_id": spec["case_id"],
        "status": "scored" if complete or not gate else "needs_review",
        "S_vlm": diagnostic if complete or not gate else None,
        "diagnostic_score": diagnostic,
        "S_core": None,
        "gate_passed": gate,
        "coverage": observed / len(checks),
        "deductions_by_dimension": {k: round(v, 6) for k, v in deductions.items()},
        "review_root_causes": review,
        "unobservable_checks": [
            c["check_id"] for c in response["checks"] if c["status"] == "unobservable"
        ],
        "score_rule": "max penalty per frozen unit, sum across units/checks; fatal=0; severity 0.20/0.08/0.02",
    }
