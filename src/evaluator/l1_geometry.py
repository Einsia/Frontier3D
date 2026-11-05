"""Unified L1 geometry-evidence facade.

The lower-level modules in this package deliberately remain usable on their
own (and are also used by Blender workers).  This facade is the boundary used
by a task evaluator: every operation is reported with the same protocol,
world-metre coordinate declaration, hash-bound input bindings and scoped
availability failure.  It does not apply alignment or silently turn missing
evidence into a zero score.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .l1_failures import FAILURE_STATUSES, InspectionFailure
from .l1_numeric import tolerance_measurement
from .l1_pairing import compare_scene_geometry
from .l1_sections import measure_bore as measure_bore_sections
from .l1_surface import compare_surfaces, load_surface
from .l1_volume import compare_volumes

GEOMETRY_PROTOCOL = "l1-geometry-v1"
_VALID_STATUSES = {"ok", "failed", "not_measurable", *FAILURE_STATUSES}


def _finite_positive(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite positive number")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def _levels(
    values: Any, name: str, *, minimum: int = 1, maximum: int = 65536
) -> tuple[int, ...]:
    try:
        values = tuple(values)
    except TypeError as error:
        raise ValueError(f"{name} must be a nonempty integer sequence") from error
    if (
        not values
        or any(
            type(value) is not int or not minimum <= value <= maximum
            for value in values
        )
        or values != tuple(sorted(set(values)))
    ):
        raise ValueError(f"{name} must be sorted, unique and within its frozen range")
    return values


def _binding(record: dict[str, Any]) -> dict[str, Any]:
    """Return only provenance needed to bind evidence to a mesh packet."""
    packet = record.get("mesh_payload", record)
    if not isinstance(packet, dict):
        raise TypeError("Mesh record must contain a mesh_payload object")
    required = {"path", "sha256", "coordinate_space"}
    if not required <= set(packet):
        raise ValueError("Mesh record lacks hash-bound payload fields")
    return {
        "path": str(packet["path"]),
        "sha256": packet["sha256"],
        "coordinate_space": packet["coordinate_space"],
    }


@dataclass(frozen=True)
class GeometryConfig:
    """Frozen shared settings for one evaluator invocation."""

    trusted_root: Path
    surface_tolerance_m: float = 1e-5
    surface_levels: tuple[int, ...] = (256, 1024, 4096)
    surface_convergence_m: float = 1e-5
    seed: int = 0
    volume_timeout_s: float = 120.0
    volume_grid_levels: tuple[int, ...] = (8, 16, 32)
    blender: Path | None = None
    volume_new_session: bool = True
    surface_only: bool = False
    reproduction_diagnostics: bool = True

    def __post_init__(self) -> None:
        if type(self.surface_only) is not bool:
            raise TypeError('surface_only must be boolean')
        if type(self.reproduction_diagnostics) is not bool:
            raise TypeError('reproduction_diagnostics must be boolean')
        if type(self.volume_new_session) is not bool:
            raise TypeError("volume_new_session must be boolean")
        root = Path(self.trusted_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("trusted_root must be an existing directory")
        object.__setattr__(self, "trusted_root", root)
        object.__setattr__(
            self,
            "surface_tolerance_m",
            _finite_positive(self.surface_tolerance_m, "surface_tolerance_m"),
        )
        object.__setattr__(
            self,
            "surface_convergence_m",
            _finite_positive(self.surface_convergence_m, "surface_convergence_m"),
        )
        object.__setattr__(
            self, "surface_levels", _levels(self.surface_levels, "surface_levels")
        )
        object.__setattr__(
            self,
            "volume_grid_levels",
            _levels(
                self.volume_grid_levels, "volume_grid_levels", minimum=2, maximum=64
            ),
        )
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        object.__setattr__(
            self,
            "volume_timeout_s",
            _finite_positive(self.volume_timeout_s, "volume_timeout_s"),
        )
        if self.blender is not None:
            object.__setattr__(
                self, "blender", Path(self.blender).expanduser().resolve()
            )


class L1GeometryEvaluator:
    """Run shared geometry measurements under one evidence protocol.

    ``status='failed'`` means the geometry was measurable and did not satisfy
    a caller's declared condition.  ``not_measurable`` and
    ``infrastructure_error`` mean that no candidate pass may be inferred.
    """

    def __init__(self, config: GeometryConfig):
        if not isinstance(config, GeometryConfig):
            raise TypeError("config must be a GeometryConfig")
        self.config = config

    def worker_configuration(self) -> dict[str, Any]:
        config = asdict(self.config)
        config["trusted_root"] = str(self.config.trusted_root)
        config["blender"] = str(self.config.blender) if self.config.blender is not None else None
        return config

    def _report(
        self,
        operation: str,
        result: dict[str, Any],
        *,
        inputs: dict[str, Any],
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(result, dict):
            result = {
                "status": "infrastructure_error",
                "reason": "Geometry operation returned a non-object report",
            }
        status = result.get("status")
        if status not in _VALID_STATUSES:
            status = "infrastructure_error"
            result = {
                "status": status,
                "reason": "Geometry operation returned an unknown status",
                "raw_result": result,
            }
        failure = None
        if status in FAILURE_STATUSES:
            failure = {
                "status": status,
                "code": result.get("code", f"GEOMETRY_{status.upper()}"),
                "reason": str(result.get("reason", "Geometry evidence unavailable")),
            }
        return {
            "protocol": GEOMETRY_PROTOCOL,
            "operation": operation,
            "status": status,
            "coordinate_space": result.get("coordinate_space", "world_metres"),
            "units": {"length": "m", "area": "m2", "volume": "m3"},
            "alignment": result.get("alignment", "none"),
            "inputs": inputs,
            "settings": settings or {},
            "failure": failure,
            "evidence": result,
        }

    def _exception_report(
        self,
        operation: str,
        error: Exception,
        *,
        inputs: dict[str, Any],
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(error, InspectionFailure):
            status, code, reason = error.status, error.code, error.reason
        elif isinstance(error, (KeyError, ValueError, OSError)):
            status, code, reason = (
                "not_measurable",
                "GEOMETRY_INPUT_UNAVAILABLE",
                str(error),
            )
        else:
            status, code, reason = (
                "infrastructure_error",
                "GEOMETRY_OPERATION_ERROR",
                str(error),
            )
        return self._report(
            operation,
            {"status": status, "code": code, "reason": reason},
            inputs=inputs,
            settings=settings,
        )

    def compare_surface_records(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
        *,
        tolerance_m: float | None = None,
        levels: tuple[int, ...] | None = None,
        convergence_m: float | None = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Compare two hash-bound mesh packets without alignment."""
        inputs = {}
        try:
            inputs = {"left": _binding(left), "right": _binding(right)}
            result = compare_surfaces(
                load_surface(left.get("mesh_payload", left), self.config.trusted_root),
                load_surface(
                    right.get("mesh_payload", right), self.config.trusted_root
                ),
                levels=self.config.surface_levels
                if levels is None
                else _levels(levels, "levels"),
                convergence_m=self.config.surface_convergence_m
                if convergence_m is None
                else _finite_positive(convergence_m, "convergence_m"),
                seed=self.config.seed if seed is None else seed,
            )
            result = {"status": "ok", **result}
            tolerance = (
                self.config.surface_tolerance_m
                if tolerance_m is None
                else _finite_positive(tolerance_m, "tolerance_m")
            )
            _, decision = tolerance_measurement(
                result["levels"][-1]["sampled_max_m"], 0.0, tolerance
            )
            result["tolerance_decision"] = decision
            result["within_tolerance"] = decision["within_tolerance"]
            return self._report(
                "surface_pair",
                result,
                inputs=inputs,
                settings={
                    "tolerance_m": tolerance,
                },
            )
        except (InspectionFailure, KeyError, OSError, ValueError, TypeError) as error:
            return self._exception_report("surface_pair", error, inputs=inputs)

    def compare_scene_records(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
        *,
        output: Path | None = None,
        tolerance_m: float | None = None,
        minimum_volume_iou: float | None = None,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        """Match complete scenes one-to-one and optionally enforce IoU."""
        inputs = {"left_scene": "geometry_facts", "right_scene": "geometry_facts"}
        threshold = minimum_volume_iou
        settings = {
            "tolerance_m": self.config.surface_tolerance_m
            if tolerance_m is None
            else _finite_positive(tolerance_m, "tolerance_m"),
            "surface_levels": list(self.config.surface_levels),
            "surface_convergence_m": self.config.surface_convergence_m,
            "seed": self.config.seed,
            "volume_grid_levels": list(self.config.volume_grid_levels),
        }
        try:
            if deadline is not None:
                from .l1_compute import run_compute
                return run_compute("geometry_scene", {
                    "config": self.worker_configuration(), "left": left, "right": right,
                    "arguments": {
                        "output": str(output) if output is not None else None,
                        "tolerance_m": tolerance_m, "minimum_volume_iou": minimum_volume_iou,
                    },
                }, output=output if output is not None else self.config.trusted_root / "compute",
                    deadline=deadline)
            if threshold is not None:
                if isinstance(threshold, bool) or not 0 <= float(threshold) <= 1:
                    raise ValueError("minimum_volume_iou must be between zero and one")
                if self.config.blender is None or output is None:
                    raise ValueError(
                        "IoU matching requires configured Blender and output"
                    )
            result = compare_scene_geometry(
                left,
                right,
                trusted_root=self.config.trusted_root,
                tolerance_m=settings["tolerance_m"],
                sample_levels=self.config.surface_levels,
                convergence_m=self.config.surface_convergence_m,
                seed=self.config.seed,
                blender=self.config.blender,
                output=output,
                minimum_volume_iou=threshold,
                volume_timeout=self.config.volume_timeout_s,
                volume_grid_levels=self.config.volume_grid_levels,
                volume_new_session=self.config.volume_new_session,
                surface_only=self.config.surface_only,
            )
            return self._report(
                "scene_pairing", result, inputs=inputs, settings=settings
            )
        except (InspectionFailure, KeyError, OSError, ValueError, TypeError) as error:
            return self._exception_report(
                "scene_pairing", error, inputs=inputs, settings=settings
            )

    def compare_volume_records(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
        *,
        output: Path,
    ) -> dict[str, Any]:
        """Run the independent Boolean/IoU worker with shared settings."""
        inputs = {}
        try:
            inputs = {"left": _binding(left), "right": _binding(right)}
            if self.config.blender is None:
                raise InspectionFailure(
                    "infrastructure_error",
                    "BLENDER_UNAVAILABLE",
                    "No Blender configured",
                )
            result = compare_volumes(
                left,
                right,
                trusted_root=self.config.trusted_root,
                output=Path(output),
                blender=self.config.blender,
                timeout=self.config.volume_timeout_s,
                grid_levels=self.config.volume_grid_levels,
                new_session=self.config.volume_new_session,
            )
            return self._report(
                "volume_pair",
                result,
                inputs=inputs,
                settings={"grid_levels": list(self.config.volume_grid_levels)},
            )
        except (InspectionFailure, KeyError, OSError, ValueError, TypeError) as error:
            return self._exception_report("volume_pair", error, inputs=inputs)

    def measure_bore_record(
        self,
        record: dict[str, Any],
        center,
        axis,
        span_m,
        radius_m: float,
        tolerance_m: float,
        *,
        fractions=(0.125, 0.375, 0.625, 0.875),
    ) -> dict[str, Any]:
        """Measure a declared bore while retaining hash/provenance metadata."""
        inputs = {}
        try:
            inputs = {"mesh": _binding(record)}
            result = measure_bore_sections(
                load_surface(
                    record.get("mesh_payload", record), self.config.trusted_root
                ),
                center,
                axis,
                span_m,
                _finite_positive(radius_m, "radius_m"),
                _finite_positive(tolerance_m, "tolerance_m"),
                fractions=fractions,
                solid_validated=record.get("volume_reliable") is True,
            )
            return self._report(
                "bore_sections",
                result,
                inputs=inputs,
                settings={
                    "radius_m": float(radius_m),
                    "tolerance_m": float(tolerance_m),
                    "solid_validation_source": "trusted_inspector.volume_reliable",
                },
            )
        except (InspectionFailure, KeyError, OSError, ValueError, TypeError) as error:
            return self._exception_report("bore_sections", error, inputs=inputs)


__all__ = ["GEOMETRY_PROTOCOL", "GeometryConfig", "L1GeometryEvaluator"]
