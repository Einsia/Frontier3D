"""Reusable atomic metrics over evaluator-owned facts, never submitted scores."""

# External evidence type errors are normalized into metric failures.
# ruff: noqa: TRY004

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity

from .spec import CheckSpec, EvalSpec, finite_number


class MissingEvidence(ValueError):
    """A declared measurement is unavailable; it remains in the denominator."""


def resolve(evidence: dict[str, Any], pointer: str) -> Any:
    """Resolve a JSON pointer (object names may themselves contain dots or '/')."""
    value: Any = evidence
    try:
        for part in pointer[1:].split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            value = value[int(key)] if isinstance(value, list) else value[key]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise MissingEvidence(f"Missing evidence: {pointer}") from error
    if value is None:
        raise MissingEvidence(f"Missing evidence: {pointer}")
    return value


def _numbers(value: Any) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind not in "iuf" or not array.size:
        raise ValueError("Expected a nonempty numeric scalar or array")
    array = array.astype(float)
    if not np.isfinite(array).all():
        raise ValueError("Measurement contains non-finite numbers")
    return array


@dataclass(frozen=True)
class MetricResult:
    score: float
    status: str
    passed: bool
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Metric = Callable[[CheckSpec, dict[str, Any], EvalSpec], tuple[float, dict[str, Any]]]
REGISTRY: dict[str, Metric] = {}
_PARAMS: dict[str, tuple[set[str], set[str]]] = {}


def _scale(value: Any, spec: EvalSpec) -> float:
    if isinstance(value, str):
        if value not in spec.tolerances:
            raise ValueError(f"Unknown named tolerance: {value}")
        value = spec.tolerances[value]
    return finite_number(value, "metric tolerance")


def _scene_objects(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects = resolve(evidence, "/scene/objects")
    if not isinstance(objects, dict):
        raise ValueError("Scene objects evidence must be an object")
    return objects


def _select_objects(
    objects: dict[str, dict[str, Any]], selector: Any
) -> list[dict[str, Any]]:
    if isinstance(selector, str):
        selector = {"name": selector}
    if not isinstance(selector, dict) or set(selector) - {
        "name",
        "pattern",
        "type",
        "min_count",
        "max_count",
    }:
        raise ValueError("Object selector must contain name, pattern or type")
    if "name" in selector:
        if not isinstance(selector["name"], str):
            raise ValueError("Object name selector must be a string")
        names = [selector["name"]]
    elif "pattern" in selector:
        if not isinstance(selector["pattern"], str):
            raise ValueError("Object pattern selector must be a string")
        names = [name for name in objects if re.search(selector["pattern"], name)]
    else:
        names = list(objects)
    selected = [objects[name] for name in names if name in objects]
    if "type" in selector:
        selected = [item for item in selected if item.get("type") == selector["type"]]
    return selected


def _selected_named_objects(
    evidence: dict[str, Any], selector: Any, *, root: str = "/scene/objects"
) -> list[tuple[str, dict[str, Any]]]:
    objects = resolve(evidence, root)
    if not isinstance(objects, dict):
        raise ValueError("Scene objects evidence must be an object")
    selected = _select_objects(objects, selector)
    names = {id(item): name for name, item in objects.items()}
    return [(names[id(item)], item) for item in selected]


def _overlap_2d(first: dict[str, Any], second: dict[str, Any], tolerance: float) -> bool:
    first_bounds = first.get("bounds")
    second_bounds = second.get("bounds")
    if not first_bounds or not second_bounds:
        return False
    return all(
        first_bounds[0][axis] <= second_bounds[1][axis] + tolerance
        and second_bounds[0][axis] <= first_bounds[1][axis] + tolerance
        for axis in (0, 1)
    )


def _object_field_equal(actual: Any, expected: Any, tolerance: float) -> bool:
    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        try:
            left, right = _numbers(actual), _numbers(expected)
        except ValueError:
            return actual == expected
        return left.shape == right.shape and bool(np.max(np.abs(left - right)) <= tolerance)
    return type(actual) is type(expected) and actual == expected


def _path_image(evidence: dict[str, Any], pointer: str) -> Path:
    path = Path(resolve(evidence, pointer))
    if not path.is_file():
        raise MissingEvidence(f"Missing image: {path}")
    return path


def _register(
    name: str, required: str, optional: str = ""
) -> Callable[[Metric], Metric]:
    def register(function: Metric) -> Metric:
        REGISTRY[name] = function
        _PARAMS[name] = (set(required.split()), set(optional.split()))
        return function

    return register


def validate_metrics(spec: EvalSpec) -> None:
    """Reject misspelled/unsupported metrics before running any submission."""
    if spec.profile == "L2":
        from . import l2_metrics
    views = {view["id"] for view in spec.render_views}
    numeric_bindings = {}
    image_views = set()
    for checks in spec.checks.values():
        for check in checks:
            if check.metric not in REGISTRY:
                raise ValueError(f"Unknown metric {check.metric!r} in {check.id}")
            required, optional = _PARAMS[check.metric]
            params = check.params
            if required - params.keys() or params.keys() - required - optional:
                raise ValueError(f"Invalid parameters for {check.metric}: {check.id}")
            if check.metric.startswith('l2_'):
                if spec.profile != 'L2':
                    raise ValueError('L2 metrics require profile L2')
                l2_metrics.validate_parameters(check)
            if check.metric == 'all_seed_checks':
                from .l1_seed_quality import validate_parameters
                validate_parameters(check, spec)
            if check.metric == 'procedural_material_sequence':
                from .l1_material_sequence import validate_parameters
                validate_parameters(check, spec)
            if check.metric == 'machined_sleeve':
                from .l1_sleeve import FEATURES, validate_design
                if spec.profile != 'L1' or not spec.to_dict().get('l1_geometry'):
                    raise ValueError('Sleeve measurements require L1 trusted mesh inspection')
                if (params['feature'] not in FEATURES or params['scene'] not in {'/scene', '/artifacts/scene.glb/scene'}
                        or not isinstance(params['path'], str)
                        or re.fullmatch(r'/numeric_checks/[A-Za-z0-9_-]+', params['path']) is None):
                    raise ValueError('Invalid sleeve feature or evidence binding')
                validate_design(params['design'])
                binding = (check.metric, params['scene'], params['design'])
                if params['path'] in numeric_bindings and numeric_bindings[params['path']] != binding:
                    raise ValueError('Conflicting sleeve measurement cache binding')
                numeric_bindings[params['path']] = binding
            if check.metric == 'washer_edit':
                from .l1_washer_edit import FEATURES, validate_design
                if (spec.profile != 'L1' or spec.mode != 'edit' or not spec.to_dict().get('l1_geometry')
                        or not spec.baseline_scene):
                    raise ValueError('Washer edit requires L1 edit mode, initial scene and trusted mesh inspection')
                expected_scope = {'/scene': 'native_constant_principled', '/artifacts/scene.glb/scene': 'gltf_core_pbr'}
                if (params['feature'] not in FEATURES or params['scene'] not in expected_scope
                        or params['baseline'] != '/baseline' or params['material_scope'] != expected_scope[params['scene']]
                        or not isinstance(params['path'], str)
                        or re.fullmatch(r'/numeric_checks/[A-Za-z0-9_-]+', params['path']) is None):
                    raise ValueError('Invalid washer feature or baseline/material binding')
                validate_design(params['design'])
                binding = (check.metric, params['scene'], params['baseline'], params['design'], params['material_scope'])
                if params['path'] in numeric_bindings and numeric_bindings[params['path']] != binding:
                    raise ValueError('Conflicting washer measurement cache binding')
                numeric_bindings[params['path']] = binding
            if check.metric == 'slot_plate_edit':
                from .l1_slot_plate_edit import FEATURES, validate_policy
                expected_scope = {'/scene': 'native_constant_principled', '/artifacts/scene.glb/scene': 'gltf_core_pbr'}
                if (spec.profile != 'L1' or spec.mode != 'edit' or not spec.to_dict().get('l1_geometry')
                        or not spec.baseline_scene or params['feature'] not in FEATURES
                        or params['scene'] not in expected_scope or params['baseline'] != '/baseline'
                        or params['material_scope'] != expected_scope[params['scene']]
                        or not isinstance(params['path'], str)
                        or re.fullmatch(r'/numeric_checks/[A-Za-z0-9_-]+', params['path']) is None):
                    raise ValueError('Plate edit requires strict L1 edit, mesh, initial and format bindings')
                validate_policy(params['design'], params['material_tolerance'])
                binding = (check.metric, params['scene'], params['baseline'], params['design'],
                           params['material_scope'], params['material_tolerance'])
                if params['path'] in numeric_bindings and numeric_bindings[params['path']] != binding:
                    raise ValueError('Conflicting plate measurement cache binding')
                numeric_bindings[params['path']] = binding
            if check.metric == 'swept_bar':
                from .l1_sweep_measurements import FEATURES, validate_design
                if spec.profile != 'L1' or spec.mode != 'text' or not spec.to_dict().get('l1_geometry'):
                    raise ValueError('Swept bar requires L1 text mode and trusted mesh inspection')
                if (params['feature'] not in FEATURES or params['scene'] not in {'/scene','/artifacts/scene.glb/scene'}
                        or not isinstance(params['path'],str)
                        or re.fullmatch(r'/numeric_checks/[A-Za-z0-9_-]+',params['path']) is None):
                    raise ValueError('Invalid sweep feature or evidence binding')
                validate_design(params['design'])
                binding = (check.metric,params['scene'],params['design'])
                if params['path'] in numeric_bindings and numeric_bindings[params['path']] != binding:
                    raise ValueError('Conflicting sweep measurement cache binding')
                numeric_bindings[params['path']] = binding
            if check.metric in {'native_image_pair', 'main_render_consistency'}:
                from .l1_image_pair import validate_parameters
                validate_parameters(check, spec)
                if check.metric == 'native_image_pair' and check.applicable:
                    if params['view'] in image_views:
                        raise ValueError('Each native image view must have a single quality factor')
                    image_views.add(params['view'])
                    camera = next(v for v in spec.render_views if v['id'] == params['view'])
                    if camera.get('camera_source') == 'declared':
                        if any(Path(name).suffix.lower() in {'.png', '.jpg', '.jpeg'} for name in spec.required_artifacts):
                            raise ValueError('Declared-camera image quality cannot bypass a submitted-image contract')
                    elif not any(c.applicable and c.metric == 'main_render_consistency'
                               and c.params.get('view') == params['view'] and c.id in spec.critical_constraints
                               for group in spec.checks.values() for c in group):
                        raise ValueError('Native image quality requires a critical saved-PNG consistency check')
            for key in ("path", "reference_path"):
                if key in params and (
                    not isinstance(params[key], str) or not params[key].startswith("/")
                ):
                    raise ValueError(f"{key} must be a JSON pointer")
            if "expected" in params and "reference_path" in params:
                raise ValueError("Use either expected or reference_path, not both")
            if (
                check.metric in {"equals", "numeric", "distance"}
                and "expected" not in params
                and "reference_path" not in params
            ):
                raise ValueError(f"{check.id} requires expected or reference_path")
            for key in ("tolerance", "tau"):
                if key in params and _scale(params[key], spec) <= 0:
                    raise ValueError(f"{key} must be positive")
            if check.metric in {"numeric", "distance"} and "expected" in params:
                _numbers(params["expected"])
            if check.metric in {"range", "similarity"}:
                low = finite_number(params["min"], "min")
                high = finite_number(params["max"], "max")
                if low > high or (check.metric == "similarity" and low == high):
                    raise ValueError("Invalid measurement interval")
            if "view" in params and params["view"] not in views:
                raise ValueError(f"Unknown frozen view: {params['view']}")
            if check.metric == "mask_iou" and not spec.reference_scene:
                raise ValueError("mask_iou requires reference_scene")
            if check.metric == "occupancy":
                points, inside = params["points"], params["inside"]
                if (
                    not isinstance(points, list)
                    or not points
                    or not isinstance(inside, list)
                    or len(points) != len(inside)
                    or any(type(v) is not bool for v in inside)
                ):
                    raise ValueError(
                        "occupancy needs equally sized points and boolean inside arrays"
                    )
                for point in points:
                    if _numbers(point).shape != (3,):
                        raise ValueError(
                            "occupancy points must be xyz coordinates in metres"
                        )
                if "objects" in params and (
                    not isinstance(params["objects"], list)
                    or not params["objects"]
                    or not all(isinstance(name, str) for name in params["objects"])
                ):
                    raise ValueError("objects must be a nonempty name list")
            if check.metric == "hole_profile":
                center = _numbers(params.get("center"))
                if center.shape != (2,):
                    raise ValueError("hole_profile center must be xy")
                z_values = params.get("z_values")
                if (
                    not isinstance(z_values, list)
                    or len(z_values) < 2
                    or any(not isinstance(value, (int, float)) for value in z_values)
                ):
                    raise ValueError("hole_profile needs at least two z_values")
                if finite_number(params.get("radius"), "hole radius") <= 0:
                    raise ValueError("hole_profile radius must be positive")
                _scale(params.get("tolerance"), spec)
                if "angular_samples" in params and (
                    type(params["angular_samples"]) is not int
                    or params["angular_samples"] < 8
                ):
                    raise ValueError("hole_profile angular_samples must be >= 8")
                if "objects" in params and (
                    not isinstance(params["objects"], list)
                    or not params["objects"]
                    or not all(isinstance(name, str) for name in params["objects"])
                ):
                    raise ValueError("hole_profile objects must be a nonempty name list")
            if check.metric == "hole_pattern":
                centers = params.get("centers")
                if (
                    not isinstance(centers, list)
                    or not centers
                    or any(
                        not isinstance(center, list)
                        or len(center) != 2
                        or _numbers(center).shape != (2,)
                        for center in centers
                    )
                ):
                    raise ValueError("hole_pattern centers must be nonempty xy points")
                z_values = params.get("z_values")
                if (
                    not isinstance(z_values, list)
                    or len(z_values) < 2
                    or any(not isinstance(value, (int, float)) for value in z_values)
                ):
                    raise ValueError("hole_pattern needs at least two z_values")
                if finite_number(params.get("radius"), "hole radius") <= 0:
                    raise ValueError("hole_pattern radius must be positive")
                _scale(params.get("tolerance"), spec)
                if "objects" not in params:
                    dimensions = _numbers(params.get("object_dimensions"))
                    if dimensions.shape != (3,) or bool((dimensions <= 0).any()):
                        raise ValueError("hole_pattern needs object_dimensions or objects")
                    if _scale(
                        params.get("object_dimension_tolerance", 0.0), spec
                    ) < 0:
                        raise ValueError("object dimension tolerance cannot be negative")
                elif (
                    not isinstance(params["objects"], list)
                    or not params["objects"]
                    or not all(isinstance(name, str) for name in params["objects"])
                ):
                    raise ValueError("hole_pattern objects must be a nonempty name list")
                for key in ("angular_samples", "axis_samples"):
                    if key in params and (
                        type(params[key]) is not int or params[key] < 8
                    ):
                        raise ValueError(f"hole_pattern {key} must be >= 8")
                if "relative_to_object" in params and type(
                    params["relative_to_object"]
                ) is not bool:
                    raise ValueError("hole_pattern relative_to_object must be boolean")
            if check.metric == "coverage":
                paths = params["paths"]
                if (
                    not isinstance(paths, list)
                    or not paths
                    or not all(isinstance(p, str) and p.startswith("/") for p in paths)
                    or len(paths) != len(set(paths))
                ):
                    raise ValueError("coverage paths must be unique JSON pointers")
            if check.metric == "object_coverage":
                rules = params["rules"]
                if not isinstance(rules, list) or not rules:
                    raise ValueError("object_coverage rules must be a nonempty list")
                for rule in rules:
                    if not isinstance(rule, dict) or set(rule) - {
                        "pattern",
                        "name",
                        "type",
                        "min_count",
                        "max_count",
                    }:
                        raise ValueError("Invalid object_coverage rule")
                    if not isinstance(rule.get("pattern", rule.get("name")), str):
                        raise ValueError("Object rule needs a string pattern or name")
                    if not any(key in rule for key in ("min_count", "max_count")):
                        raise ValueError("Object rule needs min_count or max_count")
                    for key in ("min_count", "max_count"):
                        if key in rule and (
                            type(rule[key]) is not int or rule[key] < 0
                        ):
                            raise ValueError(
                                "Object counts must be nonnegative integers"
                            )
            if check.metric == "semantic_inventory":
                parts = params.get("parts")
                if not isinstance(parts, list) or not parts:
                    raise ValueError("semantic_inventory parts must be a nonempty list")
                part_ids = set()
                for part in parts:
                    if not isinstance(part, dict) or set(part) - {
                        "id", "type", "count", "dimensions", "tolerance"
                    }:
                        raise ValueError("Invalid semantic_inventory part")
                    if not isinstance(part.get("id"), str) or not part["id"]:
                        raise ValueError("semantic_inventory part needs an id")
                    if part["id"] in part_ids:
                        raise ValueError("Duplicate semantic_inventory part id")
                    part_ids.add(part["id"])
                    if part.get("type", "MESH") != "MESH":
                        raise ValueError("semantic_inventory currently supports MESH parts")
                    if type(part.get("count")) is not int or part["count"] < 1:
                        raise ValueError("semantic_inventory count must be positive")
                    dimensions = _numbers(part.get("dimensions"))
                    if dimensions.shape != (3,) or bool((dimensions <= 0).any()):
                        raise ValueError("semantic_inventory dimensions must be xyz")
                    if _scale(part.get("tolerance"), spec) <= 0:
                        raise ValueError("semantic_inventory tolerance must be positive")
            if check.metric == "part_geometry":
                rules = params["rules"]
                if not isinstance(rules, list) or not rules:
                    raise ValueError("part_geometry rules must be a nonempty list")
                for rule in rules:
                    if not isinstance(rule, dict) or set(rule) - {
                        "selector",
                        "count",
                        "dimensions",
                        "tolerance",
                    }:
                        raise ValueError("Invalid part_geometry rule")
                    if not isinstance(rule.get("selector"), (str, dict)):
                        raise ValueError("part_geometry selector is required")
                    if type(rule.get("count")) is not int or rule["count"] < 1:
                        raise ValueError("part_geometry count must be positive")
                    dimensions = _numbers(rule.get("dimensions"))
                    if dimensions.shape != (3,):
                        raise ValueError("part_geometry dimensions must be xyz")
                    if _scale(rule.get("tolerance"), spec) <= 0:
                        raise ValueError("part_geometry tolerance must be positive")
            if check.metric == "relation":
                if not isinstance(params.get("left"), (str, dict)) or not isinstance(
                    params.get("right"), (str, dict)
                ):
                    raise ValueError("relation needs left and right selectors")
                relation_name = params.get("relation")
                if relation_name not in {
                    "left_of",
                    "right_of",
                    "above",
                    "below",
                    "in_front_of",
                    "behind",
                    "near",
                    "far",
                    "contains",
                    "disjoint",
                }:
                    raise ValueError("Unknown spatial relation")
                if relation_name in {"near", "far"} and "tolerance" not in params:
                    raise ValueError("near/far relations require tolerance")
            if check.metric == "coaxial":
                if not isinstance(params.get("left"), (str, dict)) or not isinstance(
                    params.get("right"), (str, dict)
                ):
                    raise ValueError("coaxial needs left and right selectors")
                if params.get("axis") not in {"x", "y", "z"}:
                    raise ValueError("coaxial axis must be x, y or z")
                if _scale(params.get("position_tolerance"), spec) < 0:
                    raise ValueError("coaxial position_tolerance must be nonnegative")
                angular = params.get("angular_tolerance", 0.01)
                if (
                    isinstance(angular, bool)
                    or not isinstance(angular, (int, float))
                    or not math.isfinite(float(angular))
                    or float(angular) < 0
                ):
                    raise ValueError("coaxial angular_tolerance must be nonnegative")
                for key in ("left_dimensions", "right_dimensions"):
                    if key in params:
                        dimensions = _numbers(params[key])
                        if dimensions.shape != (3,) or bool((dimensions <= 0).any()):
                            raise ValueError(f"{key} must be positive xyz dimensions")
                if "dimension_tolerance" in params and _scale(params["dimension_tolerance"], spec) < 0:
                    raise ValueError("coaxial dimension_tolerance must be nonnegative")
            if check.metric == "ground_contact":
                if not isinstance(params.get("selector"), (str, dict)):
                    raise ValueError("ground_contact needs a selector")
                _scale(params["max_height"], spec)
            if check.metric == "collision_free" and (
                type(params.get("max_pairs")) is not int or params["max_pairs"] < 0
            ):
                raise ValueError("collision_free needs a nonnegative max_pairs")
            if check.metric == "camera_config":
                if not isinstance(params.get("camera"), str):
                    raise ValueError("camera_config needs a camera name")
                if not any(
                    key in params for key in ("projection", "resolution", "elevation")
                ):
                    raise ValueError("camera_config needs a target property")
                if "projection" in params and not isinstance(params["projection"], str):
                    raise ValueError("camera projection must be a string")
                if "resolution" in params and (
                    not isinstance(params["resolution"], list)
                    or len(params["resolution"]) != 2
                    or any(
                        type(value) is not int or value <= 0
                        for value in params["resolution"]
                    )
                ):
                    raise ValueError("camera resolution must be two positive integers")
                if "elevation" in params and (
                    not isinstance(params["elevation"], list)
                    or len(params["elevation"]) != 2
                    or any(
                        not isinstance(value, (int, float))
                        for value in params["elevation"]
                    )
                    or params["elevation"][0] > params["elevation"][1]
                ):
                    raise ValueError(
                        "camera elevation must be an ordered two-number range"
                    )
            if check.metric == "image_ssim":
                for key in ("candidate", "reference"):
                    if not isinstance(params.get(key), str) or not params[
                        key
                    ].startswith("/"):
                        raise ValueError(
                            "image_ssim needs candidate/reference JSON pointers"
                        )
            if check.metric == "render_similarity":
                if not isinstance(params.get("view"), str):
                    raise ValueError("render_similarity needs a view")
                if params["view"] not in spec.reference_images:
                    raise ValueError(
                        "render_similarity needs a reference image for its view"
                    )
            if check.metric == "image_validity" and (
                not isinstance(params.get("path"), str)
                or not params["path"].startswith("/")
            ):
                raise ValueError("image_validity needs an image JSON pointer")
            if check.metric == "dimension_match":
                axes = params.get("axes")
                expected = params.get("expected")
                if (
                    not isinstance(axes, list)
                    or not axes
                    or any(type(axis) is not int or axis not in {0, 1, 2} for axis in axes)
                    or len(set(axes)) != len(axes)
                    or not isinstance(expected, list)
                    or len(expected) != len(axes)
                ):
                    raise ValueError("dimension_match needs unique axes and matching expected values")
                _scale(params["tolerance"], spec)
            if check.metric == "billboard_free" and (
                type(params.get("max_suspects")) is not int
                or params["max_suspects"] < 0
            ):
                raise ValueError("billboard_free needs a nonnegative max_suspects")
            if check.metric == "scene_preservation":
                fields = params.get("fields")
                if (
                    not isinstance(fields, list)
                    or not fields
                    or not all(isinstance(field, str) for field in fields)
                ):
                    raise ValueError("scene_preservation needs a nonempty fields list")
                allowed_fields = {
                    "parent", "location", "rotation", "scale", "dimensions",
                    "bounds", "visible_render", "editable", "modifiers", "materials",
                    "image_texture_count",
                }
                if set(fields) - allowed_fields:
                    raise ValueError("scene_preservation has an unknown field")
                _scale(params["tolerance"], spec)
                for key in ("ignore_patterns",):
                    if key in params and (
                        not isinstance(params[key], list)
                        or not all(isinstance(value, str) for value in params[key])
                    ):
                        raise ValueError("scene_preservation ignore_patterns must be strings")
            if check.metric == "camera_delta":
                if not isinstance(params.get("camera"), str):
                    raise ValueError("camera_delta needs a camera")
                if not isinstance(params.get("baseline_camera", params.get("reference_camera")), str):
                    raise ValueError("camera_delta needs baseline_camera or reference_camera")
                for key in ("max_location_delta", "max_rotation_delta", "max_lens_delta"):
                    if key in params:
                        _scale(params[key], spec)
                if "expected_local_delta" in params:
                    if (
                        not isinstance(params["expected_local_delta"], list)
                        or len(params["expected_local_delta"]) != 3
                    ):
                        raise ValueError("expected_local_delta must be xyz")
                    _numbers(params["expected_local_delta"])
            if check.metric == "corridor_clearance":
                if not isinstance(params.get("corridor"), (str, dict)):
                    raise ValueError("corridor_clearance needs a corridor selector")
                if type(params.get("axis")) is not int or params["axis"] not in {0, 1}:
                    raise ValueError("corridor_clearance axis must be 0 or 1")
                _scale(params["min_width"], spec)
                if "blocked" in params and not isinstance(params["blocked"], (str, dict)):
                    raise ValueError("corridor_clearance blocked must be a selector")
            if check.metric == "corridor_connectivity":
                for key in ("corridors", "start", "goal"):
                    if not isinstance(params.get(key), (str, dict)):
                        raise ValueError(f"corridor_connectivity needs {key} selector")
                if type(params.get("axis")) is not int or params["axis"] not in {0, 1}:
                    raise ValueError("corridor_connectivity axis must be 0 or 1")
                _scale(params["min_width"], spec)
                _scale(params["snap_distance"], spec)


def evaluate_metric(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> MetricResult:
    if spec.profile == "L2":
        from . import l2_metrics  # noqa: F401
    if not check.applicable:
        return MetricResult(0.0, "not_applicable", False, {"reason": check.reason})
    try:
        score, details = REGISTRY[check.metric](check, evidence, spec)
        score = finite_number(score, "metric score")
        if not 0 <= score <= 1:
            raise ValueError("Metric output is outside [0, 1]")
        json.dumps(details, allow_nan=False)
        # A tolerance check is a boolean protocol decision, not a demand for
        # mathematically exact floating-point equality. Metrics that expose an
        # explicit ``within_tolerance`` result take precedence over the generic
        # continuous score threshold. Other metrics retain their declared
        # pass_threshold semantics.
        passed = (
            bool(details["within_tolerance"])
            if "within_tolerance" in details
            else score >= check.pass_threshold
        )
        return MetricResult(score, "ok", passed, details)
    except MissingEvidence as error:
        return MetricResult(0.0, "missing", False, {"error": str(error)})
    except (OSError, ValueError, TypeError, OverflowError) as error:
        return MetricResult(0.0, "invalid", False, {"error": str(error)})


def _pair(check: CheckSpec, evidence: dict[str, Any]) -> tuple[Any, Any]:
    params = check.params
    expected = (
        resolve(evidence, params["reference_path"])
        if "reference_path" in params
        else params["expected"]
    )
    return resolve(evidence, params["path"]), expected


@_register("equals", "path", "expected reference_path")
def equals(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    actual, expected = _pair(check, evidence)
    # Python otherwise treats True == 1, which could accept malformed gate evidence.
    passed = type(actual) is type(expected) and actual == expected
    return float(passed), {"actual": actual, "expected": expected}


@_register('slot_plate_edit', 'path scene baseline design material_scope material_tolerance feature')
def slot_plate_edit(check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec) -> tuple[float, dict]:
    from .l1_slot_plate_edit import PROTOCOL
    audit = resolve(evidence, check.params['path'])
    if (not isinstance(audit, dict) or audit.get('protocol') != PROTOCOL
            or audit.get('design') != check.params['design']
            or audit.get('material_scope') != check.params['material_scope']
            or audit.get('material_tolerance') != check.params['material_tolerance']):
        raise MissingEvidence('Missing or incorrectly bound plate edit measurement')
    feature = audit.get('features', {}).get(check.params['feature'])
    if not isinstance(feature, dict) or feature.get('status') not in {'passed', 'failed'}:
        raise MissingEvidence('Plate feature is not measurable: '+str(feature))
    passed = feature['status'] == 'passed'
    if feature.get('passed') is not passed:
        raise ValueError('Inconsistent plate verdict')
    sources = audit.get('sources', {})
    if not sources:
        if passed or check.params['feature'] != 'solid':
            raise MissingEvidence('Plate measurement has no actual sources')
    else:
        for label, pointer in [('candidate', check.params['scene']), ('initial', check.params['baseline'])]:
            source = sources.get(label, {})
            row = resolve(evidence, pointer).get('objects', {}).get(source.get('object'), {})
            if (not source.get('mesh_payload') or row.get('mesh_payload') != source['mesh_payload']
                    or row.get('material_surface') != source.get('material_surface')):
                raise MissingEvidence('Plate geometry/material measurement source changed')
    return float(passed), {'protocol': PROTOCOL, 'design': audit['design'], 'feature': check.params['feature'],
        'measurement': feature, 'sources': sources, 'material_scope': audit['material_scope'],
        'material_tolerance': audit['material_tolerance']}


@_register('swept_bar', 'path scene design feature')
def swept_bar(check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec) -> tuple[float, dict]:
    from .l1_sweep_measurements import PROTOCOL
    audit = resolve(evidence,check.params['path'])
    if not isinstance(audit,dict) or audit.get('protocol') != PROTOCOL or audit.get('design') != check.params['design']:
        raise MissingEvidence('Missing or incorrectly bound swept-bar measurement')
    feature = audit.get('features',{}).get(check.params['feature'])
    if not isinstance(feature,dict) or feature.get('status') not in {'passed','failed'}:
        raise MissingEvidence('Sweep feature is not measurable: '+str(feature))
    passed = feature['status']=='passed'
    if feature.get('passed') is not passed:
        raise ValueError('Inconsistent sweep feature verdict')
    if audit.get('source'):
        source = audit['source']
        scene = resolve(evidence,check.params['scene'])
        if (scene.get('objects',{}).get(source['object'],{}).get('mesh_payload') != source['mesh_payload']
                or source['reference']['sha256'] != check.params['design']['reference_sha256']):
            raise MissingEvidence('Sweep measurement source does not match actual mesh/reference')
    elif passed:
        raise MissingEvidence('Sweep passing feature has no mesh source')
    return float(passed), {'protocol':PROTOCOL,'design':audit['design'],'feature':check.params['feature'],
                           'measurement':feature,'source':audit.get('source')}


@_register('machined_sleeve', 'path scene design feature')
def machined_sleeve(check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec) -> tuple[float, dict]:
    from .l1_sleeve import PROTOCOL

    audit = resolve(evidence, check.params['path'])
    if (not isinstance(audit, dict) or audit.get('protocol') != PROTOCOL
            or audit.get('design') != check.params['design']):
        raise MissingEvidence('Missing or incorrectly bound sleeve measurement')
    feature = audit.get('features', {}).get(check.params['feature'])
    if not isinstance(feature, dict) or feature.get('status') not in {'passed', 'failed'}:
        raise MissingEvidence('Sleeve feature is not measurable: '+str(feature))
    passed = feature['status'] == 'passed'
    if feature.get('passed') is not passed:
        raise ValueError('Inconsistent sleeve feature verdict')
    return float(passed), {'protocol': PROTOCOL, 'design': audit['design'], 'feature': check.params['feature'],
                           'measurement': feature, 'source': audit.get('source')}


@_register('washer_edit', 'path scene baseline design material_scope feature')
def washer_edit(check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec) -> tuple[float, dict]:
    from .l1_washer_edit import PROTOCOL

    audit = resolve(evidence, check.params['path'])
    if (not isinstance(audit, dict) or audit.get('protocol') != PROTOCOL
            or audit.get('design') != check.params['design']
            or audit.get('material_scope') != check.params['material_scope']):
        raise MissingEvidence('Missing or incorrectly bound washer measurement')
    feature = audit.get('features', {}).get(check.params['feature'])
    if not isinstance(feature, dict) or feature.get('status') not in {'passed', 'failed'}:
        raise MissingEvidence('Washer feature is not measurable: '+str(feature))
    passed = feature['status'] == 'passed'
    if feature.get('passed') is not passed:
        raise ValueError('Inconsistent washer feature verdict')
    return float(passed), {'protocol': PROTOCOL, 'design': audit['design'], 'feature': check.params['feature'],
                           'measurement': feature, 'source': audit.get('source')}


@_register('edit_surface', 'path feature')
def edit_surface(check, evidence, spec):
    from .l1_edit_surface import PROTOCOL
    audit = resolve(evidence,check.params['path'])
    if (spec.profile!='L1' or spec.mode!='edit' or 'l1_edit_quality' not in spec.to_dict()
            or audit.get('protocol')!=PROTOCOL or audit.get('status')!='measured'
            or check.params['feature'] not in {'target','preservation'}):
        raise MissingEvidence('Missing native edit surface measurement')
    policy=spec.to_dict()['l1_edit_quality']['surface']
    if any(audit.get(k)!=policy[k] for k in ('dimension_m','preserve_m')) or audit.get('samples_per_scene')!=policy['samples']:
        raise MissingEvidence('Native edit surface policy changed')
    return float(audit[check.params['feature']]), audit


@_register("procedural_materials", "path")
def procedural_materials(check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec) -> tuple[float, dict]:
    from .l1_procedural_materials import PROTOCOL

    audit = resolve(evidence, check.params["path"])
    if not isinstance(audit, dict) or audit.get("protocol") != PROTOCOL:
        raise MissingEvidence("Missing trusted procedural-material inspection")
    if audit.get("status") == "not_measurable":
        raise MissingEvidence(f"Procedural-material audit incomplete: {audit.get('unknown')}")
    if audit.get("status") not in {"passed", "failed"}:
        raise ValueError("Invalid procedural-material audit status")
    passed = audit["status"] == "passed"
    if (audit.get("passed") is not passed or type(audit.get("material_uses")) is not int
            or audit["material_uses"] <= 0 or not isinstance(audit.get("violations"), list)
            or not isinstance(audit.get("unknown"), list)
            or (passed and (audit["violations"] or audit["unknown"]))
            or (not passed and not audit["violations"])):
        raise ValueError("Inconsistent procedural-material inspection")
    return float(passed), audit


@_register('all_seed_checks', 'checks native_frames glb_frames')
def all_seed_checks(check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec) -> tuple[float, dict]:
    from .l1_seed_quality import measure
    return measure(check, evidence, spec)


@_register('procedural_material_sequence', 'path frames')
def procedural_material_sequence(check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec) -> tuple[float, dict]:
    from .l1_material_sequence import measure
    return measure(check, evidence, spec)


@_register("numeric", "path tolerance", "expected reference_path")
def numeric(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    actual, expected = _pair(check, evidence)
    left, right = _numbers(actual), _numbers(expected)
    if left.shape != right.shape:
        raise ValueError("Measurement and target shapes differ")
    if spec.profile == "L1" and "l1_protocol" in spec.to_dict():
        from .l1_numeric import tolerance_measurement

        return tolerance_measurement(actual, expected, _scale(check.params["tolerance"], spec))
    errors = np.abs(left - right)
    score = float(
        np.clip(1 - errors / _scale(check.params["tolerance"], spec), 0, 1).mean()
    )
    tolerance = _scale(check.params["tolerance"], spec)
    return score, {
        "actual": actual,
        "expected": expected,
        "absolute_error": errors.tolist(),
        "max_absolute_error": float(np.max(errors)),
        "tolerance": tolerance,
        "within_tolerance": bool(np.all(errors <= tolerance)),
    }


@_register("distance", "path tau", "expected reference_path")
def distance(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    actual, expected = _pair(check, evidence)
    left, right = _numbers(actual), _numbers(expected)
    if left.shape != right.shape:
        raise ValueError("Measurement and target shapes differ")
    error = float(np.linalg.norm((left - right).ravel()))
    return math.exp(-error / _scale(check.params["tau"], spec)), {
        "actual": actual,
        "expected": expected,
        "distance": error,
    }


@_register("range", "path min max")
def within_range(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    actual = resolve(evidence, check.params["path"])
    values = _numbers(actual)
    passed = (values >= check.params["min"]) & (values <= check.params["max"])
    return float(passed.mean()), {"actual": actual}


@_register("similarity", "path min max")
def similarity(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    value = finite_number(resolve(evidence, check.params["path"]), "similarity")
    low, high = check.params["min"], check.params["max"]
    return min(1.0, max(0.0, (value - low) / (high - low))), {"actual": value}


@_register("coverage", "paths")
def coverage(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    outcomes = {}
    for path in check.params["paths"]:
        try:
            outcomes[path] = resolve(evidence, path) is True
        except MissingEvidence:
            outcomes[path] = False
    return sum(outcomes.values()) / len(outcomes), {"outcomes": outcomes}


@_register("occupancy", "points inside", "objects")
def occupancy(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    actual = resolve(evidence, f"/probes/{check.id}")
    expected = check.params["inside"]
    if (
        not isinstance(actual, list)
        or len(actual) != len(expected)
        or any(type(v) is not bool for v in actual)
    ):
        raise ValueError("Incomplete or invalid occupancy measurements")
    return sum(a == b for a, b in zip(actual, expected, strict=True)) / len(expected), {
        "actual": actual,
        "expected": expected,
    }


@_register("hole_profile", "center z_values radius tolerance", "objects angular_samples")
def hole_profile(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    measured = resolve(evidence, f"/probes/{check.id}")
    if not isinstance(measured, dict):
        raise MissingEvidence("Missing hole profile measurement")
    layers = measured.get("layers")
    if not isinstance(layers, list) or not layers:
        raise MissingEvidence("Hole profile has no section measurements")
    expected = _scale(check.params["radius"], spec) if isinstance(check.params["radius"], str) else finite_number(check.params["radius"], "hole radius")
    tolerance = _scale(check.params["tolerance"], spec)
    errors = []
    for layer in layers:
        radius = layer.get("radius") if isinstance(layer, dict) else None
        if radius is None:
            continue
        errors.append(abs(float(radius) - expected))
    if len(errors) != len(layers):
        within = False
    else:
        within = bool(errors) and max(errors) <= tolerance and measured.get("through_layers") is True
    max_error = max(errors) if errors else None
    score = 0.0 if max_error is None else max(0.0, 1.0 - max_error / max(tolerance, 1e-12))
    if spec.profile == "L1" and "l1_protocol" in spec.to_dict() and errors:
        from .l1_numeric import tolerance_measurement

        score, numeric_details = tolerance_measurement(
            [layer["radius"] for layer in layers if isinstance(layer, dict) and layer.get("radius") is not None],
            [expected] * len(errors), tolerance,
        )
        within = (numeric_details["within_tolerance"] and len(errors) == len(layers)
                  and measured.get("through_layers") is True)
    if measured.get("through_layers") is not True:
        score *= 0.5
    return score, {
        "expected_radius": expected,
        "tolerance": tolerance,
        "layers": layers,
        "max_radius_error": max_error,
        "through_layers": measured.get("through_layers") is True,
        "within_tolerance": within,
        "limitations": ["Section medians and through_layers alone do not prove a fully open, circular bore."],
    }


@_register(
    "hole_pattern",
    "centers z_values radius tolerance",
    "objects object_dimensions object_dimension_tolerance angular_samples axis_samples relative_to_object",
)
def hole_pattern(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    """Score a repeated hole pattern with per-hole through-axis evidence."""
    measured = resolve(evidence, f"/probes/{check.id}")
    if not isinstance(measured, dict):
        raise MissingEvidence("Missing hole pattern measurement")
    holes = measured.get("holes")
    expected_count = len(check.params["centers"])
    if not isinstance(holes, list) or len(holes) != expected_count:
        raise MissingEvidence("Hole pattern has an incomplete hole list")
    expected_radius = finite_number(check.params["radius"], "hole radius")
    tolerance = _scale(check.params["tolerance"], spec)
    errors = [
        float(hole["max_radius_error"])
        for hole in holes
        if isinstance(hole, dict) and isinstance(hole.get("max_radius_error"), (int, float))
    ]
    per_hole = []
    for hole in holes:
        if not isinstance(hole, dict) or not isinstance(hole.get("layers"), list):
            per_hole.append({"passed": False, "reason": "missing_layers"})
            continue
        error = hole.get("max_radius_error")
        passed = (
            isinstance(error, (int, float))
            and math.isfinite(error)
            and error <= tolerance
            and hole.get("through_axis") is True
        )
        per_hole.append(
            {
                "center": hole.get("center"),
                "max_radius_error": error,
                "through_axis": hole.get("through_axis") is True,
                "passed": passed,
            }
        )
    passed_count = sum(item["passed"] for item in per_hole)
    score = passed_count / expected_count
    if errors and spec.profile == "L1" and "l1_protocol" in spec.to_dict():
        from .l1_numeric import tolerance_measurement

        measured_values = [
            expected_radius + error for error in errors
        ]
        numeric_score, _ = tolerance_measurement(
            measured_values, [expected_radius] * len(errors), tolerance
        )
        score = min(score, numeric_score)
    return score, {
        "expected_count": expected_count,
        "measured_count": len(holes),
        "expected_radius": expected_radius,
        "tolerance": tolerance,
        "holes": per_hole,
        "within_tolerance": passed_count == expected_count,
        "limitations": [
            "Radial sections and sampled axis points are finite-resolution evidence, not a continuous CAD proof."
        ],
    }


def _mask(evidence: dict[str, Any], pointer: str) -> np.ndarray:
    path = Path(resolve(evidence, pointer))
    if not path.is_file():
        raise MissingEvidence(f"Missing evaluator mask: {path}")
    with Image.open(path) as image:
        if image.mode != "L":
            raise ValueError("Evaluator silhouette must be a grayscale mask")
        return np.asarray(image) >= 128


@_register("mask_iou", "view")
def mask_iou(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    view = check.params["view"]
    left = _mask(evidence, f"/views/{view}/mask")
    right = _mask(evidence, f"/reference_views/{view}/mask")
    if left.shape != right.shape:
        raise ValueError("Fixed-view mask resolutions differ")
    union = int(np.count_nonzero(left | right))
    intersection = int(np.count_nonzero(left & right))
    return intersection / union if union else 0.0, {
        "intersection": intersection,
        "union": union,
    }


@_register("render_validity", "view")
def render_validity(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    if spec.profile == 'L1' and 'l1_image_quality' in spec.to_dict():
        from .l1_image_pair import saved_image, read_bound_image
        view = next(v for v in spec.render_views if v['id'] == check.params['view'])
        definition = {k:view[k] for k in ('location','target','ortho_scale')} if view['camera_source']=='declared' else None
        native, pixels = saved_image(evidence,view['id'],spec.scene,frame=view['frame'],
            camera_source=view['camera_source'],definition=definition)
        mask = read_bound_image(native['mask'],native['mask_sha256'])
        if mask.shape[:2] != pixels.shape[:2] or list(pixels.shape[1::-1]) != view['beauty_resolution']:
            raise MissingEvidence('Native image/mask resolution does not match the declared view')
        # Beauty capture uses real-geometry alpha, not the legacy grayscale
        # silhouette. Framing differences reduce appearance, not render validity.
        return 1., {'protocol':native['render_protocol'],'foreground_fraction':float((mask[...,3]>=128).mean()),
            'foreground_affects_eligibility':False,'source_sha256':native['source_sha256'],
            'render_sha256':native['image_sha256'],'mask_sha256':native['mask_sha256']}
    mask = _mask(evidence, f"/views/{check.params['view']}/mask")
    fraction = float(mask.mean())
    # Versioned occupancy limits reject empty frames and fully occluded cameras.
    return float(0.001 <= fraction <= 0.95), {"foreground_fraction": fraction}


@_register("seed_success", "")
def seed_success(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    if spec.profile == 'L1' and any(k in spec.to_dict() for k in ('l1_edit_quality','l1_image_quality')):
        from .l1_edit_validity import reproduction
        return reproduction(spec, evidence)
    outcomes = {}
    for seed in spec.seeds:
        try:
            run = resolve(evidence, f"/harness/seed_runs/{seed}")
            if not isinstance(run, dict):
                raise MissingEvidence("Seed run must be an object")
            passed = run.get("passed") is True
            # Once semantic reproduction is configured, execution success is
            # necessary but not sufficient for the fixed-seed gate. Historical
            # records without this field retain their legacy execution-only
            # meaning and are not silently scored as semantic passes.
            outcomes[str(seed)] = passed and (
                run.get("reproduction_status") == "ok"
                if "reproduction_status" in run
                else True
            )
        except MissingEvidence:
            outcomes[str(seed)] = False
    return sum(outcomes.values()) / len(spec.seeds), {
        "outcomes": outcomes,
        "semantic_reproduction_required": any(
            isinstance(run, dict) and "reproduction_status" in run
            for run in evidence.get("harness", {}).get("seed_runs", {}).values()
        ),
    }


@_register("object_coverage", "rules")
def object_coverage(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    objects = _scene_objects(evidence)
    outcomes = {}
    for index, rule in enumerate(check.params["rules"]):
        selected = _select_objects(objects, rule)
        count = len(selected)
        passed = (count >= rule["min_count"] if "min_count" in rule else True) and (
            count <= rule["max_count"] if "max_count" in rule else True
        )
        outcomes[str(index)] = {"count": count, "passed": passed}
    return sum(item["passed"] for item in outcomes.values()) / len(outcomes), {
        "outcomes": outcomes
    }


@_register("semantic_inventory", "parts")
def semantic_inventory(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    """Match required part roles by measured geometry, never by object names.

    This is deliberately a conservative inventory check. It uses evaluated
    dimensions and a one-to-one assignment, so renaming objects cannot make a
    missing part pass and one candidate object cannot satisfy two roles.
    Feature-level checks (holes, axes and assembly relations) remain separate
    metrics and are not inferred from this inventory result.
    """
    objects = _scene_objects(evidence)
    if spec.profile == "L1" and "l1_protocol" in spec.to_dict():
        from .l1_numeric import match_dimension_proxies

        return match_dimension_proxies(objects, check.params["parts"], spec.tolerances)
    candidates = [
        item for item in objects.values()
        if item.get("type") == "MESH" and item.get("visible_render", True)
        and item.get("dimensions") is not None
    ]
    remaining = list(candidates)
    outcomes: dict[str, Any] = {}
    matched_total = 0
    expected_total = 0
    for part in check.params["parts"]:
        expected_total += part["count"]
        target = np.sort(_numbers(part["dimensions"]))
        tolerance = _scale(part["tolerance"], spec)
        matches: list[dict[str, Any]] = []
        unmatched: list[dict[str, Any]] = []
        # Greedy nearest assignment is deterministic and sufficient for the
        # distinct signatures in the task specs. Each object is removed once.
        scored = []
        for index, item in enumerate(remaining):
            dimensions = np.sort(_numbers(item["dimensions"]))
            if dimensions.shape != target.shape:
                continue
            error = float(np.max(np.abs(dimensions - target)))
            scored.append((error, index, item))
        scored.sort(key=lambda value: (value[0], value[1]))
        used: set[int] = set()
        for error, index, item in scored:
            if len(matches) >= part["count"]:
                break
            if index in used:
                continue
            used.add(index)
            if error <= tolerance:
                matches.append({"max_dimension_error": error})
            else:
                unmatched.append({"max_dimension_error": error})
        if used:
            remaining = [item for index, item in enumerate(remaining) if index not in used]
        matched_total += len(matches)
        outcomes[part["id"]] = {
            "expected_count": part["count"],
            "matched_count": len(matches),
            "matches": matches,
            "near_misses": unmatched,
            "tolerance": tolerance,
            "passed": len(matches) == part["count"],
        }
    expected = len(check.params["parts"])
    passed_roles = sum(item["passed"] for item in outcomes.values())
    return passed_roles / expected, {
        "roles": outcomes,
        "matched_parts": matched_total,
        "expected_parts": expected_total,
        "unmatched_meshes": len(remaining),
        "within_tolerance": bool(passed_roles == expected and not remaining),
    }


@_register("part_geometry", "rules")
def part_geometry(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    """Compare annotated part dimension signatures without trusting names alone."""

    objects = _scene_objects(evidence)
    if spec.profile == "L1" and "l1_protocol" in spec.to_dict():
        from .l1_numeric import match_dimension_proxies

        return match_dimension_proxies(objects, check.params["rules"], spec.tolerances)
    outcomes = {}
    for index, rule in enumerate(check.params["rules"]):
        selected = _select_objects(objects, rule["selector"])
        expected_count = rule["count"]
        target = np.sort(_numbers(rule["dimensions"]))
        tolerance = _scale(rule["tolerance"], spec)
        matching_mode = "selector"
        if len(selected) != expected_count:
            # Names are only an optional hint. When a selector is a name/pattern
            # and it matches nothing, recover the role from the measured shape
            # and use a one-to-one nearest assignment instead of failing a
            # geometrically valid submission because it was renamed.
            selected = [
                item for item in objects.values()
                if item.get("type") == "MESH"
                and item.get("visible_render", True)
                and item.get("dimensions") is not None
            ]
            matching_mode = "dimension_fallback"
        measured = [
            np.sort(_numbers(item.get("dimensions")))
            for item in selected
            if item.get("dimensions") is not None
        ]
        if matching_mode == "dimension_fallback":
            measured.sort(key=lambda value: float(np.max(np.abs(value - target))))
            candidates = measured[:expected_count]
        else:
            candidates = measured
        errors = [
            float(np.max(np.abs(candidate - target))) for candidate in candidates
        ]
        dimension_score = (
            float(np.mean([max(0.0, 1.0 - error / tolerance) for error in errors]))
            if errors
            else 0.0
        )
        count_score = float(len(candidates) == expected_count)
        max_error = max(errors) if errors else None
        outcomes[str(index)] = {
            "count": len(candidates),
            "expected_count": expected_count,
            "max_dimension_error": max_error,
            "tolerance": tolerance,
            "score": count_score * dimension_score,
            "matching_mode": matching_mode,
            "within_tolerance": bool(
                len(candidates) == expected_count
                and bool(errors)
                and all(error <= tolerance for error in errors)
            ),
        }
    all_within_tolerance = all(item["within_tolerance"] for item in outcomes.values())
    return sum(item["score"] for item in outcomes.values()) / len(outcomes), {
        "outcomes": outcomes,
        "within_tolerance": all_within_tolerance,
    }


@_register("relation", "left right relation", "tolerance")
def relation(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    objects = _scene_objects(evidence)
    left = _select_objects(objects, check.params["left"])
    right = _select_objects(objects, check.params["right"])
    if not left or not right:
        raise MissingEvidence("Spatial relation selector matched no objects")
    tolerance = _scale(check.params.get("tolerance", 0.0), spec)
    outcomes = []
    for first in left:
        for second in right:
            if first is second:
                continue
            a = np.asarray(first["location"], dtype=float)
            b = np.asarray(second["location"], dtype=float)
            ad = np.asarray(first.get("dimensions", [0, 0, 0]), dtype=float)
            bd = np.asarray(second.get("dimensions", [0, 0, 0]), dtype=float)
            delta = a - b
            name = check.params["relation"]
            if name == "left_of":
                passed = a[0] + ad[0] / 2 <= b[0] - bd[0] / 2 + tolerance
            elif name == "right_of":
                passed = a[0] - ad[0] / 2 >= b[0] + bd[0] / 2 - tolerance
            elif name == "above":
                passed = a[2] - ad[2] / 2 >= b[2] + bd[2] / 2 - tolerance
            elif name == "below":
                passed = a[2] + ad[2] / 2 <= b[2] - bd[2] / 2 + tolerance
            elif name == "in_front_of":
                passed = a[1] < b[1] + tolerance
            elif name == "behind":
                passed = a[1] > b[1] - tolerance
            elif name == "near":
                passed = float(np.linalg.norm(delta)) <= tolerance
            elif name == "far":
                passed = float(np.linalg.norm(delta)) >= tolerance
            elif name == "contains":
                passed = bool(
                    first.get("bounds")
                    and second.get("bounds")
                    and all(
                        first["bounds"][0][i] <= second["bounds"][0][i]
                        and first["bounds"][1][i] >= second["bounds"][1][i]
                        for i in range(3)
                    )
                )
            else:
                passed = bool(
                    first.get("bounds")
                    and second.get("bounds")
                    and all(
                        first["bounds"][1][i] < second["bounds"][0][i]
                        or first["bounds"][0][i] > second["bounds"][1][i]
                        for i in range(3)
                    )
                )
            outcomes.append(bool(passed))
    if not outcomes:
        raise MissingEvidence("Spatial relation has no distinct object pair")
    return sum(outcomes) / len(outcomes), {
        "pairs": len(outcomes),
        "passed": sum(outcomes),
    }


def _coaxial_selection(
    objects: dict[str, dict[str, Any]],
    selector: Any,
    dimensions: Any,
    dimension_tolerance: float,
) -> tuple[list[tuple[str, dict[str, Any]]], str]:
    """Select diagnostic meshes, using only dimensions when they are declared.

    Names never rescue a failed dimension signature. Neither selector kind
    establishes actual bore identity, which needs evaluated geometry evidence.
    """

    selected = _selected_named_objects({"scene": {"objects": objects}}, selector)
    selected = [
        (name, item)
        for name, item in selected
        if item.get("type") == "MESH" and item.get("visible_render", True)
    ]
    if dimensions is None:
        return selected, "selector"
    target = np.sort(_numbers(dimensions))
    if target.shape != (3,):
        raise ValueError("coaxial dimension signatures must be xyz")
    dimension_selected = []
    for name, item in objects.items():
        if item.get("type") != "MESH" or not item.get("visible_render", True):
            continue
        actual = item.get("dimensions")
        if actual is None:
            continue
        measured = np.sort(_numbers(actual))
        if measured.shape == target.shape and bool(
            np.all(np.abs(measured - target) <= dimension_tolerance)
        ):
            dimension_selected.append((name, item))
    return dimension_selected, "dimension_signature"


@_register(
    "coaxial",
    "left right axis position_tolerance",
    "angular_tolerance left_dimensions right_dimensions dimension_tolerance",
)
def coaxial(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    """Diagnostic object-frame alignment, NOT a physical bore-axis proof.

    Each right-side feature is paired with its nearest left-side axis.  The
    position error is the perpendicular distance from the right object's origin
    to that infinite axis line; the angular error is the unoriented angle
    between the two world-matrix axis columns.  This deliberately does not
    require a particular object name or a fixed order of repeated parts.
    """

    objects = _scene_objects(evidence)
    params = check.params
    dimension_tolerance = _scale(params.get("dimension_tolerance", 0.0), spec)
    left, left_mode = _coaxial_selection(
        objects,
        params["left"],
        params.get("left_dimensions"),
        dimension_tolerance,
    )
    right, right_mode = _coaxial_selection(
        objects,
        params["right"],
        params.get("right_dimensions"),
        dimension_tolerance,
    )
    if not left or not right:
        raise MissingEvidence("Coaxial selectors matched no visible meshes")
    axis_index = {"x": 0, "y": 1, "z": 2}[params["axis"]]
    position_tolerance = _scale(params["position_tolerance"], spec)
    angular_tolerance = float(params.get("angular_tolerance", 0.01))

    def axis_and_origin(name: str, item: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
        matrix = np.asarray(item.get("matrix_world"), dtype=float)
        if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
            raise MissingEvidence(f"Object {name} has no finite 4x4 world matrix")
        vector = matrix[:3, axis_index]
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-12:
            raise ValueError(f"Object {name} has a zero-length world axis")
        location = _numbers(item.get("location"))
        if location.shape != (3,):
            raise MissingEvidence(f"Object {name} has no xyz world location")
        return vector / norm, location

    left_axes = [(name, *axis_and_origin(name, item)) for name, item in left]
    matches = []
    for right_name, right_item in right:
        right_axis, right_origin = axis_and_origin(right_name, right_item)
        candidates = []
        for left_name, left_axis, left_origin in left_axes:
            if left_name == right_name:
                continue
            delta = right_origin - left_origin
            distance = float(np.linalg.norm(np.cross(delta, left_axis)))
            dot = float(np.clip(abs(np.dot(left_axis, right_axis)), -1.0, 1.0))
            angle = float(math.acos(dot))
            candidates.append((distance, angle, left_name))
        if not candidates:
            raise MissingEvidence("Coaxial relation has no distinct object pair")
        distance, angle, left_name = min(candidates, key=lambda value: (value[0], value[1], value[2]))
        matches.append(
            {
                "left": left_name,
                "right": right_name,
                "position_error": distance,
                "angular_error_rad": angle,
                "position_passed": distance <= position_tolerance,
                "angular_passed": angle <= angular_tolerance,
                "passed": distance <= position_tolerance and angle <= angular_tolerance,
            }
        )
    passed = sum(match["passed"] for match in matches)
    return passed / len(matches), {
        "axis": params["axis"],
        "position_tolerance": position_tolerance,
        "angular_tolerance_rad": angular_tolerance,
        "left_count": len(left),
        "right_count": len(right),
        "left_selection": left_mode,
        "right_selection": right_mode,
        "matches": matches,
        "within_tolerance": passed == len(matches),
        "evidence_kind": "object_frame_proxy",
        "physical_coaxiality_proven": False,
        "limitations": [
            "Object origins and matrix columns need not be bore centers or axes. Applying transforms can change this proxy without changing geometry.",
            "Dimension signatures do not establish semantic roles or full part counts. This diagnostic is not used by the official Image2Code EvalSpec.",
        ],
    }


@_register("ground_contact", "selector max_height")
def ground_contact(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    selected = _select_objects(_scene_objects(evidence), check.params["selector"])
    if not selected:
        raise MissingEvidence("Ground selector matched no objects")
    threshold = _scale(check.params["max_height"], spec)
    if not any(item.get("bounds") for item in selected):
        raise MissingEvidence("Ground objects have no bounds")
    values = [
        float(item["bounds"][0][2]) if item.get("bounds") else None for item in selected
    ]
    outcomes = [value is not None and value <= threshold for value in values]
    return sum(outcomes) / len(outcomes), {"min_z": values, "passed": outcomes}


@_register("collision_free", "max_pairs")
def collision_free(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    pairs = resolve(evidence, "/scene/collision_pairs")
    if not isinstance(pairs, list):
        raise MissingEvidence("Missing collision pairs")
    allowed = check.params["max_pairs"]
    return float(len(pairs) <= allowed), {
        "collision_pairs": pairs,
        "max_pairs": allowed,
    }


@_register("dimension_match", "path axes expected tolerance")
def dimension_match(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    actual = _numbers(resolve(evidence, check.params["path"]))
    axes = check.params["axes"]
    expected = _numbers(check.params["expected"])
    if actual.ndim != 1 or expected.shape != (len(axes),):
        raise ValueError("dimension_match expects a vector and matching expected values")
    selected = actual[axes]
    errors = np.abs(selected - expected)
    tolerance = _scale(check.params["tolerance"], spec)
    if spec.profile == "L1" and "l1_protocol" in spec.to_dict():
        from .l1_numeric import tolerance_measurement

        score, details = tolerance_measurement(selected, expected, tolerance)
        return score, {"axes": axes, **details}
    score = float(np.clip(1 - errors / tolerance, 0, 1).mean())
    return score, {
        "axes": axes,
        "actual": selected.tolist(),
        "expected": expected.tolist(),
        "absolute_error": errors.tolist(),
        "max_absolute_error": float(np.max(errors)),
        "tolerance": tolerance,
        "within_tolerance": bool(np.all(errors <= tolerance)),
    }


@_register("billboard_free", "max_suspects")
def billboard_free(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    suspects = resolve(evidence, "/scene/billboard_suspects")
    if not isinstance(suspects, list):
        raise MissingEvidence("Missing billboard audit facts")
    allowed = check.params["max_suspects"]
    return float(len(suspects) <= allowed), {
        "suspects": suspects,
        "max_suspects": allowed,
    }


@_register(
    "scene_preservation",
    "fields tolerance",
    "ignore_patterns candidate_path baseline_path",
)
def scene_preservation(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    candidate_path = check.params.get("candidate_path", "/scene/objects")
    baseline_path = check.params.get("baseline_path", "/baseline/objects")
    candidate = resolve(evidence, candidate_path)
    baseline = resolve(evidence, baseline_path)
    if not isinstance(candidate, dict) or not isinstance(baseline, dict):
        raise MissingEvidence("Scene preservation needs candidate and baseline objects")
    patterns = [re.compile(pattern) for pattern in check.params.get("ignore_patterns", [])]
    names = [
        name
        for name in baseline
        if not any(pattern.search(name) for pattern in patterns)
    ]
    if not names:
        raise MissingEvidence("Scene preservation selector matched no baseline objects")
    tolerance = _scale(check.params["tolerance"], spec)
    fields = check.params["fields"]
    total = len(names) * len(fields)
    passed = 0
    failures = []
    for name in names:
        if name not in candidate:
            failures.append({"object": name, "reason": "missing"})
            continue
        for field in fields:
            if _object_field_equal(candidate[name].get(field), baseline[name].get(field), tolerance):
                passed += 1
            else:
                failures.append({"object": name, "field": field})
    return passed / total, {
        "objects": len(names),
        "fields": fields,
        "passed": passed,
        "total": total,
        "failures": failures[:100],
    }


def _camera(evidence: dict[str, Any], path: str, name: str) -> dict[str, Any]:
    cameras = resolve(evidence, path)
    camera = cameras.get(name) if isinstance(cameras, dict) else None
    if not isinstance(camera, dict):
        raise MissingEvidence(f"Camera not found: {name}")
    return camera


@_register(
    "camera_delta",
    "camera",
    "baseline_camera reference_camera expected_local_delta max_location_delta max_rotation_delta max_lens_delta",
)
def camera_delta(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    params = check.params
    candidate = _camera(evidence, "/scene/cameras", params["camera"])
    reference_name = params.get("reference_camera")
    if reference_name is not None:
        reference = _camera(evidence, "/scene/cameras", reference_name)
    else:
        reference = _camera(evidence, "/baseline/cameras", params["baseline_camera"])
    scores = []
    details: dict[str, Any] = {"camera": params["camera"], "reference": reference_name or params["baseline_camera"]}
    location = np.asarray(candidate.get("location"), dtype=float)
    reference_location = np.asarray(reference.get("location"), dtype=float)
    if location.shape != (3,) or reference_location.shape != (3,):
        raise ValueError("Camera locations must be xyz")
    if "expected_local_delta" in params:
        basis_x = np.asarray(reference.get("basis_x"), dtype=float)
        basis_y = np.asarray(reference.get("basis_y"), dtype=float)
        basis_z = np.asarray(reference.get("basis_z"), dtype=float)
        if any(vector.shape != (3,) for vector in (basis_x, basis_y, basis_z)):
            raise MissingEvidence("Camera basis vectors are unavailable")
        expected = np.asarray(params["expected_local_delta"], dtype=float)
        expected_world = expected[0] * basis_x + expected[1] * basis_y + expected[2] * basis_z
        error = float(np.linalg.norm((location - reference_location) - expected_world))
        score = 1.0 - error / _scale(params.get("max_location_delta", 0.01), spec)
        scores.append(float(np.clip(score, 0, 1)))
        details.update({"location_error": error, "expected_local_delta": expected.tolist()})
    elif "max_location_delta" in params:
        error = float(np.linalg.norm(location - reference_location))
        scores.append(float(np.clip(1 - error / _scale(params["max_location_delta"], spec), 0, 1)))
        details["location_error"] = error
    if "max_rotation_delta" in params:
        rotation = np.asarray(candidate.get("rotation"), dtype=float)
        reference_rotation = np.asarray(reference.get("rotation"), dtype=float)
        if rotation.shape != (3,) or reference_rotation.shape != (3,):
            raise ValueError("Camera rotations must be xyz Euler values")
        error = float(np.max(np.abs(rotation - reference_rotation)))
        scores.append(float(np.clip(1 - error / _scale(params["max_rotation_delta"], spec), 0, 1)))
        details["rotation_error"] = error
    if "max_lens_delta" in params:
        error = abs(float(candidate.get("lens")) - float(reference.get("lens")))
        scores.append(float(np.clip(1 - error / _scale(params["max_lens_delta"], spec), 0, 1)))
        details["lens_error"] = error
    if not scores:
        raise ValueError("camera_delta needs at least one delta constraint")
    return float(np.mean(scores)), details


@_register("corridor_clearance", "corridor axis min_width", "blocked tolerance")
def corridor_clearance(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    corridors = _selected_named_objects(evidence, check.params["corridor"])
    if not corridors:
        raise MissingEvidence("Corridor selector matched no objects")
    axis = check.params["axis"]
    min_width = _scale(check.params["min_width"], spec)
    tolerance = _scale(check.params.get("tolerance", 1e-6), spec) if "tolerance" in check.params else 1e-6
    blocked = _selected_named_objects(evidence, check.params["blocked"]) if "blocked" in check.params else []
    outcomes = []
    details = []
    for name, corridor in corridors:
        dimensions = corridor.get("dimensions")
        if not dimensions or len(dimensions) != 3:
            raise MissingEvidence(f"Corridor has no dimensions: {name}")
        width = float(dimensions[axis])
        blockers = [other_name for other_name, other in blocked if other_name != name and _overlap_2d(corridor, other, tolerance)]
        passed = width + tolerance >= min_width and not blockers
        outcomes.append(passed)
        details.append({"corridor": name, "width": width, "min_width": min_width, "blockers": blockers, "passed": passed})
    return sum(outcomes) / len(outcomes), {"corridors": details}


@_register("corridor_connectivity", "corridors start goal axis min_width snap_distance")
def corridor_connectivity(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    corridor_items = _selected_named_objects(evidence, check.params["corridors"])
    starts = _selected_named_objects(evidence, check.params["start"])
    goals = _selected_named_objects(evidence, check.params["goal"])
    if not corridor_items or not starts or not goals:
        raise MissingEvidence("Corridor connectivity selector matched no objects")
    axis = check.params["axis"]
    min_width = _scale(check.params["min_width"], spec)
    snap = _scale(check.params["snap_distance"], spec)
    usable = [
        (name, item)
        for name, item in corridor_items
        if item.get("dimensions") and float(item["dimensions"][axis]) >= min_width
    ]
    if not usable:
        return 0.0, {"usable_corridors": [], "connected": False}
    nodes = {name for name, _ in usable}
    edges = {name: set() for name in nodes}
    for index, (left_name, left) in enumerate(usable):
        for right_name, right in usable[index + 1 :]:
            if _overlap_2d(left, right, snap):
                edges[left_name].add(right_name)
                edges[right_name].add(left_name)
    def touches(item: dict[str, Any], other: dict[str, Any]) -> bool:
        return _overlap_2d(item, other, snap)
    frontier = [name for name, corridor in usable if any(touches(corridor, start) for _, start in starts)]
    visited = set(frontier)
    while frontier:
        current = frontier.pop()
        for neighbor in edges[current]:
            if neighbor not in visited:
                visited.add(neighbor)
                frontier.append(neighbor)
    connected = any(any(touches(corridor, goal) for _, goal in goals) for name, corridor in usable if name in visited)
    return float(connected), {"usable_corridors": sorted(nodes), "reachable_corridors": sorted(visited), "connected": connected}


@_register("camera_config", "camera", "projection resolution elevation")
def camera_config(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    cameras = resolve(evidence, "/scene/cameras")
    camera = cameras.get(check.params["camera"]) if isinstance(cameras, dict) else None
    if not isinstance(camera, dict):
        raise MissingEvidence("Camera not found")
    outcomes = []
    if "projection" in check.params:
        outcomes.append(camera.get("type") == check.params["projection"])
    if "resolution" in check.params:
        outcomes.append(camera.get("resolution") == check.params["resolution"])
    if "elevation" in check.params:
        low, high = check.params["elevation"]
        outcomes.append(low <= camera.get("elevation", float("nan")) <= high)
    return sum(outcomes) / len(outcomes), {"camera": camera, "outcomes": outcomes}


@_register('native_image_pair', 'view mask_asset mask_sha256 reference_sha256 regions')
def native_image_pair(check, evidence, spec):
    from .l1_image_pair import image_pair
    return image_pair(check, evidence, spec)


@_register('main_render_consistency', 'view artifact mean_tolerance p99_tolerance')
def main_render_consistency(check, evidence, spec):
    from .l1_image_pair import consistency
    return consistency(check, evidence, spec)


@_register("image_ssim", "candidate reference")
def image_ssim(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    candidate = _path_image(evidence, check.params["candidate"])
    reference = _path_image(evidence, check.params["reference"])
    with Image.open(reference) as image:
        size = image.size
    with Image.open(candidate) as image:
        left = np.asarray(image.convert("RGB").resize(size), dtype=np.uint8)
    with Image.open(reference) as image:
        right = np.asarray(image.convert("RGB"), dtype=np.uint8)
    score = float(structural_similarity(left, right, channel_axis=2, data_range=255))
    return max(0.0, min(1.0, score)), {"ssim": score}


@_register("image_validity", "path")
def image_validity(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    path = _path_image(evidence, check.params["path"])
    with Image.open(path) as image:
        pixels = np.asarray(image.convert("L"), dtype=np.float32) / 255
        size = list(image.size)
    fraction = float(np.mean(pixels > 2 / 255))
    passed = fraction >= 0.001
    return float(passed), {"visible_fraction": fraction, "size": size}


@_register("render_similarity", "view")
def render_similarity(
    check: CheckSpec, evidence: dict[str, Any], spec: EvalSpec
) -> tuple[float, dict]:
    """Compare evaluator-owned Workbench renders against a task reference image.

    SSIM captures silhouette, occlusion and shading structure. A separate mean
    color term keeps material and global illumination/background changes visible
    even when edges remain similar. Both paths are generated or staged by the
    evaluator; submitted image files are never used as evidence.
    """
    view = check.params["view"]
    candidate = _path_image(evidence, f"/views/{view}/image")
    reference = _path_image(evidence, f"/reference_images/{view}/path")
    with Image.open(reference) as image:
        right = np.asarray(image.convert("RGB"), dtype=np.float32)
    with Image.open(candidate) as image:
        left = np.asarray(image.convert("RGB").resize((right.shape[1], right.shape[0])), dtype=np.float32)
    if left.shape != right.shape or min(left.shape[:2]) < 7:
        raise ValueError("Render comparison images have incompatible dimensions")
    ssim = float(
        structural_similarity(
            left.astype(np.uint8),
            right.astype(np.uint8),
            channel_axis=2,
            data_range=255,
        )
    )
    color_error = float(np.mean(np.abs(left - right)) / 255.0)
    color_score = max(0.0, 1.0 - color_error)
    score = max(0.0, min(1.0, 0.75 * ssim + 0.25 * color_score))
    return score, {
        "ssim": ssim,
        "color_similarity": color_score,
        "mean_absolute_color_error": color_error,
        "candidate_size": [int(left.shape[1]), int(left.shape[0])],
        "reference_size": [int(right.shape[1]), int(right.shape[0])],
    }
