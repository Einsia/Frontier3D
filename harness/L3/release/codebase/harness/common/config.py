"""Strict, level-aware TOML configuration."""
from __future__ import annotations
import hashlib, json, math, tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

def _num(value: Any, name: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or (value < 0 if nonnegative else value <= 0):
        raise ValueError(f"{name} must be {'nonnegative' if nonnegative else 'positive'} finite number")
    return float(value)

def _path_list(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v or Path(v).is_absolute() or ".." in Path(v).parts for v in value):
        raise ValueError(f"{name} must contain safe relative paths")
    return tuple(value)

@dataclass(frozen=True)
class HarnessConfig:
    schema_version: int; harness_version: str; task_id: str; level: int
    command: str; runtime: str; model_env: str; reasoning_effort: str | None
    timeout_seconds: float; max_total_seconds: float; max_retries: int
    retry_timeout: bool; retry_transport_error: bool; retry_empty_output: bool; retry_protocol_error: bool
    backoff_seconds: tuple[float, ...]; environment_files: tuple[str, ...]; output_files: tuple[str, ...]
    network: bool; source: dict[str, Any]
    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def load_config(path: Path, *, level: int, task_prefix: str) -> HarnessConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict): raise ValueError("harness.toml must contain a table")
    if raw.get("schema_version", 1) != 1: raise ValueError("unsupported harness schema_version")
    task_id = raw.get("task_id")
    if not isinstance(task_id, str) or not task_id.startswith(task_prefix): raise ValueError(f"task_id must start with {task_prefix}")
    if raw.get("level") != level: raise ValueError(f"harness requires level={level}")
    generator, retry, workspace = raw.get("generator", {}), raw.get("retry_policy", {}), raw.get("workspace", {})
    if not all(isinstance(x, dict) for x in (generator, retry, workspace)): raise ValueError("generator/retry_policy/workspace must be tables")
    effort = generator.get("reasoning_effort")
    if effort is not None and effort not in {"minimal","low","medium","high","xhigh"}: raise ValueError("invalid reasoning_effort")
    timeout = _num(generator.get("timeout_seconds", 900), "timeout_seconds")
    total = _num(generator.get("max_total_seconds", timeout), "max_total_seconds")
    if total < timeout: raise ValueError("max_total_seconds must cover one attempt")
    max_retries = retry.get("max_retries", 0)
    if type(max_retries) is not int or max_retries < 0: raise ValueError("max_retries must be nonnegative integer")
    backoff = retry.get("backoff_seconds", [2])
    if not isinstance(backoff, list): raise ValueError("backoff_seconds must be a list")
    backoff_values = tuple(_num(v, "backoff_seconds", nonnegative=True) for v in backoff) or (0.0,)
    network = workspace.get("network", False)
    if type(network) is not bool: raise ValueError("network must be boolean")
    source = json.loads(json.dumps(raw, ensure_ascii=False))
    return HarnessConfig(1, str(raw.get("harness_version", f"level{level}-harness-v0.1.0")), task_id, level, str(generator.get("command", "src.generator")), str(generator.get("runtime", "local")), str(generator.get("model_env", "OPENAI_MODEL")), effort, timeout, total, max_retries, bool(retry.get("retry_timeout", True)), bool(retry.get("retry_transport_error", True)), bool(retry.get("retry_empty_output", False)), bool(retry.get("retry_protocol_error", False)), backoff_values, _path_list(workspace.get("environment_files", []), "environment_files"), _path_list(workspace.get("output_files", []), "output_files"), network, source)
