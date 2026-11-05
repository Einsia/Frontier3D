"""Programmatic and VLM-assisted evaluation for 3DBench submissions."""

from .core import evaluate_blender_submission
from .l1 import evaluate_l1_submission, score_l1
from .l1_calibration import CALIBRATION_PROTOCOL, numeric_policy_calibration
from .l1_geometry import GEOMETRY_PROTOCOL, GeometryConfig, L1GeometryEvaluator
from .l1_reproduction import REPRODUCTION_PROTOCOL
from .l2 import evaluate_l2_submission, score_l2
from .spec import L1_WEIGHTS, L2_WEIGHTS, EvalSpec

__all__ = [
    "CALIBRATION_PROTOCOL",
    "GEOMETRY_PROTOCOL",
    "L1_WEIGHTS",
    "L2_WEIGHTS",
    "REPRODUCTION_PROTOCOL",
    "EvalSpec",
    "GeometryConfig",
    "L1GeometryEvaluator",
    "evaluate_blender_submission",
    "evaluate_l1_submission",
    "evaluate_l2_submission",
    "numeric_policy_calibration",
    "score_l1",
    "score_l2",
]
