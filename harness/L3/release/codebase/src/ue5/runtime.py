"""Local and Docker Unreal Engine runtime abstraction."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


class UE5Error(RuntimeError):
    """Raised when an Unreal project or runtime is unavailable."""


def _positive_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise UE5Error(f"{name} must be numeric, got {value!r}") from error
    if parsed <= 0:
        raise UE5Error(f"{name} must be greater than zero")
    return parsed


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise UE5Error(f"{name} must be an integer, got {value!r}") from error
    if parsed <= 0:
        raise UE5Error(f"{name} must be greater than zero")
    return parsed


def _env_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise UE5Error(f"{name} must be true or false, got {value!r}")


@dataclass(frozen=True)
class UE5Config:
    mode: str = "local"
    root: Path | None = None
    editor: Path | None = None
    runuat: Path | None = None
    docker_binary: str = "docker"
    docker_image: str = "ghcr.io/epicgames/unreal-engine:dev-5.8.0"
    docker_root: str = "/home/ue4/UnrealEngine"
    docker_engine_uid: int = 1000
    docker_engine_gid: int = 1000
    docker_gpu: bool = True
    timeout: float = 1800.0

    def __post_init__(self) -> None:
        if self.mode not in {"local", "docker"}:
            raise UE5Error("UE5_MODE must be local or docker")

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> UE5Config:
        selected = (env_file or DEFAULT_ENV_FILE).expanduser().resolve()
        load_dotenv(selected, override=True)
        raw_root = os.environ.get("UE5_ROOT", "").strip()
        root = Path(raw_root).expanduser().resolve() if raw_root else None
        raw_editor = os.environ.get("UE5_EDITOR", "").strip()
        raw_runuat = os.environ.get("UE5_RUNUAT", "").strip()
        editor = Path(raw_editor).expanduser().resolve() if raw_editor else None
        runuat = Path(raw_runuat).expanduser().resolve() if raw_runuat else None
        if root is not None:
            editor = editor or root / "Engine" / "Binaries" / "Linux" / "UnrealEditor"
            runuat = runuat or root / "Engine" / "Build" / "BatchFiles" / "RunUAT.sh"
        return cls(
            mode=os.environ.get("UE5_MODE", "local").strip().lower(),
            root=root,
            editor=editor,
            runuat=runuat,
            docker_binary=os.environ.get("UE5_DOCKER_BIN", "docker").strip()
            or "docker",
            docker_image=os.environ.get(
                "UE5_DOCKER_IMAGE", "ghcr.io/epicgames/unreal-engine:dev-5.8.0"
            ).strip(),
            docker_root=os.environ.get(
                "UE5_DOCKER_ROOT", "/home/ue4/UnrealEngine"
            ).strip(),
            docker_engine_uid=_positive_int(
                os.environ.get("UE5_DOCKER_ENGINE_UID", "1000"),
                "UE5_DOCKER_ENGINE_UID",
            ),
            docker_engine_gid=_positive_int(
                os.environ.get("UE5_DOCKER_ENGINE_GID", "1000"),
                "UE5_DOCKER_ENGINE_GID",
            ),
            docker_gpu=_env_bool(
                os.environ.get("UE5_DOCKER_GPU", "true"), "UE5_DOCKER_GPU"
            ),
            timeout=_positive_float(
                os.environ.get("UE5_TIMEOUT", "1800"), "UE5_TIMEOUT"
            ),
        )


def validate_project(path: Path) -> dict[str, Any]:
    project = path.expanduser().resolve()
    if project.is_dir():
        candidates = list(project.glob("*.uproject"))
        if len(candidates) != 1:
            raise UE5Error(
                f"Expected exactly one top-level .uproject in {project}; "
                f"found {len(candidates)}"
            )
        project = candidates[0]
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise UE5Error(f"Unreal project does not exist: {project}")
    try:
        descriptor = json.loads(project.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UE5Error(f"Invalid .uproject JSON: {error}") from error
    root = project.parent
    source_files = (
        list((root / "Source").rglob("*.cpp"))
        if (root / "Source").is_dir()
        else []
    )
    config_files = (
        list((root / "Config").glob("*.ini"))
        if (root / "Config").is_dir()
        else []
    )
    errors: list[str] = []
    if not isinstance(descriptor.get("FileVersion"), int):
        errors.append("missing integer FileVersion")
    if not source_files and not (root / "Content").is_dir():
        errors.append("project has neither C++ Source nor Content")
    if not config_files:
        errors.append("project has no Config/*.ini")
    if errors:
        raise UE5Error("Invalid UE5 project structure: " + "; ".join(errors))
    forbidden = [
        name
        for name in ("Binaries", "DerivedDataCache", "Intermediate", "Saved")
        if (root / name).exists()
    ]
    return {
        "project_file": str(project),
        "engine_association": descriptor.get("EngineAssociation"),
        "modules": len(descriptor.get("Modules", [])),
        "cpp_files": len(source_files),
        "config_files": len(config_files),
        "forbidden_build_directories": forbidden,
        "structure_valid": True,
    }


def inspect_environment(config: UE5Config) -> dict[str, Any]:
    report: dict[str, Any] = {"mode": config.mode, "ready": False, "errors": []}
    errors: list[str] = report["errors"]
    if config.mode == "local":
        report.update(
            {
                "root": str(config.root) if config.root else None,
                "editor": str(config.editor) if config.editor else None,
                "runuat": str(config.runuat) if config.runuat else None,
            }
        )
        if config.root is None:
            errors.append("UE5_ROOT is not configured")
        if config.editor is None or not config.editor.is_file():
            errors.append("UnrealEditor executable is missing")
        if config.runuat is None or not config.runuat.is_file():
            errors.append("RunUAT.sh is missing")
    else:
        docker = shutil.which(config.docker_binary)
        report.update(
            {
                "docker_binary": docker,
                "docker_image": config.docker_image,
                "docker_root": config.docker_root,
                "docker_engine_uid": config.docker_engine_uid,
                "docker_engine_gid": config.docker_engine_gid,
                "gpu": config.docker_gpu,
            }
        )
        if docker is None:
            errors.append(f"Docker executable not found: {config.docker_binary}")
        else:
            try:
                completed = subprocess.run(
                    [docker, "image", "inspect", config.docker_image],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                errors.append("Docker image inspection timed out after 30 seconds")
                report["ready"] = False
                return report
            if completed.returncode != 0:
                diagnostic = completed.stderr.strip().splitlines()[-1:]
                detail = diagnostic[0] if diagnostic else ""
                if "permission denied" in detail and "docker.sock" in detail:
                    errors.append(
                        "Docker daemon access denied; if the user is already in "
                        "the docker group, enter a `newgrp docker` shell and rerun"
                    )
                else:
                    errors.append(
                        "UE5 Docker image is unavailable"
                        + (f": {detail}" if detail else "")
                    )
    report["ready"] = not errors
    return report


def _docker_prefix(
    config: UE5Config, project_root: Path, output_dir: Path
) -> list[str]:
    command = [
        config.docker_binary,
        "run",
        "--rm",
        "--init",
        "--user",
        f"{config.docker_engine_uid}:{os.getgid()}",
        "--group-add",
        str(config.docker_engine_gid),
    ]
    if config.docker_gpu:
        command.extend(("--gpus", "all"))
    command.extend(
        (
            "--mount",
            f"type=bind,src={project_root},dst=/project",
            "--mount",
            f"type=bind,src={output_dir},dst=/output",
            config.docker_image,
        )
    )
    return command


def prepare_docker_mount(path: Path) -> None:
    """Grant the active ``newgrp docker`` group write access to one bind mount."""

    root = path.expanduser().resolve()
    if not root.is_dir():
        raise UE5Error(f"Docker bind mount is not a directory: {root}")
    group_id = os.getgid()
    for current_root, directories, files in os.walk(root, followlinks=False):
        current = Path(current_root)
        entries = [current, *(current / name for name in directories), *(current / name for name in files)]
        for entry in entries:
            if entry.is_symlink():
                raise UE5Error(f"Docker bind mount contains a symlink: {entry}")
            metadata = entry.stat()
            # Files produced by the container are owned by the configured ue4
            # UID but already use the active docker GID. They remain writable
            # by the next container invocation and need no host-side chmod.
            if metadata.st_uid != os.getuid():
                if metadata.st_gid != group_id:
                    raise UE5Error(
                        "Docker bind mount entry is owned by an unexpected "
                        f"identity: {entry} ({metadata.st_uid}:{metadata.st_gid})"
                    )
                continue
            os.chown(entry, -1, group_id)
            mode = stat.S_IMODE(metadata.st_mode)
            if entry.is_dir():
                entry.chmod(mode | stat.S_IRWXG | stat.S_ISGID)
            else:
                entry.chmod(mode | stat.S_IRGRP | stat.S_IWGRP)


def build_smoke_command(
    config: UE5Config, project_file: Path, output_dir: Path,
    *, max_parallel_actions: int | None = None, disable_uba: bool = False,
) -> list[str]:
    build_options: list[str] = []
    if max_parallel_actions is not None:
        if type(max_parallel_actions) is not int or max_parallel_actions < 1:
            raise UE5Error("max_parallel_actions must be a positive integer")
        build_options.append(f"-MaxParallelActions={max_parallel_actions}")
    if disable_uba:
        build_options.append("-NoUBA")
    project_file = project_file.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    target = f"{project_file.stem}Editor"
    if config.mode == "local":
        assert config.editor is not None
        assert config.runuat is not None
        build_script = config.runuat.parent / "Linux" / "Build.sh"
        editor_command = config.editor.with_name("UnrealEditor-Cmd")
        build = [
            str(build_script),
            target,
            "Linux",
            "Development",
            str(project_file),
            "-NoHotReload",
            "-WaitMutex",
            *build_options,
        ]
        commandlet = [
            str(editor_command),
            str(project_file),
            "-run=CompileAllBlueprints",
            "-ProjectOnly",
            "-unattended",
            "-nop4",
            "-NullRHI",
            "-nosplash",
            "-nosound",
            "-stdout",
            "-FullStdOutLogOutput",
            *([f"-corelimit={max_parallel_actions}"] if max_parallel_actions is not None else []),
        ]
        return [
            "/bin/bash",
            "-lc",
            "set -euo pipefail; "
            + shlex.join(build)
            + " && "
            + shlex.join(commandlet),
        ]
    container_project = Path("/project") / project_file.name
    build_script = (
        Path(config.docker_root) / "Engine/Build/BatchFiles/Linux/Build.sh"
    )
    editor = Path(config.docker_root) / "Engine/Binaries/Linux/UnrealEditor-Cmd"
    build = [
        str(build_script),
        target,
        "Linux",
        "Development",
        str(container_project),
        "-NoHotReload",
        "-WaitMutex",
        *build_options,
    ]
    commandlet = [
        str(editor),
        str(container_project),
        "-run=CompileAllBlueprints",
        "-ProjectOnly",
        "-unattended",
        "-nop4",
        "-NullRHI",
        "-nosplash",
        "-nosound",
        "-stdout",
        "-FullStdOutLogOutput",
        *([f"-corelimit={max_parallel_actions}"] if max_parallel_actions is not None else []),
    ]
    return [
        *_docker_prefix(config, project_file.parent, output_dir),
        "/bin/bash",
        "-lc",
        "set -euo pipefail; umask 0002; "
        + shlex.join(build)
        + " && "
        + shlex.join(commandlet),
    ]


def build_package_command(
    config: UE5Config, project_file: Path, output_dir: Path
) -> list[str]:
    project_file = project_file.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    arguments = [
        "BuildCookRun",
        f"-project={project_file}",
        "-noP4",
        "-platform=Linux",
        "-clientconfig=Development",
        "-build",
        "-cook",
        "-stage",
        "-pak",
        "-archive",
        f"-archivedirectory={output_dir}",
        "-utf8output",
    ]
    if config.mode == "local":
        assert config.runuat is not None
        return [str(config.runuat), *arguments]
    container_project = Path("/project") / project_file.name
    container_arguments = [
        value.replace(str(project_file), str(container_project)).replace(
            str(output_dir), "/output"
        )
        for value in arguments
    ]
    runuat = Path(config.docker_root) / "Engine/Build/BatchFiles/RunUAT.sh"
    return [
        *_docker_prefix(config, project_file.parent, output_dir),
        "/bin/bash",
        "-lc",
        "set -euo pipefail; umask 0002; "
        + shlex.join([str(runuat), *container_arguments]),
    ]


def run_command(command: list[str], timeout: float, cwd: Path) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        return {
            "status": "timeout",
            "returncode": 124,
            "elapsed_seconds": time.monotonic() - started,
            "stdout": error.stdout or "",
            "stderr": error.stderr or "",
        }
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "elapsed_seconds": time.monotonic() - started,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
