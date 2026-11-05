import subprocess
from pathlib import Path

import pytest

from src.generator.cli import _build_parser
from src.generator.client import (
    BpyScriptGenerator,
    GeneratorConfig,
    GeneratorError,
    build_codex_command,
    extract_python_source,
    resolve_output_path,
    resolve_reference_image,
    write_script,
)
from src.generator.task_adapter import (
    generate_task_submission,
    load_benchmark_task,
)


class FakeRunner:
    def __init__(
        self, content: str | list[str], returncode: int | list[int] = 0
    ) -> None:
        self.contents = [content] if isinstance(content, str) else content
        self.returncodes = [returncode] if isinstance(returncode, int) else returncode
        self.command = None
        self.arguments = None
        self.calls = 0
        self.cwd_files = None

    def __call__(self, command, **kwargs):
        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        self.command = command
        self.arguments = kwargs
        working_directory = Path(kwargs["cwd"])
        self.cwd_files = sorted(
            path.relative_to(working_directory).as_posix()
            for path in working_directory.rglob("*")
            if path.is_file()
        )
        output_index = command.index("--output-last-message") + 1
        Path(command[output_index]).write_text(content, encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            self.returncodes[min(self.calls - 1, len(self.returncodes) - 1)],
            stdout=content,
            stderr=(
                "test error"
                if self.returncodes[min(self.calls - 1, len(self.returncodes) - 1)]
                else ""
            ),
        )


def config(**overrides) -> GeneratorConfig:
    values = {
        "api_key": "test-secret",
        "base_url": "https://example.test/v1",
        "model": "vision-model",
    }
    values.update(overrides)
    return GeneratorConfig(**values)


def test_cli_accepts_explicit_model_and_reasoning_overrides() -> None:
    args = _build_parser().parse_args(
        [
            "task",
            "--task",
            "L1/Image2Code",
            "--model",
            "gpt-6-astra",
            "--reasoning-effort",
            "medium",
        ]
    )

    assert args.model == "gpt-6-astra"
    assert args.reasoning_effort == "medium"


def test_loads_codex_configuration_from_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_DATA_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "GENERATOR_TIMEOUT",
        "GENERATOR_MAX_ATTEMPTS",
        "GENERATOR_RUNTIME",
        "GENERATOR_CODEX_BIN",
        "GENERATOR_DOCKER_BIN",
        "GENERATOR_DOCKER_IMAGE",
        "GENERATOR_REASONING_EFFORT",
        "GENERATOR_VERBOSITY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key-must-not-win")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=secret\n"
        "OPENAI_BASE_URL=https://example.test/v1/\n"
        "OPENAI_MODEL=vision-model\n"
        "GENERATOR_TIMEOUT=45\n"
        "GENERATOR_MAX_ATTEMPTS=3\n"
        "GENERATOR_RUNTIME=docker\n"
        "GENERATOR_CODEX_BIN=custom-codex\n"
        "GENERATOR_DOCKER_BIN=custom-docker\n"
        "GENERATOR_DOCKER_IMAGE=custom-image:1\n"
        "GENERATOR_REASONING_EFFORT=low\n"
        "GENERATOR_VERBOSITY=high\n",
        encoding="utf-8",
    )

    loaded = GeneratorConfig.from_env(env_file)

    assert loaded.api_key == "secret"
    assert loaded.base_url == "https://example.test/v1"
    assert loaded.model == "vision-model"
    assert loaded.timeout == 45
    assert loaded.max_attempts == 3
    assert loaded.runtime == "docker"
    assert loaded.codex_binary == "custom-codex"
    assert loaded.docker_binary == "custom-docker"
    assert loaded.docker_image == "custom-image:1"
    assert loaded.reasoning_effort == "low"
    assert loaded.verbosity == "high"


def test_extracts_one_markdown_code_block() -> None:
    assert extract_python_source("```python\nimport bpy\n```") == "import bpy\n"


def test_rejects_invalid_python() -> None:
    with pytest.raises(GeneratorError, match="invalid Python"):
        extract_python_source("def broken(")


def test_text_generation_uses_local_codex_without_key_in_command() -> None:
    runner = FakeRunner("import bpy\n")
    generator = BpyScriptGenerator(config(), command_runner=runner)

    assert generator.from_text("A red cube") == "import bpy\n"
    assert runner.command[:2] == ["codex", "exec"]
    assert "vision-model" in runner.command
    assert "test-secret" not in " ".join(runner.command)
    assert runner.arguments["env"]["CODEX_API_KEY"] == "test-secret"
    assert "A red cube" in runner.arguments["input"]
    assert runner.arguments["cwd"].parent.name.startswith("3dbench-generator-")


def test_image_generation_passes_reference_to_codex(tmp_path: Path) -> None:
    image = tmp_path / "reference.png"
    image.write_bytes(b"fake png")
    runner = FakeRunner("import bpy\n")
    generator = BpyScriptGenerator(config(), command_runner=runner)

    generator.from_image(image, prompt="Use orthographic projection")

    image_index = runner.command.index("--image") + 1
    assert runner.command[image_index] == str(image.resolve())
    assert "Use orthographic projection" in runner.arguments["input"]


def test_retries_invalid_python_with_validation_feedback() -> None:
    runner = FakeRunner(["def broken(", "import bpy\n"])
    generator = BpyScriptGenerator(config(), command_runner=runner)

    assert generator.from_text("A red cube") == "import bpy\n"
    assert runner.calls == 2
    assert "failed Python syntax validation" in runner.arguments["input"]
    assert "def broken(" in runner.arguments["input"]


def test_retries_transient_codex_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner(["partial", "import bpy\n"], returncode=[1, 0])
    generator = BpyScriptGenerator(config(), command_runner=runner)
    monkeypatch.setattr("src.generator.client.time.sleep", lambda _seconds: None)

    assert generator.from_text("A red cube") == "import bpy\n"
    assert runner.calls == 2


def test_builds_isolated_docker_codex_command(tmp_path: Path) -> None:
    image = tmp_path / "reference.png"
    image.write_bytes(b"fake png")
    output = tmp_path / "final.py"

    command = build_codex_command(
        config(runtime="docker", docker_image="codex-test:1"),
        output_path=output,
        working_directory=tmp_path,
        image_path=image,
    )

    assert command[:4] == ["docker", "run", "--rm", "-i"]
    assert "codex-test:1" in command
    assert command[command.index("codex-test:1") + 1 :][:2] == ["codex", "exec"]
    assert "test-secret" not in " ".join(command)
    assert "CODEX_API_KEY" in command
    assert "/output/final.py" in command
    assert "/workspace/reference.png" in command


def test_codex_command_applies_optional_model_controls(tmp_path: Path) -> None:
    command = build_codex_command(
        config(reasoning_effort="low", verbosity="high"),
        output_path=tmp_path / "final.py",
        working_directory=tmp_path,
    )

    assert 'model_reasoning_effort="low"' in command
    assert 'model_verbosity="high"' in command


def test_codex_command_supports_workspace_write_and_output_schema(
    tmp_path: Path,
) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")

    command = build_codex_command(
        config(),
        output_path=tmp_path / "final.json",
        working_directory=tmp_path,
        sandbox_mode="workspace-write",
        output_schema=schema,
    )

    assert command[command.index("--sandbox") + 1] == "workspace-write"
    assert command[command.index("--output-schema") + 1] == str(schema.resolve())


def _write_task_bundle(
    tmp_path: Path,
    *,
    level: int = 1,
    environment_files: dict[str, bytes] | None = None,
) -> Path:
    task_dir = tmp_path / "tasks" / f"L{level}" / "Example"
    environment = task_dir / "environment"
    environment.mkdir(parents=True)
    (task_dir / "instruction.md").write_text(
        "Create the requested editable Blender asset.", encoding="utf-8"
    )
    files = environment_files or {}
    for name, content in files.items():
        target = environment / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    file_list = ", ".join(repr(name) for name in files)
    (task_dir / "task.toml").write_text(
        "version = 1\n"
        f'id = "L{level}/Example"\n'
        f"level = {level}\n"
        'title = "Example"\n'
        'instruction = "instruction.md"\n'
        'review_instruction = "instruction.zh.md"\n'
        'environment = "environment"\n'
        'solution = "solution"\n'
        'harness = "harness"\n'
        'harness_status = "not_implemented"\n'
        'reference_kind = "geometric_reference"\n'
        f"environment_files = [{file_list}]\n",
        encoding="utf-8",
    )
    return task_dir


def test_task_adapter_stages_only_allowlisted_inputs_and_all_images(
    tmp_path: Path,
) -> None:
    task_dir = _write_task_bundle(
        tmp_path,
        environment_files={
            "input/front.png": b"front image",
            "input/top.png": b"top image",
            "input/initial.py": b"VALUE = 1\n",
        },
    )
    hidden = task_dir / "solution" / "secret.txt"
    hidden.parent.mkdir()
    hidden.write_text("must not be visible", encoding="utf-8")
    task = load_benchmark_task(task_dir)
    runner = FakeRunner("import bpy\n")
    output_dir = tmp_path / "submission"

    script = generate_task_submission(
        BpyScriptGenerator(config(), command_runner=runner),
        task,
        output_dir,
    )

    assert script == output_dir / "solution.py"
    assert script.read_text(encoding="utf-8") == "import bpy\n"
    manifest = __import__("json").loads(
        (output_dir / "task_run.json").read_text(encoding="utf-8")
    )
    assert manifest["generation"] == {
        "model": "vision-model",
        "reasoning_effort": None,
        "runtime": "local",
    }
    assert (output_dir / "input" / "initial.py").is_file()
    assert not (output_dir / "solution" / "secret.txt").exists()
    assert runner.cwd_files == [
        "input/front.png",
        "input/initial.py",
        "input/top.png",
    ]
    image_arguments = [
        runner.command[index + 1]
        for index, value in enumerate(runner.command)
        if value == "--image"
    ]
    assert len(image_arguments) == 2
    assert "input/front.png" in runner.arguments["input"]
    assert "input/initial.py" in runner.arguments["input"]
    assert "must not be visible" not in runner.arguments["input"]


def test_task_adapter_rejects_unmaterialized_lfs_assets(tmp_path: Path) -> None:
    pointer = (
        b"version https://git-lfs.github.com/spec/v1\noid sha256:0123456789\nsize 123\n"
    )
    task = load_benchmark_task(
        _write_task_bundle(
            tmp_path,
            environment_files={"input/reference.png": pointer},
        )
    )

    with pytest.raises(GeneratorError, match="Git LFS pointer"):
        task.validate_materialized_assets()


def test_task_adapter_rejects_ue5_level_three(tmp_path: Path) -> None:
    task = load_benchmark_task(_write_task_bundle(tmp_path, level=3))

    with pytest.raises(GeneratorError, match="requires a UE5"):
        task.require_blender_backend()


def test_task_manifest_rejects_environment_path_traversal(tmp_path: Path) -> None:
    task_dir = _write_task_bundle(tmp_path)
    manifest = (task_dir / "task.toml").read_text(encoding="utf-8")
    (task_dir / "task.toml").write_text(
        manifest.replace("environment_files = []", 'environment_files = ["../secret"]'),
        encoding="utf-8",
    )

    with pytest.raises(GeneratorError, match="safe relative path"):
        load_benchmark_task(task_dir)


def test_output_is_restricted_to_a_python_filename(tmp_path: Path) -> None:
    assert resolve_output_path("scene.py", tmp_path) == tmp_path.resolve() / "scene.py"
    with pytest.raises(GeneratorError, match="filename, not a path"):
        resolve_output_path("nested/scene.py", tmp_path)


def test_write_does_not_overwrite_by_default(tmp_path: Path) -> None:
    output = tmp_path / "scene.py"
    write_script("import bpy\n", output)

    with pytest.raises(GeneratorError, match="already exists"):
        write_script("# replacement\n", output)

    assert output.read_text(encoding="utf-8") == "import bpy\n"


def test_reference_image_rejects_non_image_files(tmp_path: Path) -> None:
    document = tmp_path / "reference.txt"
    document.write_text("not an image", encoding="utf-8")

    with pytest.raises(GeneratorError, match="Unsupported reference image type"):
        resolve_reference_image(document)


def test_parallel_config_files_do_not_mutate_process_environment(tmp_path, monkeypatch):
    import os
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setenv("GENERATOR_REASONING_EFFORT", "low")
    before = dict(os.environ)
    files = []
    efforts = ["medium", "high", "xhigh", "max"]
    for i, effort in enumerate(efforts):
        path = tmp_path / f"job-{i}.env"
        path.write_text(f"OPENAI_DATA_API_KEY=key-{i}\nOPENAI_MODEL=model-{i}\n"
            f"OPENAI_BASE_URL=https://example.test/{i}\nGENERATOR_REASONING_EFFORT={effort}\n")
        files.append(path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        configs = list(pool.map(GeneratorConfig.from_env, files * 20))
    for i, value in enumerate(configs):
        j = i % 4
        assert (value.api_key, value.model, value.reasoning_effort) == (f"key-{j}", f"model-{j}", efforts[j])
    assert dict(os.environ) == before
