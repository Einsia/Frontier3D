"""Strict TOML configuration for the first-stage L1 harness."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import tomllib


def _positive_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a positive number")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return value


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _boolean(table: dict, name: str, default: bool) -> bool:
    value = table.get(name, default)
    if type(value) is not bool:
        raise TypeError(f"{name} must be boolean")
    return value


def _paths(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list of safe relative paths")
    for item in value:
        if (not isinstance(item, str) or not item or "\\" in item or ":" in item
            or any(part in {"", ".", ".."} for part in item.split("/"))
            or PurePosixPath(item).is_absolute() or any(ord(c) < 32 for c in item)):
            raise ValueError(f"{name} contains an unsafe relative path")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} contains duplicate paths")
    return tuple(value)


@dataclass(frozen=True)
class RetryPolicy:
    retry_timeout: bool = False
    retry_transport_error: bool = True
    retry_empty_output: bool = False
    retry_protocol_error: bool = False
    max_retries: int = 1
    backoff_seconds: tuple[float, ...] = (2.0,)


@dataclass(frozen=True)
class HarnessConfig:
    schema_version: int
    harness_version: str
    task_id: str
    level: int
    command: str
    runtime: str
    model_env: str
    reasoning_effort: str | None
    timeout_seconds: float
    max_attempts: int
    max_total_seconds: float
    environment_files: tuple[str, ...]
    output_files: tuple[str, ...]
    entrypoint_policy: str
    working_directory_mode: str
    network: bool
    save_stdout: bool
    save_stderr: bool
    save_prompt_hash: bool
    save_input_hashes: bool
    save_output_hash: bool
    retry: RetryPolicy
    source: dict[str, Any]
    source_path: str = ""
    file_sha256: str = ""

    @property
    def digest(self) -> str:
        payload = json.dumps(self.source, sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(payload).hexdigest()

    def effective(self) -> dict[str, Any]:
        """All parsed/defaulted policy values; excludes provenance and raw TOML."""
        values = asdict(self)
        for name in ("source", "source_path", "file_sha256"):
            values.pop(name)
        return json.loads(json.dumps(values, allow_nan=False))

    @property
    def effective_digest(self) -> str:
        return hashlib.sha256(json.dumps(self.effective(), sort_keys=True, allow_nan=False).encode()).hexdigest()


def load_config(path: Path) -> HarnessConfig:
    content = path.read_bytes()
    return parse_config(content, source_path=path)


def parse_config(content: bytes, *, source_path: Path | None = None) -> HarnessConfig:
    """Parse the exact bytes hashed in the provenance record (no second read)."""
    raw = tomllib.loads(content.decode("utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("harness.toml must contain an object")
    allowed = {
        "schema_version",
        "harness_version",
        "task_id",
        "level",
        "generator",
        "retry_policy",
        "workspace",
        "recording",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unknown harness fields: {sorted(unknown)}")
    generator = raw.get("generator", {})
    retry = raw.get("retry_policy", {})
    workspace = raw.get("workspace", {})
    recording = raw.get("recording", {})
    if not all(
        isinstance(value, dict) for value in (generator, retry, workspace, recording)
    ):
        raise ValueError("harness sections must be tables")
    section_fields = {
        "generator": {"command", "runtime", "model_env", "reasoning_effort", "timeout_seconds", "max_attempts", "max_total_seconds"},
        "retry_policy": {"retry_timeout", "retry_transport_error", "retry_empty_output", "retry_protocol_error", "max_retries", "backoff_seconds"},
        "workspace": {"environment_files", "output_files", "entrypoint_policy", "working_directory_mode", "network"},
        "recording": {"save_stdout", "save_stderr", "save_prompt_hash", "save_input_hashes", "save_output_hash"},
    }
    for section, fields in section_fields.items():
        unknown = set(raw.get(section, {})) - fields
        if unknown:
            raise ValueError(f"Unknown {section} fields: {sorted(unknown)}")
    schema_version = raw.get("schema_version", 1)
    if type(schema_version) is not int or schema_version != 1:
        raise ValueError("Unsupported harness schema_version")
    task_id = raw.get("task_id")
    if not isinstance(task_id, str) or not re.fullmatch(r"L1/[A-Za-z0-9_-]+", task_id):
        raise ValueError("task_id must identify an L1 task")
    level = raw.get("level", 1)
    if type(level) is not int or level != 1:
        raise ValueError("L1 harness requires level=1")
    command = generator.get("command", "src.generator")
    runtime = generator.get("runtime", "local")
    if command != "src.generator" or runtime not in {"local", "docker"}:
        raise ValueError("Only src.generator with local or docker runtime is supported")
    model_env = generator.get("model_env", "OPENAI_MODEL")
    if model_env != "OPENAI_MODEL":
        raise ValueError("model_env must be OPENAI_MODEL; custom model environment names are unsupported")
    effort = generator.get("reasoning_effort")
    if effort is not None and effort not in {
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }:
        raise ValueError("Invalid reasoning_effort")
    timeout = _positive_float(generator.get("timeout_seconds", 300), "timeout_seconds")
    max_attempts = _positive_int(generator.get("max_attempts", 1), "max_attempts")
    if max_attempts != 1:
        raise ValueError("generator.max_attempts must be 1; retries belong to retry_policy.max_retries")
    total = _positive_float(
        generator.get("max_total_seconds", timeout), "max_total_seconds"
    )
    retry_count = retry.get("max_retries", 1)
    if type(retry_count) is not int or retry_count < 0:
        raise ValueError("max_retries must be a nonnegative integer")
    backoff = retry.get("backoff_seconds", [2])
    if not isinstance(backoff, list) or any(isinstance(v, bool) for v in backoff):
        raise ValueError("backoff_seconds must be a list")
    backoff_values = tuple(_positive_float(v, "backoff_seconds") for v in backoff) or (
        0.0,
    )
    files = _paths(workspace.get("environment_files", []), "environment_files")
    outputs = _paths(workspace.get("output_files", ["solution.py"]), "output_files")
    if not outputs:
        raise ValueError("output_files must not be empty")
    entrypoint_policy = workspace.get("entrypoint_policy", "declared_python")
    if entrypoint_policy not in {"declared_python", "fixed_solution"}:
        raise ValueError(
            "entrypoint_policy must be declared_python or fixed_solution"
        )
    mode = workspace.get("working_directory_mode", "staged_readonly")
    if mode != "staged_readonly":
        raise ValueError("Only staged_readonly working_directory_mode is supported")
    network = workspace.get("network", False)
    if type(network) is not bool:
        raise ValueError("network must be boolean")
    version = raw.get("harness_version", "l1-harness-v0.1.0")
    if not isinstance(version, str) or not re.fullmatch(r"l1-harness-v\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise ValueError("harness_version must be a versioned l1-harness identifier")
    # Integrity hashes are mandatory, not optional recording cosmetics. Refuse
    # unsupported disabling rather than recording false while still hashing.
    for name in ("save_input_hashes", "save_output_hash"):
        if not _boolean(recording, name, True):
            raise ValueError(f"recording.{name} must be true for L1 provenance")
    source = json.loads(json.dumps(raw, ensure_ascii=False))
    return HarnessConfig(
        schema_version=schema_version,
        harness_version=version,
        task_id=task_id,
        level=level,
        command=command,
        runtime=runtime,
        model_env=model_env,
        reasoning_effort=effort,
        timeout_seconds=timeout,
        max_attempts=max_attempts,
        max_total_seconds=total,
        environment_files=tuple(files),
        output_files=tuple(outputs),
        entrypoint_policy=entrypoint_policy,
        working_directory_mode=mode,
        network=network,
        save_stdout=_boolean(recording, "save_stdout", True),
        save_stderr=_boolean(recording, "save_stderr", True),
        save_prompt_hash=_boolean(recording, "save_prompt_hash", True),
        save_input_hashes=_boolean(recording, "save_input_hashes", True),
        save_output_hash=_boolean(recording, "save_output_hash", True),
        retry=RetryPolicy(
            retry_timeout=_boolean(retry, "retry_timeout", False),
            retry_transport_error=_boolean(retry, "retry_transport_error", True),
            retry_empty_output=_boolean(retry, "retry_empty_output", False),
            retry_protocol_error=_boolean(retry, "retry_protocol_error", False),
            max_retries=retry_count,
            backoff_seconds=backoff_values,
        ),
        source=source,
        source_path=str(source_path.expanduser().resolve()) if source_path is not None else "",
        file_sha256=hashlib.sha256(content).hexdigest(),
    )
