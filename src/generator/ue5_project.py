"""Generate a source-controlled Unreal Engine project for Level 3 tasks."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from .client import BpyScriptGenerator, GeneratorError
from .task_adapter import BenchmarkTask

UE5_SYSTEM_PROMPT = """\
You are an expert Unreal Engine 5 C++ gameplay engineer. Work only inside the
current isolated workspace. The task's declared public inputs are under
input/. Create the complete deliverable below project/. Do not access the
network or any path outside this workspace.

Create one editable Unreal Engine project that can be built on Linux. It must
contain exactly one .uproject plus Config/, Source/, a concise README.md, and
any text assets or plugins it actually needs. Prefer a self-contained C++
implementation that procedurally creates gameplay and geometry, so the project
does not depend on unavailable Marketplace content or opaque binary .uasset
files. Target Unreal Engine 5.8 and set EngineAssociation to "5.8". Use only
stock Unreal Engine modules. C++ targets must use
DefaultBuildSettings = BuildSettingsVersion.V7 and
IncludeOrderVersion = EngineIncludeOrderVersion.Latest. Supply both
<ProjectName>.Target.cs and <ProjectName>Editor.Target.cs so the conventional
<ProjectName>Editor target can be built. The default map/game mode must
launch into playable gameplay and implement the requested fixed-step,
interaction, state, save/load, and deterministic-seed behavior rather than
merely displaying a mock UI. Expose stable automation hooks or console
commands for evaluator-driven actions and state inspection where practical.

Do not create build products such as Binaries/, DerivedDataCache/,
Intermediate/, Saved/, packaged archives, or engine files. Do not embed the
reference image as a billboard. Do not return source files in the final
message: write them to project/ using your tools. When finished, return a
short plain-text inventory and any known build limitations.
"""


def _validate_generated_project(project_root: Path) -> Path:
    if not project_root.is_dir():
        raise GeneratorError("Codex did not create the required project/ directory")
    symlinks = [path for path in project_root.rglob("*") if path.is_symlink()]
    if symlinks:
        raise GeneratorError(
            "Generated UE5 project contains forbidden symlinks: "
            + ", ".join(str(path.relative_to(project_root)) for path in symlinks[:10])
        )
    project_files = list(project_root.glob("*.uproject"))
    if len(project_files) != 1:
        raise GeneratorError(
            "Generated UE5 project must contain exactly one top-level .uproject; "
            f"found {len(project_files)}"
        )
    required = (project_root / "Config", project_root / "Source")
    missing = [path.name for path in required if not path.is_dir()]
    if missing:
        raise GeneratorError(
            "Generated UE5 project is missing required directories: "
            + ", ".join(missing)
        )
    if not (project_root / "README.md").is_file():
        raise GeneratorError("Generated UE5 project is missing project/README.md")
    forbidden = [
        name
        for name in ("Binaries", "DerivedDataCache", "Intermediate", "Saved")
        if (project_root / name).exists()
    ]
    if forbidden:
        raise GeneratorError(
            "Generated UE5 project contains forbidden build directories: "
            + ", ".join(forbidden)
        )
    try:
        descriptor = json.loads(project_files[0].read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GeneratorError(f"Invalid .uproject JSON: {error}") from error
    if not isinstance(descriptor.get("FileVersion"), int):
        raise GeneratorError("Generated .uproject must contain an integer FileVersion")
    association = str(descriptor.get("EngineAssociation", ""))
    if not association.startswith("5.8"):
        raise GeneratorError(
            "Generated .uproject must target EngineAssociation 5.8; "
            f"got {association!r}"
        )
    source_files = tuple((project_root / "Source").rglob("*.cpp"))
    if not source_files:
        raise GeneratorError("Generated UE5 project contains no C++ implementation")
    return project_files[0]


def generate_ue5_task_submission(
    generator: BpyScriptGenerator,
    task: BenchmarkTask,
    output_dir: Path,
    overwrite: bool = False,
) -> Path:
    """Generate and stage one Level 3 UE5 source project."""

    if task.level != 3:
        raise GeneratorError(f"Task {task.task_id} is not a Level 3 UE5 task")
    task.validate_materialized_assets()
    output_dir = output_dir.expanduser().resolve()
    run_manifest_path = output_dir / "task_run.json"
    destination_project = output_dir / "project"
    if (run_manifest_path.exists() or destination_project.exists()) and not overwrite:
        raise GeneratorError(
            f"Submission already exists in {output_dir}; pass --overwrite to replace it"
        )

    with tempfile.TemporaryDirectory(prefix="3dbench-ue5-task-") as temp_name:
        workspace = Path(temp_name)
        task.stage_environment(workspace)
        project_root = workspace / "project"
        project_root.mkdir()
        images = tuple(
            workspace.joinpath(*relative_path.parts)
            for relative_path in task.image_files
        )
        file_listing = "\n".join(
            f"- {relative_path.as_posix()}" for relative_path in task.environment_files
        ) or "- (none)"
        prompt = (
            f"{UE5_SYSTEM_PROMPT.strip()}\n\n"
            f"Task id: {task.task_id}\n"
            f"Declared public files:\n{file_listing}\n\n"
            f"Task instruction:\n{task.instruction.strip()}\n"
        )
        transport_recovered = False
        try:
            final_message = generator.run_workspace_task(
                prompt,
                image_paths=images,
                working_directory=workspace,
            )
        except GeneratorError as transport_error:
            # Codex can finish writing the workspace before its response stream
            # disconnects. Preserve only artifacts that pass every structural
            # gate; compilation remains the authoritative compatibility check.
            try:
                _validate_generated_project(project_root)
            except GeneratorError:
                raise transport_error
            transport_recovered = True
            final_message = (
                "Codex transport failed after writing a structurally valid "
                "project; recovered the artifact for compile-time validation."
            )
        project_file = _validate_generated_project(project_root)

        output_dir.mkdir(parents=True, exist_ok=True)
        task.stage_environment(output_dir, overwrite=overwrite)
        if destination_project.exists():
            if not overwrite:
                raise GeneratorError(f"UE5 project already exists: {destination_project}")
            shutil.rmtree(destination_project)
        shutil.copytree(project_root, destination_project)

    copied_project = destination_project / project_file.name
    run_manifest = {
        "schema_version": 1,
        "task_id": task.task_id,
        "level": task.level,
        "backend": "ue5",
        "source_task": str(task.root),
        "instruction": task.instruction_path.name,
        "environment_files": [
            relative_path.as_posix() for relative_path in task.environment_files
        ],
        "project_file": str(copied_project.relative_to(output_dir)),
        "model_summary": final_message.strip(),
        "transport_recovered": transport_recovered,
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
    return copied_project
