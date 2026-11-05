"""Adapter for the versioned task bundles under ``data/3dbench/task``."""

from __future__ import annotations

import json
import mimetypes
import shutil
import tempfile
from dataclasses import dataclass
from filecmp import cmp
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import tomllib

from .client import PROJECT_ROOT, GeneratorError, write_script

if TYPE_CHECKING:
    from .client import BpyScriptGenerator

DEFAULT_TASKS_ROOT = PROJECT_ROOT / "data" / "3dbench" / "task"
DEFAULT_TASK_RUNS_DIR = PROJECT_ROOT / "data" / "task_runs"
_LFS_HEADER = b"version https://git-lfs.github.com/spec/v1"


def _safe_relative_path(value: str, field_name: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise GeneratorError(f"{field_name} must be a safe relative path: {value!r}")
    return path


def _required_string(data: dict[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise GeneratorError(f"task.toml field {name!r} must be a non-empty string")
    return value.strip()


def _is_lfs_pointer(path: Path) -> bool:
    with path.open("rb") as asset_file:
        return asset_file.read(len(_LFS_HEADER)) == _LFS_HEADER


@dataclass(frozen=True)
class BenchmarkTask:
    """Validated, model-visible portion of one 3DBench task bundle."""

    root: Path
    task_id: str
    level: int
    title: str
    instruction_path: Path
    environment_dir: Path
    environment_files: tuple[PurePosixPath, ...]
    reference_kind: str

    @property
    def instruction(self) -> str:
        return self.instruction_path.read_text(encoding="utf-8")

    @property
    def image_files(self) -> tuple[PurePosixPath, ...]:
        images: list[PurePosixPath] = []
        for relative_path in self.environment_files:
            media_type, _ = mimetypes.guess_type(relative_path.name)
            if media_type is not None and media_type.startswith("image/"):
                images.append(relative_path)
        return tuple(images)

    @property
    def output_slug(self) -> str:
        return "__".join(self.task_id.split("/"))

    def require_blender_backend(self) -> None:
        if self.level not in {1, 2}:
            raise GeneratorError(
                f"Task {self.task_id} requires a UE5 project/runtime, but the "
                "current generator and renderer only support Blender bpy tasks "
                "from Level 1 and Level 2"
            )

    def validate_materialized_assets(self) -> None:
        pointers = [
            relative_path.as_posix()
            for relative_path in self.environment_files
            if _is_lfs_pointer(self.environment_dir / relative_path)
        ]
        if pointers:
            names = ", ".join(pointers)
            raise GeneratorError(
                f"Task {self.task_id} contains Git LFS pointer files instead of "
                f"materialized assets: {names}. Install Git LFS and run "
                f"`git -C {self.root.parents[2]} lfs pull` before generation."
            )

    def stage_environment(
        self,
        workspace: Path,
        *,
        overwrite: bool = False,
    ) -> tuple[Path, ...]:
        """Copy only the manifest allowlist, preserving ``input/...`` paths."""

        workspace = workspace.expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        staged: list[Path] = []
        for relative_path in self.environment_files:
            from .public_inputs import require_public_input
            try:
                require_public_input(relative_path)
            except ValueError as error:
                raise GeneratorError(str(error)) from error
            source = self.environment_dir / relative_path
            destination = workspace.joinpath(*relative_path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.is_file() and cmp(source, destination, shallow=False):
                    staged.append(destination)
                    continue
                if not overwrite:
                    raise GeneratorError(
                        f"Submission input already exists with different content: "
                        f"{destination}; pass --overwrite to replace it"
                    )
            shutil.copy2(source, destination)
            staged.append(destination)
        return tuple(staged)


def load_benchmark_task(
    task: str | Path,
    tasks_root: Path = DEFAULT_TASKS_ROOT,
) -> BenchmarkTask:
    """Load a task by ``L1/Text2Code`` id or by task directory path."""

    tasks_root = tasks_root.expanduser().resolve()
    requested = Path(task).expanduser()
    if requested.is_absolute() or requested.exists():
        task_root = requested.resolve()
    else:
        task_id_path = _safe_relative_path(str(task), "task id")
        task_root = tasks_root.joinpath(*task_id_path.parts).resolve()
        try:
            task_root.relative_to(tasks_root)
        except ValueError as error:
            raise GeneratorError(f"Task escapes tasks root: {task}") from error

    manifest_path = task_root / "task.toml"
    if not manifest_path.is_file():
        raise GeneratorError(f"Task manifest does not exist: {manifest_path}")
    try:
        with manifest_path.open("rb") as manifest_file:
            manifest = tomllib.load(manifest_file)
    except tomllib.TOMLDecodeError as error:
        raise GeneratorError(
            f"Invalid task manifest {manifest_path}: {error}"
        ) from error

    if manifest.get("version") != 1:
        raise GeneratorError(
            f"Unsupported task manifest version in {manifest_path}: "
            f"{manifest.get('version')!r}"
        )
    task_id = _required_string(manifest, "id")
    level = manifest.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or level not in {1, 2, 3}:
        raise GeneratorError("task.toml field 'level' must be one of 1, 2, or 3")

    instruction_relative = _safe_relative_path(
        _required_string(manifest, "instruction"), "instruction"
    )
    environment_relative = _safe_relative_path(
        _required_string(manifest, "environment"), "environment"
    )
    instruction_path = task_root.joinpath(*instruction_relative.parts).resolve()
    environment_dir = task_root.joinpath(*environment_relative.parts).resolve()
    for path, name in (
        (instruction_path, "instruction"),
        (environment_dir, "environment"),
    ):
        try:
            path.relative_to(task_root)
        except ValueError as error:
            raise GeneratorError(
                f"Task {name} escapes task directory: {path}"
            ) from error
    if not instruction_path.is_file():
        raise GeneratorError(f"Task instruction does not exist: {instruction_path}")
    if not environment_dir.is_dir():
        raise GeneratorError(f"Task environment does not exist: {environment_dir}")

    raw_environment_files = manifest.get("environment_files")
    if not isinstance(raw_environment_files, list) or not all(
        isinstance(value, str) for value in raw_environment_files
    ):
        raise GeneratorError(
            "task.toml field 'environment_files' must be a string list"
        )
    environment_files = tuple(
        _safe_relative_path(value, "environment_files item")
        for value in raw_environment_files
    )
    if len(set(environment_files)) != len(environment_files):
        raise GeneratorError("task.toml environment_files contains duplicate paths")
    for relative_path in environment_files:
        from .public_inputs import require_public_input
        try:
            require_public_input(relative_path)
        except ValueError as error:
            raise GeneratorError(str(error)) from error
        asset = environment_dir.joinpath(*relative_path.parts).resolve()
        try:
            asset.relative_to(environment_dir)
        except ValueError as error:
            raise GeneratorError(
                f"Environment asset escapes task directory: {asset}"
            ) from error
        if not asset.is_file():
            raise GeneratorError(f"Declared environment asset does not exist: {asset}")

    return BenchmarkTask(
        root=task_root,
        task_id=task_id,
        level=level,
        title=_required_string(manifest, "title"),
        instruction_path=instruction_path,
        environment_dir=environment_dir,
        environment_files=environment_files,
        reference_kind=_required_string(manifest, "reference_kind"),
    )


def default_task_run_dir(task: BenchmarkTask) -> Path:
    return DEFAULT_TASK_RUNS_DIR / task.output_slug


def generate_task_submission(
    generator: BpyScriptGenerator,
    task: BenchmarkTask,
    output_dir: Path,
    overwrite: bool = False,
) -> Path:
    """Stage safe inputs, generate ``solution.py``, and create a run workspace."""

    task.require_blender_backend()
    task.validate_materialized_assets()
    output_dir = output_dir.expanduser().resolve()
    script_path = output_dir / "solution.py"
    run_manifest_path = output_dir / "task_run.json"
    if (script_path.exists() or run_manifest_path.exists()) and not overwrite:
        raise GeneratorError(
            f"Submission already exists in {output_dir}; pass --overwrite to replace it"
        )

    with tempfile.TemporaryDirectory(prefix="3dbench-task-input-") as temp_name:
        model_workspace = Path(temp_name)
        task.stage_environment(model_workspace)
        staged_images = tuple(
            model_workspace.joinpath(*relative_path.parts)
            for relative_path in task.image_files
        )
        source = generator.from_benchmark_task(
            instruction=task.instruction,
            environment_files=tuple(
                relative_path.as_posix() for relative_path in task.environment_files
            ),
            image_paths=staged_images,
            working_directory=model_workspace,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    task.stage_environment(output_dir, overwrite=overwrite)
    write_script(source, script_path, overwrite=overwrite)
    run_manifest = {
        "schema_version": 1,
        "task_id": task.task_id,
        "level": task.level,
        "source_task": str(task.root),
        "instruction": task.instruction_path.name,
        "environment_files": [
            relative_path.as_posix() for relative_path in task.environment_files
        ],
        "solution_script": script_path.name,
        "scene_output": "scene.blend",
        "generation": {
            "model": generator.config.model,
            "reasoning_effort": generator.config.reasoning_effort,
            "runtime": generator.config.runtime,
        },
    }
    run_manifest_path.write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return script_path
