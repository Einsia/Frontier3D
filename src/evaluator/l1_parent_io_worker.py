"""Small stdlib-only worker for evaluator-owned path operations.

The evaluator must not perform an unbounded ``mkdir``/``mkdtemp`` in the
supervising process.  This worker deliberately has a tiny command surface and
returns only a bounded receipt; the supervisor owns the deadline and can kill
the whole process group when a filesystem operation blocks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path, PurePosixPath

PROTOCOL = "l1-parent-io-v1"


def _resolve_executable(requested: str, deadline: float) -> dict:
    """Observe a launcher in the worker; this does not pin its inode for exec."""
    if not requested or "\x00" in requested:
        raise ValueError("nonempty executable name without NUL required")
    if time.monotonic() >= deadline:
        raise TimeoutError("launcher resolution exhausted deadline")
    expanded = os.path.expanduser(requested)
    # Keep './tool' distinct from PATH lookup (Path('./tool') loses the './').
    selected = shutil.which(expanded) if "/" not in expanded else expanded
    if selected is None:
        raise FileNotFoundError("executable not found on PATH")
    canonical = Path(selected).resolve(strict=True)
    info = canonical.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("launcher must resolve to a regular file")
    if not os.access(canonical, os.X_OK):
        raise PermissionError("launcher is not executable")
    if time.monotonic() >= deadline:
        raise TimeoutError("launcher resolution exhausted deadline")
    return {
        "requested": requested, "path": str(canonical),
        "device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
        "bytes": info.st_size, "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns, "executable": True,
        "binding": "prelaunch_observation_not_exec_inode_pin",
    }


def _prepare_blender_sandbox(binary: str, runner: Path, workspace: Path, deadline: float) -> dict:
    if time.monotonic() >= deadline:
        raise TimeoutError("sandbox preparation exhausted deadline")
    selected = shutil.which("bwrap")
    if selected is None:
        return {"status": "declared_only", "reason": "bwrap_not_found", "prefix": []}
    launcher = _resolve_executable(selected, deadline)
    runtime_dir = Path(binary).resolve(strict=True).parent
    runner_path = runner.resolve(strict=True)
    if not stat.S_ISREG(runner_path.lstat().st_mode):
        raise ValueError("Blender runner must be a regular file")
    working = workspace.resolve(strict=True)
    workspace_info = _regular_directory(working)
    mounts = [Path(value) for value in ("/usr", "/bin", "/lib", "/lib64", "/etc")]
    mounts.append(runner_path.parent)
    prefix = [launcher["path"], "--die-with-parent", "--unshare-net"]
    actual_mounts = []
    for source in mounts:
        if time.monotonic() >= deadline:
            raise TimeoutError("sandbox mount preparation exhausted deadline")
        if source.exists():
            prefix += ["--ro-bind", str(source), str(source)]
            actual_mounts.append(str(source))
    prefix += [
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--ro-bind", str(runtime_dir), str(runtime_dir),
        "--bind", str(working), str(working), "--chdir", str(working),
        "--dir", "/tmp/home", "--setenv", "HOME", "/tmp/home", "--",
    ]
    if time.monotonic() >= deadline:
        raise TimeoutError("sandbox preparation exhausted deadline")
    return {"status": "prepared", "prefix": prefix, "launcher": launcher,
            "read_only_mounts": actual_mounts, "runtime_directory": str(runtime_dir),
            "runner": str(runner_path), "workspace": workspace_info,
            "binding": "prelaunch_mount_observation_not_isolation_proof"}


class BlenderUnavailable(OSError):
    """A failed Blender observation, distinct from resource/worker preparation."""


def _prepare_inspector(binary: str, runner: Path, roots: list[str], beauty: bool, deadline: float) -> dict:
    try:
        launcher = _resolve_executable(binary, deadline)
    except TimeoutError:
        raise
    except (OSError, ValueError, RuntimeError) as error:
        raise BlenderUnavailable(type(error).__name__) from error
    worker = runner.resolve(strict=True)
    if not stat.S_ISREG(worker.lstat().st_mode):
        raise ValueError("inspector worker must be a regular file")
    resolved_roots = []
    for value in roots:
        root = Path(value)
        _regular_directory(root)
        resolved = root.resolve(strict=True)
        if resolved == Path("/"):
            raise ValueError("overly broad material resource root")
        resolved_roots.append(str(resolved))
        if time.monotonic() >= deadline:
            raise TimeoutError("inspector resource preparation exhausted deadline")
    display = {"status": "not_required", "prefix": []}
    if beauty:
        selected = shutil.which("xvfb-run")
        if selected is None:
            display = {"status": "not_found", "prefix": []}
        else:
            xvfb = _resolve_executable(selected, deadline)
            display = {"status": "prepared", "launcher": xvfb,
                       "prefix": [xvfb["path"], "-a", "-s", "-screen 0 1280x1024x24"]}
    if time.monotonic() >= deadline:
        raise TimeoutError("inspector preparation exhausted deadline")
    return {"status": "prepared", "launcher": launcher, "runner": str(worker),
            "material_resource_roots": resolved_roots, "display": display,
            "binding": "prelaunch_observation_not_exec_inode_pin"}


def _receipt(value: dict) -> None:
    value = {"protocol": PROTOCOL, "pid": os.getpid(),
             "process_group": os.getpgrp(), **value}
    data = (json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n").encode()
    if len(data) > 4096:
        raise ValueError("oversized parent I/O receipt")
    os.write(1, data)


def _regular_directory(path: Path) -> dict:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("parent I/O target is not a non-symlink directory")
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


def _relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value or "\\" in value or path.is_absolute() or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("copy path must be a safe relative path")
    return path


def _copy_files(
    source_root: Path,
    destination_root: Path,
    files: list[str],
    target_files: list[str],
    limit: int,
) -> dict:
    if type(limit) is not int or limit <= 0:
        raise ValueError("positive copy byte limit required")
    source_info = _regular_directory(source_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    destination_info = _regular_directory(destination_root)
    if len(target_files) != len(files):
        raise ValueError("copy source and destination lists must have equal length")
    rows = []
    total = 0
    for value, destination_value in zip(files, target_files):
        relative = _relative(value)
        destination = _relative(destination_value)
        source = source_root.joinpath(*relative.parts)
        target = destination_root.joinpath(*destination.parts)
        source_stat = source.lstat()
        if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
            raise ValueError(f"copy source is not a regular file: {relative}")
        if total + source_stat.st_size > limit:
            raise ValueError("copy byte limit exceeded")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError(f"copy target is not a regular file: {relative}")
        temporary = None
        digest = hashlib.sha256()
        copied = 0
        try:
            with source.open("rb") as source_stream, tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=f".{target.name}.", suffix=".stage", delete=False
            ) as target_stream:
                temporary = Path(target_stream.name)
                while True:
                    chunk = source_stream.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if total + copied > limit:
                        raise ValueError("copy byte limit exceeded")
                    target_stream.write(chunk)
                    digest.update(chunk)
                target_stream.flush()
                os.fsync(target_stream.fileno())
            if copied != source_stat.st_size:
                raise ValueError("source changed during copy")
            os.replace(temporary, target)
            temporary = None
            directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            # Re-open the committed target without following a symlink and
            # bind the post-commit bytes to the receipt.  A later consumer can
            # reject a changed destination instead of trusting path existence.
            committed = target.lstat()
            if stat.S_ISLNK(committed.st_mode) or not stat.S_ISREG(committed.st_mode):
                raise ValueError("copy target changed to a non-regular entry")
            if committed.st_size != copied:
                raise ValueError("copy target size changed after commit")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        total += copied
        rows.append({
            "source": relative.as_posix(),
            "path": destination.as_posix(),
            "bytes": copied,
            "sha256": digest.hexdigest(),
        })
    return {"source": source_info, "destination": destination_info, "files": rows, "bytes": total}


def _audit_tree(
    root: Path,
    max_bytes: int,
    max_files: int,
    max_depth: int,
    max_file_bytes: int,
    deadline: float,
) -> dict:
    if any(type(value) is not int or value <= 0 for value in (max_bytes, max_files, max_depth, max_file_bytes)):
        raise ValueError("positive workspace limits required")
    root_info = _regular_directory(root)
    stack = [(root, 0)]
    files = directories = total = deepest = 0
    while stack:
        if time.monotonic() >= deadline:
            raise TimeoutError("workspace audit exhausted deadline")
        directory, depth = stack.pop()
        deepest = max(deepest, depth)
        with os.scandir(directory) as entries:
            for entry in entries:
                if time.monotonic() >= deadline:
                    raise TimeoutError("workspace audit exhausted deadline")
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise ValueError(f"workspace contains symlink: {entry.name}")
                if stat.S_ISDIR(info.st_mode):
                    child_depth = depth + 1
                    if child_depth > max_depth:
                        raise ValueError("workspace directory depth limit exceeded")
                    directories += 1
                    stack.append((Path(entry.path), child_depth))
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError(f"workspace contains nonregular entry: {entry.name}")
                files += 1
                if files > max_files or info.st_size > max_file_bytes:
                    raise ValueError("workspace file limit exceeded")
                total += info.st_size
                if total > max_bytes:
                    raise ValueError("workspace byte limit exceeded")
    return {
        "root": root_info,
        "bytes": total,
        "files": files,
        "directories": directories,
        "max_depth": deepest,
        "limits": {
            "max_bytes": max_bytes,
            "max_files": max_files,
            "max_depth": max_depth,
            "max_file_bytes": max_file_bytes,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--action",
        choices=("ensure_directory", "make_temp_directory", "copy_files", "audit_tree", "resolve_executable", "prepare_blender_sandbox", "prepare_inspector"),
        required=True,
    )
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--prefix", default="l1-")
    parser.add_argument("--parents", action="store_true")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--target-file", action="append", default=[])
    parser.add_argument("--max-bytes", type=int, default=0)
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--max-depth", type=int, default=0)
    parser.add_argument("--max-file-bytes", type=int, default=0)
    parser.add_argument("--deadline", type=float, default=float("inf"))
    parser.add_argument("--executable")
    parser.add_argument("--runner", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--resource-root", action="append", default=[])
    parser.add_argument("--beauty", action="store_true")
    args = parser.parse_args()
    entered = time.monotonic()
    _receipt({"phase": "started", "entered_monotonic": entered, "action": args.action})
    try:
        if args.action == "ensure_directory":
            args.path.mkdir(parents=args.parents, exist_ok=True)
            result = _regular_directory(args.path)
        elif args.action == "make_temp_directory":
            parent = _regular_directory(args.path)
            created = Path(tempfile.mkdtemp(prefix=args.prefix, dir=args.path))
            result = {"parent": parent, **_regular_directory(created), "created": True}
        else:
            if args.action == "prepare_inspector":
                result = _prepare_inspector(args.executable, args.runner, args.resource_root, args.beauty, args.deadline)
            elif args.action == "prepare_blender_sandbox":
                result = _prepare_blender_sandbox(args.executable, args.runner, args.workspace, args.deadline)
            elif args.action == "resolve_executable":
                result = _resolve_executable(args.executable, args.deadline)
            elif args.action == "audit_tree":
                result = _audit_tree(
                    args.path,
                    args.max_bytes,
                    args.max_files,
                    args.max_depth,
                    args.max_file_bytes,
                    args.deadline,
                )
            elif args.source_root is None or not args.file:
                raise ValueError("copy_files requires source-root and file paths")
            else:
                result = _copy_files(
                    args.source_root,
                    args.path,
                    args.file,
                    args.target_file or args.file,
                    args.max_bytes,
                )
        _receipt({"phase": "finished", "status": "completed",
                  "completed_monotonic": time.monotonic(), "result": result})
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        _receipt({"phase": "finished", "status": "failed",
                  "completed_monotonic": time.monotonic(),
                  "error_type": type(error).__name__, "reason": str(error)[:256]})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
