"""Public L1 submission manifest validation and dependency staging."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from src.evaluator.l1_failures import InspectionFailure
from src.evaluator.l1_log_io import write_bounded_file
from src.evaluator.l1_parent_io import (
    copy_regular_files,
    ensure_directory,
    write_bounded_json,
)

from .attempt_log import sha256, write_json
from .entrypoint import ENTRYPOINT_PROTOCOL, entrypoint_mode, launcher_source

MANIFEST_NAME = "submission_manifest.json"
MANIFEST_SCHEMA_VERSION = 1
_MAX_FILE_BYTES = 64 * 1024 * 1024
_RESERVED_ROOTS = {
    MANIFEST_NAME, "run_manifest.json", "harness_record.json", "artifacts.json",
    "seed_runs", "source_snapshot", "reproduction", "evaluation", "configuration",
    "reconstruction_baseline", "resource_snapshots",
    "refinement_context", "refinement_manifest.json", "agent_state.json", "agent_rounds", "agent_work",
    "blender.stdout.log", "blender.stderr.log",
}


def _relative(value: Any, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field} must be a nonempty relative path")
    path = PurePosixPath(value)
    if (
        "\\" in value or ":" in value or any(ord(c) < 32 for c in value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{field} must be a safe relative path: {value!r}")
    return path


def _contained(root: Path, relative: PurePosixPath) -> Path:
    path = (root / Path(*relative.parts)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"Submission path escapes source root: {relative}") from error
    return path


def _validate_regular(root: Path, relative: PurePosixPath, *, allow_empty: bool = False) -> Path:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Submission file is missing or symlinked: {relative}")
    path = _contained(root, relative)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Submission file is missing or symlinked: {relative}")
    if path.stat().st_size <= 0 and not allow_empty:
        raise ValueError(f"Submission file is empty: {relative}")
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError(f"Submission file exceeds {_MAX_FILE_BYTES} bytes: {relative}")
    return path


def _load_manifest(root: Path) -> tuple[dict[str, Any], str]:
    path = root / MANIFEST_NAME
    if not path.exists():
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "entrypoint": "solution.py",
            "files": ["solution.py"],
            "source": "legacy_single_file",
        }, "implicit_legacy"
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Invalid {MANIFEST_NAME}: must be a regular file")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid {MANIFEST_NAME}: {error}") from error
    if not isinstance(raw, dict):
        raise TypeError(f"{MANIFEST_NAME} must contain an object")
    allowed = {
        "schema_version",
        "entrypoint",
        "files",
        "description",
        "runtime",
        "dependencies",
        "run_instructions",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unknown {MANIFEST_NAME} fields: {sorted(unknown)}")
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"Unsupported {MANIFEST_NAME} schema_version")
    entrypoint = _relative(raw.get("entrypoint"), "entrypoint")
    if entrypoint.suffix.lower() != ".py":
        raise ValueError("submission entrypoint must be a Python file")
    files = raw.get("files")
    if (
        not isinstance(files, list)
        or not files
        or not all(isinstance(v, str) for v in files)
    ):
        raise ValueError("submission files must be a nonempty string list")
    paths = [_relative(value, "files item") for value in files]
    if len(set(paths)) != len(paths):
        raise ValueError("submission files contains duplicate paths")
    if entrypoint not in paths:
        raise ValueError("submission files must include entrypoint")
    if "description" in raw and not isinstance(raw["description"], str):
        raise TypeError("submission description must be a string")
    runtime = raw.get("runtime")
    if runtime is not None and (
        not isinstance(runtime, str) or not runtime.strip() or len(runtime) > 256
    ):
        raise TypeError("submission runtime must be a short string")
    dependencies = raw.get("dependencies", [])
    if (
        not isinstance(dependencies, list)
        or any(not isinstance(value, str) or not value.strip() for value in dependencies)
    ):
        raise TypeError("submission dependencies must be a string list")
    run_instructions = raw.get("run_instructions")
    if run_instructions is not None and (
        not isinstance(run_instructions, str) or len(run_instructions) > 8192
    ):
        raise TypeError("submission run_instructions must be a bounded string")
    normalized = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "entrypoint": entrypoint.as_posix(),
        "files": [path.as_posix() for path in paths],
    }
    if "description" in raw:
        normalized["description"] = raw["description"]
    if runtime is not None:
        normalized["runtime"] = runtime.strip()
    normalized["dependencies"] = list(dict.fromkeys(dependencies))
    if run_instructions is not None:
        normalized["run_instructions"] = run_instructions
    return normalized, "explicit"


def validate_submission(
    root: Path,
    *,
    reserved_outputs: tuple[str, ...] = (),
    explicit_entrypoint: str | None = None,
    entrypoint_policy: str = "declared_python",
) -> dict[str, Any]:
    """Validate a source directory and return hash-bound file metadata.

    ``reserved_outputs`` are evaluator-produced artifacts (for example
    ``scene.blend`` and ``scene.glb``) which candidates may not pre-supply.
    ``input/`` is also reserved because task staging owns that namespace.
    """
    root = root.expanduser().resolve()
    if entrypoint_policy not in {"declared_python", "fixed_solution"}:
        raise ValueError("Unknown entrypoint policy")
    if not root.is_dir():
        raise ValueError(f"Submission source must be a directory: {root}")
    if explicit_entrypoint is not None:
        entrypoint = _relative(explicit_entrypoint, "entrypoint")
        if entrypoint.suffix.lower() != ".py":
            raise ValueError("submission entrypoint must be a Python file")
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "entrypoint": entrypoint.as_posix(),
            "files": [entrypoint.as_posix()],
            "source": "explicit_file_argument",
        }
        source = "implicit_legacy"
    else:
        manifest, source = _load_manifest(root)
    entrypoint = _relative(manifest["entrypoint"], "entrypoint")
    if entrypoint_policy == "fixed_solution" and entrypoint.as_posix() != "solution.py":
        raise ValueError("This task requires solution.py as the entrypoint")
    files = [_relative(value, "files item") for value in manifest["files"]]
    if PurePosixPath("solution.py") in files and entrypoint.as_posix() != "solution.py":
        raise ValueError("solution.py may only be the declared submission entrypoint")
    reserved = {
        PurePosixPath(value)
        for value in reserved_outputs
        if PurePosixPath(value) != PurePosixPath("solution.py")
    }
    for relative in files:
        if relative.parts[0] in _RESERVED_ROOTS or relative.parts[0].startswith("attempt-"):
            raise ValueError(f"submission file conflicts with harness metadata: {relative}")
        if relative.parts[0] == "input":
            raise ValueError("submission dependencies may not overwrite task input/")
        if any(relative == path or path in relative.parents or relative in path.parents for path in reserved):
            raise ValueError(
                f"submission file conflicts with evaluator output: {relative}"
            )
    hashes = {}
    for relative in files:
        path = _validate_regular(root, relative, allow_empty=relative != entrypoint)
        hashes[relative.as_posix()] = {
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
    return {
        "manifest_name": MANIFEST_NAME if source == "explicit" else None,
        "manifest_source": source,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "entrypoint": entrypoint.as_posix(),
        "canonical_entrypoint": "solution.py",
        "files": hashes,
        "description": manifest.get("description"),
        "runtime": manifest.get("runtime"),
        "dependencies": list(manifest.get("dependencies", [])),
        "run_instructions": manifest.get("run_instructions"),
        "entrypoint_policy": entrypoint_policy,
        "entrypoint_protocol": ENTRYPOINT_PROTOCOL,
        "entrypoint_mode": entrypoint_mode(entrypoint.as_posix()),
    }


def stage_submission(
    source: Path,
    destination: Path,
    *,
    reserved_outputs: tuple[str, ...] = (),
    entrypoint_policy: str = "declared_python",
    deadline: float | None = None,
) -> dict[str, Any]:
    """Validate and copy a public submission into an isolated workspace."""
    source = source.expanduser().resolve()
    if source.is_file():
        metadata = validate_submission(
            source.parent,
            reserved_outputs=reserved_outputs,
            explicit_entrypoint=source.name,
            entrypoint_policy=entrypoint_policy,
        )
    else:
        metadata = validate_submission(
            source,
            reserved_outputs=reserved_outputs,
            entrypoint_policy=entrypoint_policy,
        )
    destination = destination.expanduser().resolve()
    source_root = source.parent if source.is_file() else source
    path_io = []

    def require_completed(receipt: dict[str, Any], operation: str) -> dict[str, Any]:
        if receipt.get("status") != "completed":
            code = receipt.get("failure_code", "PARENT_IO_FAILED")
            raise InspectionFailure("infrastructure_error", code, operation)
        return receipt

    if deadline is None:
        destination.mkdir(parents=True, exist_ok=True)
        for relative in metadata["files"]:
            source_path = _contained(source_root, PurePosixPath(relative))
            target = destination.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil_copy(source_path, target)
        staged_files = {
            relative: sha256(destination.joinpath(*PurePosixPath(relative).parts))
            for relative in metadata["files"]
        }
    else:
        directory_receipt = ensure_directory(destination, deadline=deadline, parents=True)
        path_io.append(directory_receipt["execution"])
        copy_files = tuple(metadata["files"])
        if metadata["manifest_source"] == "explicit":
            copy_files += (MANIFEST_NAME,)
        copy_receipt = copy_regular_files(
            source_root,
            destination,
            copy_files,
            deadline=deadline,
        )
        path_io.append(copy_receipt["execution"])
        staged_files = {
            row["path"]: row["sha256"]
            for row in copy_receipt["result"]["files"]
            if row["path"] in metadata["files"]
        }
    entrypoint = PurePosixPath(metadata["entrypoint"])
    canonical = destination / "solution.py"
    if entrypoint.as_posix() != "solution.py":
        launcher = launcher_source(entrypoint.as_posix())
        if deadline is None:
            canonical.write_text(launcher, encoding="utf-8")
        else:
            launcher_receipt = require_completed(write_bounded_file(
                canonical,
                launcher,
                deadline=deadline,
                replace=False,
            ), "canonical launcher write")
            path_io.append(launcher_receipt)
    manifest_path = source_root / MANIFEST_NAME
    if metadata["manifest_source"] == "explicit":
        if deadline is None:
            shutil_copy(manifest_path, destination / MANIFEST_NAME)
    elif entrypoint.as_posix() != "solution.py":
        # A single explicitly selected noncanonical file still needs its
        # declaration when this frozen directory is staged again later.
        manifest_value = {
            "schema_version": 1,
            "entrypoint": entrypoint.as_posix(),
            "files": list(metadata["files"]),
        }
        if deadline is None:
            write_json(destination / MANIFEST_NAME, manifest_value)
        else:
            manifest_receipt = write_bounded_json(
                destination / MANIFEST_NAME, manifest_value, deadline=deadline
            )["execution"]
            path_io.append(require_completed(manifest_receipt, "implicit manifest write"))
    metadata["staged_files"] = staged_files
    metadata["canonical_sha256"] = sha256(canonical)
    if path_io:
        metadata["path_io"] = path_io
    return metadata


def shutil_copy(source: Path, destination: Path) -> None:
    """Copy bytes without following a source symlink after validation."""
    destination.write_bytes(source.read_bytes())


__all__ = ["MANIFEST_NAME", "stage_submission", "validate_submission"]
