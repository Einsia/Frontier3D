"""Frozen execution/audit policy in addition to the shared generation config."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from harness.common.config import load_config as load_generation_config
from src.evaluator.spec import EvalSpec, relative_path, contained_path
from .budget import timeout_steps


@dataclass(frozen=True)
class Policy:
    timeout: float
    total: float
    threads: int
    views: tuple[dict, ...]
    mean_error: float
    p99_error: float
    digest: str
    version: str
    environment_files: tuple[str, ...]
    output_files: tuple[str, ...]
    timeout_steps: tuple[float, ...]
    roles: tuple[str, ...] = ()
    max_repairs: int = 1
    baseline_scene: str | None = None
    entity_parts: dict[str, tuple[str, ...]] = field(default_factory=dict)
    requirements: dict = field(default_factory=dict)
    requirements_path: Path | None = None
    spec: EvalSpec | None = None


def load_policy(path: Path, task_id: str, spec: EvalSpec) -> Policy:
    config = load_generation_config(path, level=2, task_prefix="L2/")
    if config.task_id != task_id:
        raise ValueError("Harness task_id does not match task")
    execution = config.source.get("execution", {})
    audit = config.source.get("audit", {})
    if set(execution) - {"timeout_seconds", "max_total_seconds", "threads", "sandbox", "timeout_steps_seconds"}:
        raise ValueError("Unknown L2 execution policy field")
    if execution.get("sandbox") != "bubblewrap":
        raise ValueError("L2 execution sandbox must be bubblewrap")
    if set(audit) - {"views", "max_mean_pixel_error", "max_p99_pixel_error"}:
        raise ValueError("Unknown L2 audit policy field")
    def number(value, name, maximum=None):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"Invalid {name}")
        if maximum is not None and value > maximum:
            raise ValueError(f"Invalid {name}")
        return float(value)
    timeout = number(execution.get("timeout_seconds"), "execution timeout")
    total = number(execution.get("max_total_seconds"), "execution budget")
    threads = execution.get("threads", 8)
    if type(threads) is not int or not 1 <= threads <= 64 or total < timeout:
        raise ValueError("Invalid threads or execution budget")
    views = audit.get("views")
    if not isinstance(views, list) or not views:
        raise ValueError("L2 audit requires frozen views")
    artifacts = set()
    for view in views:
        if not isinstance(view, dict) or set(view) != {"artifact", "camera", "resolution"}:
            raise ValueError("Invalid audit view")
        artifact = relative_path(view["artifact"])
        if artifact not in spec.required_artifacts or artifact in artifacts:
            raise ValueError("Invalid or duplicate view artifact")
        artifacts.add(artifact)
        if not isinstance(view["camera"], str) or not view["camera"]:
            raise ValueError("Missing camera")
        size = view["resolution"]
        if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or v <= 0 for v in size):
            raise ValueError("Invalid resolution")
    if artifacts != {n for n in spec.required_artifacts if n.endswith(".png")}:
        raise ValueError("Every required PNG needs an audit view")
    if set(config.output_files) != set(spec.required_artifacts):
        raise ValueError("Harness output_files must equal EvalSpec required_artifacts")
    roles = config.source.get('semantics', {}).get('roles', [])
    repairs = config.source.get('preview', {}).get('max_repairs', 1)
    if not isinstance(roles, list) or any(not isinstance(r, str) or not r for r in roles) or len(set(roles)) != len(roles):
        raise ValueError('Invalid public semantic roles')
    if type(repairs) is not int or not 0 <= repairs <= 3:
        raise ValueError('Invalid public preflight repair budget')
    parts = config.source.get('semantics', {}).get('parts', {})
    if (not isinstance(parts, dict) or any(role not in roles or not isinstance(values, list)
            or not values or any(not isinstance(v, str) or not v for v in values)
            or len(set(values)) != len(values) for role, values in parts.items())):
        raise ValueError('Invalid public entity parts')
    requirements, requirements_path = {}, None
    if config.source.get('requirements'):
        from src.evaluator.l2_requirements import load_requirements
        requirements_path = contained_path(path.parent, config.source['requirements']['path'])
        instruction = path.parent.parent / 'instruction.md'
        requirements = load_requirements(requirements_path, spec, task_id,
            instruction.read_text() if instruction.is_file() else None)
    return Policy(timeout, total, threads, tuple(views),
                  number(audit.get("max_mean_pixel_error"), "mean pixel error", 1),
                  number(audit.get("max_p99_pixel_error"), "p99 pixel error", 1),
                  config.digest, config.harness_version, config.environment_files,
                  config.output_files, timeout_steps(execution), tuple(roles), repairs,
                  Path(spec.baseline_scene).relative_to('environment').as_posix() if spec.baseline_scene else None,
                  {role: tuple(values) for role, values in parts.items()}, requirements, requirements_path, spec)
