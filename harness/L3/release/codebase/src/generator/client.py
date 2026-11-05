"""Codex CLI backend for generating self-contained ``bpy`` scripts."""

from __future__ import annotations

import ast
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "output_script"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_DOCKER_IMAGE = "3dbench-codex:0.163.0"
CODEX_PROVIDER_ID = "benchmark"

SYSTEM_PROMPT = """\
You are an expert Blender Python scene author. Return exactly one complete,
self-contained Python script that uses bpy and runs in Blender 5.2.1. Return
only Python source code, without Markdown fences or explanatory prose.

The script must construct the requested scene from a clean Blender file. It
must create all required geometry, materials, lighting, world settings, and an
active camera, and configure render resolution and engine so the intended final
composition can be rendered immediately. Make the result deterministic. Do not
download assets or depend on local files unless the user explicitly requests
them. Do not save the .blend file; the surrounding runner handles saving. Do
not call tools, inspect the working directory, or modify files. For this exact
Blender build, use BLENDER_EEVEE for Eevee (never BLENDER_EEVEE_NEXT), or use
CYCLES with CPU rendering. The surrounding runner has already called
bpy.ops.wm.read_factory_settings(use_empty=True), so do not reset the file
again. A clean scene can have scene.world set to None: create and assign a
World before accessing its properties or nodes. Do not access legacy
scene.eevee properties such as use_gtao; when using Eevee, set only supported
generic render properties unless a Blender 5.2 API is certain.
For animation, insert keyframes directly. Never access
obj.animation_data.action.fcurves: Blender 5.2 uses layered/slotted Actions and
that legacy attribute is unavailable. Omit manual interpolation changes unless
you implement them through the Blender 5.2 Action layer/channelbag API.
"""

TEXT_TASK_PROMPT = """\
Create a Blender bpy script for this scene description:

{prompt}
"""

IMAGE_TASK_PROMPT = """\
Reconstruct the supplied reference image as closely as practical in Blender.
Analyze its objects, geometry, proportions, spatial layout, materials, colors,
camera pose and focal length, lighting, shadows, background, and composition.
Create a bpy script whose rendered view matches those visible characteristics.
{extra_instruction}
"""

BENCHMARK_SYSTEM_PROMPT = """\
You are an expert Blender Python scene author. Return exactly one complete
Python script named solution.py that uses bpy and runs in Blender 5.2.1.
Return only Python source code, without Markdown fences or explanatory prose.

The current read-only working directory contains only the task's declared
model-visible environment files. You may inspect and read those files, keeping
their input/... relative paths. Never search outside this working directory,
access a network service, download assets, or rely on undeclared files.

The surrounding runner starts Blender from a factory-empty file, executes the
script with the submission directory as its working directory, and saves the
result as scene.blend. Do not save scene.blend yourself. If the instruction
requires editing an input .blend file, explicitly open input/... from the
script before modifying it. If it requires additional outputs such as GLB or
PNG files, create them with the exact requested names next to solution.py. Use
paths relative to Path(__file__).resolve().parent so execution is reproducible.

Create real editable geometry rather than camera-facing reference planes or
material-only fake holes. Make the result deterministic and create or preserve
all required geometry, hierarchy, materials, cameras, lighting, animation, and
render settings. For this exact Blender build, use BLENDER_EEVEE for Eevee
(never BLENDER_EEVEE_NEXT), or use CYCLES with CPU rendering. A factory-empty
scene can have scene.world set to None: create and assign a World before
accessing it. Do not use legacy scene.eevee properties such as use_gtao.
For animation, insert keyframes directly. Never access
obj.animation_data.action.fcurves: Blender 5.2 uses layered/slotted Actions and
that legacy attribute is unavailable. Omit manual interpolation changes unless
you implement them through the Blender 5.2 Action layer/channelbag API.
"""

BENCHMARK_TASK_PROMPT = """\
Complete the following benchmark instruction.

Model-visible files (relative to the working directory):
{environment_files}

Task instruction:
{instruction}
"""

_FENCED_CODE = re.compile(
    r"```(?:python|py)?\s*\n(?P<code>.*?)\n```",
    flags=re.IGNORECASE | re.DOTALL,
)


class GeneratorError(RuntimeError):
    """Raised when configuration or model output cannot produce a script."""


def _positive_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise GeneratorError(f"{name} must be a number, got {value!r}") from error
    if parsed <= 0:
        raise GeneratorError(f"{name} must be greater than zero")
    return parsed


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise GeneratorError(f"{name} must be an integer, got {value!r}") from error
    if parsed <= 0:
        raise GeneratorError(f"{name} must be greater than zero")
    return parsed


@dataclass(frozen=True)
class GeneratorConfig:
    """Codex provider and runtime settings loaded from the project ``.env``."""

    api_key: str
    base_url: str
    model: str
    timeout: float = 300.0
    max_attempts: int = 2
    runtime: str = "local"
    codex_binary: str = "codex"
    docker_binary: str = "docker"
    docker_image: str = DEFAULT_DOCKER_IMAGE
    reasoning_effort: str | None = None
    verbosity: str | None = None

    def __post_init__(self) -> None:
        if self.runtime not in {"local", "docker"}:
            raise GeneratorError("GENERATOR_RUNTIME must be either local or docker")
        if self.runtime == "docker" and not self.docker_image.strip():
            raise GeneratorError(
                "GENERATOR_DOCKER_IMAGE is required for Docker runtime"
            )
        valid_reasoning_efforts = {
            None,
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
        }
        if self.reasoning_effort not in valid_reasoning_efforts:
            raise GeneratorError(
                "GENERATOR_REASONING_EFFORT must be minimal, low, medium, high, or xhigh"
            )
        if self.verbosity not in {None, "low", "medium", "high"}:
            raise GeneratorError(
                "GENERATOR_VERBOSITY must be low, medium, or high"
            )

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> GeneratorConfig:
        selected_env = (env_file or DEFAULT_ENV_FILE).expanduser().resolve()
        # The selected project file is the source of truth even when the
        # parent shell already exports a different OpenAI credential.
        load_dotenv(selected_env, override=True)

        required_names = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL")
        values = {name: os.environ.get(name, "").strip() for name in required_names}
        missing = [name for name, value in values.items() if not value]
        if missing:
            names = ", ".join(missing)
            raise GeneratorError(
                f"Missing required environment variables: {names}. "
                f"Copy .env.example to {selected_env} and fill in the API settings."
            )

        return cls(
            api_key=values["OPENAI_API_KEY"],
            base_url=values["OPENAI_BASE_URL"].rstrip("/"),
            model=values["OPENAI_MODEL"],
            timeout=_positive_float(
                os.environ.get("GENERATOR_TIMEOUT", "300"), "GENERATOR_TIMEOUT"
            ),
            max_attempts=_positive_int(
                os.environ.get("GENERATOR_MAX_ATTEMPTS", "2"),
                "GENERATOR_MAX_ATTEMPTS",
            ),
            runtime=os.environ.get("GENERATOR_RUNTIME", "local").strip().lower(),
            codex_binary=os.environ.get("GENERATOR_CODEX_BIN", "codex").strip()
            or "codex",
            docker_binary=os.environ.get("GENERATOR_DOCKER_BIN", "docker").strip()
            or "docker",
            docker_image=os.environ.get(
                "GENERATOR_DOCKER_IMAGE", DEFAULT_DOCKER_IMAGE
            ).strip(),
            reasoning_effort=(
                os.environ.get("GENERATOR_REASONING_EFFORT", "").strip().lower()
                or None
            ),
            verbosity=(
                os.environ.get("GENERATOR_VERBOSITY", "").strip().lower() or None
            ),
        )


def extract_python_source(content: str) -> str:
    """Normalize and syntax-check Python returned by a model."""

    if not isinstance(content, str) or not content.strip():
        raise GeneratorError("The model returned an empty response")

    normalized = content.strip().lstrip("\ufeff")
    fenced_blocks = [
        match.group("code").strip() for match in _FENCED_CODE.finditer(normalized)
    ]
    if fenced_blocks:
        if len(fenced_blocks) != 1:
            raise GeneratorError("The model returned multiple fenced code blocks")
        normalized = fenced_blocks[0]
    elif normalized.startswith("```") or normalized.endswith("```"):
        raise GeneratorError("The model returned a malformed Markdown code fence")

    try:
        ast.parse(normalized, filename="<generated_bpy_script>")
    except SyntaxError as error:
        location = f"line {error.lineno}" if error.lineno else "unknown line"
        lines = normalized.splitlines()
        offending_line = ""
        if error.lineno and error.lineno <= len(lines):
            offending_line = (
                f" Offending source: {lines[error.lineno - 1].strip()[:200]!r}."
            )
        raise GeneratorError(
            f"The generated script is invalid Python ({location}): "
            f"{error.msg}.{offending_line}"
        ) from error

    return normalized.rstrip() + "\n"


def resolve_reference_image(image_path: Path) -> Path:
    """Validate a local reference image before passing it to Codex."""

    image = image_path.expanduser().resolve()
    if not image.is_file():
        raise FileNotFoundError(f"Reference image does not exist: {image}")
    media_type, _ = mimetypes.guess_type(image.name)
    if media_type is None or not media_type.startswith("image/"):
        raise GeneratorError(
            f"Unsupported reference image type: {image.suffix or image.name}"
        )
    return image


def _codex_exec_arguments(
    config: GeneratorConfig,
    output_path: Path,
    working_directory: Path,
    image_paths: Sequence[Path],
    sandbox_mode: str = "read-only",
    output_schema: Path | None = None,
) -> list[str]:
    arguments = [
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--ephemeral",
        "--sandbox",
        sandbox_mode,
        "--skip-git-repo-check",
        "--model",
        config.model,
        "--config",
        f'model_provider="{CODEX_PROVIDER_ID}"',
        "--config",
        f'model_providers.{CODEX_PROVIDER_ID}.name="3DBench provider"',
        "--config",
        f"model_providers.{CODEX_PROVIDER_ID}.base_url={json.dumps(config.base_url)}",
        "--config",
        f'model_providers.{CODEX_PROVIDER_ID}.env_key="CODEX_API_KEY"',
        "--config",
        f'model_providers.{CODEX_PROVIDER_ID}.wire_api="responses"',
        "--config",
        'shell_environment_policy.inherit="none"',
    ]
    if config.reasoning_effort is not None:
        arguments.extend(
            ("--config", f'model_reasoning_effort="{config.reasoning_effort}"')
        )
    if config.verbosity is not None:
        arguments.extend(("--config", f'model_verbosity="{config.verbosity}"'))
    if output_schema is not None:
        arguments.extend(("--output-schema", str(output_schema)))
    arguments.extend(
        [
            "--output-last-message",
            str(output_path),
            "--cd",
            str(working_directory),
        ]
    )
    for image_path in image_paths:
        arguments.extend(("--image", str(image_path)))
    arguments.append("-")
    return arguments


def build_codex_command(
    config: GeneratorConfig,
    output_path: Path,
    working_directory: Path,
    image_path: Path | None = None,
    *,
    image_paths: Sequence[Path] | None = None,
    sandbox_mode: str = "read-only",
    output_schema: Path | None = None,
) -> list[str]:
    """Build a local or Docker Codex command without embedding the API key."""

    if image_path is not None and image_paths is not None:
        raise ValueError("Pass image_path or image_paths, not both")
    selected_images = tuple(
        image_paths or (() if image_path is None else (image_path,))
    )
    resolved_working_directory = working_directory.expanduser().resolve()
    resolved_output = output_path.expanduser().resolve()
    resolved_images = tuple(image.expanduser().resolve() for image in selected_images)
    resolved_schema = (
        output_schema.expanduser().resolve() if output_schema is not None else None
    )

    if config.runtime == "local":
        return [
            config.codex_binary,
            *_codex_exec_arguments(
                config,
                resolved_output,
                resolved_working_directory,
                resolved_images,
                sandbox_mode,
                resolved_schema,
            ),
        ]

    container_output = Path("/output") / resolved_output.name
    container_working_directory = Path("/workspace")
    command = [
        config.docker_binary,
        "run",
        "--rm",
        "-i",
        "--env",
        "CODEX_API_KEY",
        "--mount",
        f"type=bind,src={resolved_output.parent},dst=/output",
    ]
    workspace_mount = (
        "type=bind,"
        f"src={resolved_working_directory},dst={container_working_directory}"
    )
    if sandbox_mode == "read-only":
        workspace_mount += ",readonly"
    command.extend(("--mount", workspace_mount))
    container_schema = None
    if resolved_schema is not None:
        if resolved_schema.parent == resolved_output.parent:
            container_schema = Path("/output") / resolved_schema.name
        else:
            container_schema = Path("/schema") / resolved_schema.name
            command.extend(
                (
                    "--mount",
                    f"type=bind,src={resolved_schema},dst={container_schema},readonly",
                )
            )
    container_images: list[Path] = []
    for index, selected_image in enumerate(resolved_images):
        try:
            relative_image = selected_image.relative_to(resolved_working_directory)
        except ValueError:
            container_image = (
                Path("/reference_images")
                / f"reference_{index:03d}{selected_image.suffix.lower()}"
            )
            command.extend(
                (
                    "--mount",
                    f"type=bind,src={selected_image},dst={container_image},readonly",
                )
            )
        else:
            container_image = container_working_directory / relative_image
        container_images.append(container_image)

    command.extend(
        (
            config.docker_image,
            "codex",
            *_codex_exec_arguments(
                config,
                container_output,
                container_working_directory,
                container_images,
                sandbox_mode,
                container_schema,
            ),
        )
    )
    return command


def _error_tail(
    completed: subprocess.CompletedProcess[str], redactions: Sequence[str] = ()
) -> str:
    output = completed.stderr.strip() or completed.stdout.strip()
    for sensitive_value in redactions:
        if sensitive_value:
            output = output.replace(sensitive_value, "<redacted-base-url>")
    lines = output.splitlines()
    return "\n".join(lines[-30:]) if lines else "no diagnostic output"


class BpyScriptGenerator:
    """Generate scripts through the official Codex CLI."""

    def __init__(self, config: GeneratorConfig, command_runner: Any = None) -> None:
        self.config = config
        self.command_runner = command_runner or subprocess.run

    def _run_codex(
        self,
        prompt: str,
        image_paths: Sequence[Path] = (),
        working_directory: Path | None = None,
        sandbox_mode: str = "read-only",
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="3dbench-generator-") as temp_name:
            temp_directory = Path(temp_name)
            output_path = temp_directory / "final.py"
            codex_working_directory = working_directory
            if codex_working_directory is None:
                codex_working_directory = temp_directory / "workspace"
                codex_working_directory.mkdir()
            else:
                codex_working_directory = codex_working_directory.expanduser().resolve()
            command = build_codex_command(
                self.config,
                output_path=output_path,
                working_directory=codex_working_directory,
                image_paths=image_paths,
                sandbox_mode=sandbox_mode,
            )
            environment = os.environ.copy()
            environment["CODEX_API_KEY"] = self.config.api_key
            last_error = "Codex failed without diagnostic output"
            for attempt in range(1, self.config.max_attempts + 1):
                try:
                    completed = self.command_runner(
                        command,
                        input=prompt,
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=self.config.timeout,
                        cwd=codex_working_directory,
                        env=environment,
                    )
                except FileNotFoundError as error:
                    executable = (
                        self.config.codex_binary
                        if self.config.runtime == "local"
                        else self.config.docker_binary
                    )
                    raise GeneratorError(
                        f"Required executable not found: {executable}"
                    ) from error
                except subprocess.TimeoutExpired:
                    last_error = (
                        f"Codex timed out after {self.config.timeout:g} seconds"
                    )
                else:
                    if completed.returncode != 0:
                        last_error = (
                            f"Codex exited with code {completed.returncode}:\n"
                            f"{_error_tail(completed, (self.config.base_url,))}"
                        )
                    elif not output_path.is_file():
                        last_error = (
                            "Codex succeeded but did not write its final message"
                        )
                    else:
                        return output_path.read_text(encoding="utf-8")

                if attempt < self.config.max_attempts:
                    output_path.unlink(missing_ok=True)
                    time.sleep(min(2 ** (attempt - 1), 8))

            raise GeneratorError(
                f"Codex failed after {self.config.max_attempts} attempts:\n{last_error}"
            )

    def run_workspace_task(
        self,
        prompt: str,
        *,
        image_paths: Sequence[Path] = (),
        working_directory: Path,
    ) -> str:
        """Run a Codex task allowed to create files inside one isolated workspace."""

        return self._run_codex(
            prompt,
            image_paths=image_paths,
            working_directory=working_directory,
            sandbox_mode="workspace-write",
        )

    def _complete(
        self,
        task_prompt: str,
        image_paths: Sequence[Path] = (),
        working_directory: Path | None = None,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> str:
        original_prompt = f"{system_prompt.strip()}\n\n{task_prompt.strip()}\n"
        prompt = original_prompt
        for attempt in range(1, self.config.max_attempts + 1):
            raw_response = self._run_codex(
                prompt,
                image_paths=image_paths,
                working_directory=working_directory,
            )
            try:
                return extract_python_source(raw_response)
            except GeneratorError as error:
                if attempt == self.config.max_attempts:
                    raise
                prompt = (
                    f"{original_prompt}\n"
                    "Your previous response failed Python syntax validation. "
                    "Correct the complete script and return only the corrected Python source.\n"
                    f"Validation error: {error}\n\n"
                    "Previous response:\n"
                    f"{raw_response}\n"
                )
        raise AssertionError("unreachable")

    def from_text(self, prompt: str) -> str:
        """Generate a scene script from a text description."""

        prompt = prompt.strip()
        if not prompt:
            raise GeneratorError("The scene prompt must not be empty")
        return self._complete(TEXT_TASK_PROMPT.format(prompt=prompt))

    def from_image(self, image_path: Path, prompt: str | None = None) -> str:
        """Generate a scene script that visually reconstructs a reference image."""

        image = resolve_reference_image(image_path)
        extra = ""
        if prompt and prompt.strip():
            extra = f"\nAdditional user requirements:\n{prompt.strip()}"
        task_prompt = IMAGE_TASK_PROMPT.format(extra_instruction=extra)
        return self._complete(task_prompt, image_paths=(image,))

    def from_benchmark_task(
        self,
        instruction: str,
        environment_files: Sequence[str],
        image_paths: Sequence[Path],
        working_directory: Path,
    ) -> str:
        """Generate ``solution.py`` for a staged 3DBench task workspace."""

        instruction = instruction.strip()
        if not instruction:
            raise GeneratorError("The benchmark task instruction must not be empty")
        file_listing = "\n".join(f"- {name}" for name in environment_files)
        if not file_listing:
            file_listing = "- (none; this is a text-only task)"
        task_prompt = BENCHMARK_TASK_PROMPT.format(
            environment_files=file_listing,
            instruction=instruction,
        )
        return self._complete(
            task_prompt,
            image_paths=image_paths,
            working_directory=working_directory,
            system_prompt=BENCHMARK_SYSTEM_PROMPT,
        )


def resolve_output_path(
    output_name: str, output_dir: Path = DEFAULT_OUTPUT_DIR
) -> Path:
    """Resolve a script filename while keeping output inside ``output_dir``."""

    candidate = Path(output_name)
    if (
        candidate.is_absolute()
        or candidate.name != output_name
        or output_name in {"", ".", ".."}
    ):
        raise GeneratorError("--output must be a filename, not a path")
    if candidate.suffix.lower() != ".py":
        raise GeneratorError("--output filename must end with .py")
    return output_dir.expanduser().resolve() / candidate.name


def write_script(source: str, output: Path, overwrite: bool = False) -> Path:
    """Write generated source without silently replacing an existing script."""

    output.parent.mkdir(parents=True, exist_ok=True)
    if overwrite:
        output.write_text(source, encoding="utf-8")
    else:
        try:
            with output.open("x", encoding="utf-8") as script_file:
                script_file.write(source)
        except FileExistsError as error:
            raise GeneratorError(
                f"Output script already exists: {output}; pass --overwrite to replace it"
            ) from error
    return output
