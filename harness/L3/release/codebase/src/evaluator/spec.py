"""Declarative, versioned L1/L2 specifications; no task-defined scoring weights."""

# Schema validation consistently reports invalid JSON values as ValueError.
# ruff: noqa: TRY004

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

import tomllib

# P0/P1 protocol revision: tolerance boundaries are explicit, semantic entity
# matching is supported, and multi-section hole profiles are evaluator-owned.
# The parser still accepts v1.0.0 task specs for controlled migration, while
# normalizing their loaded representation to this version and a new digest.
EVALUATOR_VERSION = "scalable-v1.1.0"
L2_EVALUATOR_VERSION = "l2-v2.2.0"
L1_WEIGHTS = MappingProxyType(
    {"spec": 0.35, "geometry": 0.20, "structure": 0.15, "visual": 0.15, "robust": 0.15}
)
L2_WEIGHTS = MappingProxyType(
    {
        "content": 0.25,
        "spatial": 0.25,
        "physics": 0.15,
        "visual": 0.15,
        "structure": 0.10,
        "robust": 0.10,
    }
)
IMPORTANCE = MappingProxyType({"low": 1.0, "normal": 2.0, "high": 4.0})
EDIT_THRESHOLD = 0.8
_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Artifact paths must be nonempty POSIX relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in {"", ".", ".."} for p in value.split("/")):
        raise ValueError(f"Unsafe relative path: {value!r}")
    return value


def contained_path(root: Path, relative: str) -> Path:
    path = (root / relative_path(relative)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes its root: {relative}")
    return path


def _keys(data: Any, allowed: set[str], name: str) -> None:
    if not isinstance(data, dict):
        raise ValueError(f"{name} must be an object")
    if extra := data.keys() - allowed:
        raise ValueError(f"Unknown {name} fields: {sorted(extra)}")


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{name} must contain only letters, digits, '_' and '-'")
    return value


@dataclass(frozen=True)
class CheckSpec:
    id: str
    metric: str
    group: str
    importance: str
    role: str
    applicable: bool
    reason: str | None
    pass_threshold: float
    params: dict[str, Any]

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> CheckSpec:
        _keys(
            raw,
            {
                "id",
                "metric",
                "group",
                "importance",
                "role",
                "applicable",
                "reason",
                "pass_threshold",
                "params",
            },
            "check",
        )
        check_id = _identifier(raw.get("id"), "check id")
        metric = _identifier(raw.get("metric"), "metric")
        group = _identifier(raw.get("group"), "semantic group")
        importance = raw.get("importance", "normal")
        if importance not in IMPORTANCE:
            raise ValueError(f"Unknown importance: {importance}")
        role = raw.get("role", "standard")
        if role not in {"standard", "target", "preserve"}:
            raise ValueError(f"Unknown check role: {role}")
        applicable = raw.get("applicable", True)
        if not isinstance(applicable, bool):
            raise ValueError("applicable must be a boolean")
        reason = raw.get("reason")
        if not applicable and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError("Inapplicable checks require a predeclared reason")
        threshold = finite_number(raw.get("pass_threshold", 1.0), "pass_threshold")
        # This continuous quality factor has an availability check, not an
        # uncalibrated binary image-quality cutoff. Other metrics stay strict.
        if not (0 < threshold <= 1 or metric == 'native_image_pair' and threshold == 0):
            raise ValueError("pass_threshold must be in (0, 1]")
        params = raw.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("check params must be an object")
        return cls(
            check_id,
            metric,
            group,
            importance,
            role,
            applicable,
            reason,
            threshold,
            copy.deepcopy(params),
        )


@dataclass(frozen=True)
class EvalSpec:
    """Load with ``from_dict`` or ``load`` to validate before inspecting candidates."""

    mode: str
    profile: str
    required_artifacts: tuple[str, ...]
    critical_constraints: tuple[str, ...]
    checks: dict[str, tuple[CheckSpec, ...]]
    render_views: tuple[dict[str, Any], ...]
    seeds: tuple[int, ...]
    scene: str
    reference_scene: str | None
    baseline_scene: str | None
    reference_images: dict[str, str]
    tolerances: dict[str, float]
    _source: dict[str, Any]

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)

    def to_json(self) -> str:
        return json.dumps(
            self._source, sort_keys=True, ensure_ascii=False, allow_nan=False
        )

    @classmethod
    def load(cls, path: Path) -> EvalSpec:
        if path.suffix.lower() == ".toml":
            with path.open("rb") as stream:
                raw = tomllib.load(stream)
        elif path.suffix.lower() == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
        else:
            raise ValueError("EvalSpec must be JSON or TOML")
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EvalSpec:
        _keys(
            raw,
            {
                "version",
                "profile",
                "mode",
                "required_artifacts",
                "critical_constraints",
                "checks",
                "render_views",
                "seeds",
                "scene",
                "reference_scene",
                "baseline_scene",
                "reference_images",
                "tolerances",
                "l1_protocol",
                "l1_geometry",
                "l1_edit_quality",
                "l1_image_quality",
            },
            "EvalSpec",
        )
        # Also rejects non-finite constants nested in expected values or params.
        json.dumps(raw, allow_nan=False)
        if raw.get("version", EVALUATOR_VERSION) not in {
            EVALUATOR_VERSION,
            L2_EVALUATOR_VERSION,
            "scalable-v1.0.0",
            "l1-v1.0.0",
        }:
            raise ValueError(f"Expected evaluator version {EVALUATOR_VERSION}")
        profile = raw.get("profile")
        if profile not in {"L1", "L2"}:
            raise ValueError("profile must be L1 or L2")
        if "l1_protocol" in raw and profile != "L1":
            raise ValueError("l1_protocol is only supported for L1")
        if "l1_geometry" in raw:
            if profile != "L1" or "l1_protocol" not in raw:
                raise ValueError("l1_geometry requires an L1 requirements protocol")
            from .l1_mesh import validate_geometry_policy

            validate_geometry_policy(raw["l1_geometry"])
        if profile != "L2" and raw.get("version") == L2_EVALUATOR_VERSION:
            raise ValueError("L2 evaluator version requires profile L2")
        mode = raw.get("mode")
        if mode not in {"text", "reference", "edit", "transfer"}:
            raise ValueError("mode must be text, reference, edit or transfer")
        artifacts = raw.get("required_artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("required_artifacts must be a nonempty list")
        artifacts = tuple(relative_path(p) for p in artifacts)
        if len(set(artifacts)) != len(artifacts):
            raise ValueError("Duplicate required artifacts")
        scene = relative_path(raw.get("scene", "scene.blend"))
        if scene not in artifacts or not scene.endswith(".blend"):
            raise ValueError("scene must name a required .blend artifact")
        checks_raw = raw.get("checks")
        weights = L1_WEIGHTS if profile == "L1" else L2_WEIGHTS
        _keys(checks_raw, set(weights), "checks")
        if set(checks_raw) != set(weights):
            expected_modules = "five" if profile == "L1" else "six"
            raise ValueError(
                f"checks must declare all {expected_modules} {profile} modules"
            )
        checks: dict[str, tuple[CheckSpec, ...]] = {}
        all_checks: dict[str, CheckSpec] = {}
        has_edit = False
        for module, entries in checks_raw.items():
            if not isinstance(entries, list) or not entries:
                raise ValueError(f"{module} must declare at least one check")
            parsed = tuple(CheckSpec.parse(entry) for entry in entries)
            groups: dict[tuple[str, str], str] = {}
            for check in parsed:
                if check.id in all_checks:
                    raise ValueError(f"Duplicate check id: {check.id}")
                all_checks[check.id] = check
                key = (check.role, check.group)
                if key in groups and groups[key] != check.importance:
                    raise ValueError("Checks in a semantic group must share importance")
                groups[key] = check.importance
            roles = {c.role for c in parsed if c.applicable}
            if roles - {"standard"}:
                if mode not in {"edit", "transfer"} or roles != {"target", "preserve"}:
                    raise ValueError(
                        "Edited modules require both target and preserve checks only"
                    )
                has_edit = True
            checks[module] = parsed
        if mode in {"edit", "transfer"} and not has_edit:
            raise ValueError("Edit/transfer specs require target and preserve checks")
        if "l1_protocol" in raw:
            from .l1_requirements import validate_protocol

            validate_protocol(raw["l1_protocol"], all_checks)
        if 'l1_edit_quality' in raw:
            from .l1_edit_quality import validate
            validate(raw['l1_edit_quality'], raw, all_checks)
        if 'l1_image_quality' in raw:
            from .l1_image_quality import validate
            validate(raw['l1_image_quality'], raw, all_checks)
        critical = raw.get("critical_constraints", [])
        if not isinstance(critical, list) or not all(
            isinstance(p, str) for p in critical
        ):
            raise ValueError("critical_constraints must be a list of check ids")
        if len(set(critical)) != len(critical):
            raise ValueError("Duplicate critical constraint")
        for check_id in critical:
            if check_id not in all_checks or not all_checks[check_id].applicable:
                raise ValueError(
                    f"Critical constraint is unknown or inapplicable: {check_id}"
                )
        views = raw.get("render_views", [])
        if not isinstance(views, list):
            raise ValueError("render_views must be a list")
        view_ids = set()
        for view in views:
            _keys(
                view,
                {
                    "id",
                    "location",
                    "target",
                    "ortho_scale",
                    "resolution",
                    "beauty_resolution",
                    "beauty",
                    "camera_source",
                    "frame",
                },
                "view",
            )
            view_id = _identifier(view.get("id"), "view id")
            if view_id in view_ids:
                raise ValueError(f"Duplicate view id: {view_id}")
            view_ids.add(view_id)
            for field in ("location", "target"):
                values = view.get(field)
                if not isinstance(values, list) or len(values) != 3:
                    raise ValueError(
                        f"view {field} must contain three coordinates in metres"
                    )
                for value in values:
                    finite_number(value, field)
            if view["location"] == view["target"]:
                raise ValueError("Camera location must differ from target")
            if finite_number(view.get("ortho_scale"), "ortho_scale") <= 0:
                raise ValueError("ortho_scale must be positive")
            resolution = view.get("resolution", 256)
            if type(resolution) is not int or not 16 <= resolution <= 2048:
                raise ValueError("resolution must be an integer in [16, 2048]")
            if "beauty_resolution" in view:
                beauty_resolution = view["beauty_resolution"]
                if (
                    not isinstance(beauty_resolution, list)
                    or len(beauty_resolution) != 2
                    or any(
                        type(value) is not int or not 16 <= value <= 4096
                        for value in beauty_resolution
                    )
                ):
                    raise ValueError(
                        "beauty_resolution must contain two integers in [16, 4096]"
                    )
            if "beauty" in view and type(view["beauty"]) is not bool:
                raise ValueError("view beauty must be a boolean")
            if 'camera_source' in view and (
                not isinstance(view['camera_source'], str)
                or view['camera_source'] not in {'saved', 'declared'} or profile != 'L1'
                or not view.get('beauty') or 'beauty_resolution' not in view
            ):
                raise ValueError('Saved camera or declared camera requires an L1 beauty view and explicit resolution')
            if type(view.get("frame", 1)) is not int:
                raise ValueError("view frame must be an integer")
        seeds = raw.get("seeds", [0, 1, 2])
        if (
            not isinstance(seeds, list)
            or not seeds
            or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds)
            or len(set(seeds)) != len(seeds)
        ):
            raise ValueError("seeds must be unique unsigned 32-bit integers")
        reference = raw.get("reference_scene")
        baseline = raw.get("baseline_scene")
        for path in (reference, baseline):
            if path is not None:
                relative_path(path)
        reference_images = raw.get("reference_images", {})
        if not isinstance(reference_images, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in reference_images.items()
        ):
            raise ValueError("reference_images must map view ids to relative paths")
        for key, value in reference_images.items():
            _identifier(key, "reference image id")
            relative_path(value)
            if profile == "L1" and key not in view_ids:
                raise ValueError(
                    f"Reference image {key!r} must name a declared render view"
                )
        tolerances = raw.get("tolerances", {})
        if not isinstance(tolerances, dict):
            raise ValueError("tolerances must be an object")
        for key, value in tolerances.items():
            _identifier(key, "tolerance name")
            if finite_number(value, key) <= 0:
                raise ValueError("Named tolerances must be positive")
        source = copy.deepcopy(raw)
        source.update(
            version=L2_EVALUATOR_VERSION if profile == "L2" else EVALUATOR_VERSION,
            scene=scene,
            seeds=seeds,
            render_views=views,
            critical_constraints=critical,
        )
        return cls(
            mode,
            profile,
            artifacts,
            tuple(critical),
            checks,
            tuple(copy.deepcopy(views)),
            tuple(seeds),
            scene,
            reference,
            baseline,
            copy.deepcopy(reference_images),
            copy.deepcopy(tolerances),
            source,
        )
