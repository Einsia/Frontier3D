"""Codex-backed VLM evaluator with schema-constrained rubric output."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.generator.client import (
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_ENV_FILE,
    GeneratorConfig,
    build_codex_command,
)

CRITERIA = (
    "semantic_completeness",
    "spatial_layout",
    "materials_and_style",
    "camera_and_composition",
    "visual_coherence",
)


@dataclass(frozen=True)
class VLMConfig:
    api_key: str
    base_url: str
    model: str
    timeout: float = 300.0
    max_images: int = 8
    max_attempts: int = 2
    runtime: str = "local"
    codex_binary: str = "codex"
    docker_binary: str = "docker"
    docker_image: str = DEFAULT_DOCKER_IMAGE
    reasoning_effort: str | None = "low"
    tested_model: str | None = None

    @property
    def self_judge(self) -> bool:
        return bool(self.tested_model and self.tested_model == self.model)

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> VLMConfig:
        selected = (env_file or DEFAULT_ENV_FILE).expanduser().resolve()
        load_dotenv(selected, override=True)
        api_key = (
            os.environ.get("VLM_API_KEY", "").strip()
            or os.environ.get("OPENAI_API_KEY", "").strip()
        )
        base_url = (
            os.environ.get("VLM_BASE_URL", "").strip()
            or os.environ.get("OPENAI_BASE_URL", "").strip()
        )
        model = (
            os.environ.get("VLM_MODEL", "").strip()
            or os.environ.get("OPENAI_MODEL", "").strip()
        )
        missing = [
            name
            for name, value in (
                ("VLM_API_KEY/OPENAI_API_KEY", api_key),
                ("VLM_BASE_URL/OPENAI_BASE_URL", base_url),
                ("VLM_MODEL/OPENAI_MODEL", model),
            )
            if not value
        ]
        if missing:
            raise ValueError("Missing VLM configuration: " + ", ".join(missing))
        max_images = int(os.environ.get("VLM_MAX_IMAGES", "8"))
        max_attempts = int(os.environ.get("VLM_MAX_ATTEMPTS", "2"))
        timeout = float(os.environ.get("VLM_TIMEOUT", "300"))
        if max_images < 1 or max_attempts < 1 or timeout <= 0:
            raise ValueError(
                "VLM_MAX_IMAGES and VLM_MAX_ATTEMPTS must be positive integers; "
                "VLM_TIMEOUT must be positive"
            )
        reasoning = os.environ.get("VLM_REASONING_EFFORT", "low").strip().lower()
        return cls(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model=model,
            timeout=timeout,
            max_images=max_images,
            max_attempts=max_attempts,
            runtime=os.environ.get(
                "VLM_RUNTIME", os.environ.get("GENERATOR_RUNTIME", "local")
            )
            .strip()
            .lower(),
            codex_binary=os.environ.get(
                "VLM_CODEX_BIN", os.environ.get("GENERATOR_CODEX_BIN", "codex")
            ).strip()
            or "codex",
            docker_binary=os.environ.get(
                "VLM_DOCKER_BIN", os.environ.get("GENERATOR_DOCKER_BIN", "docker")
            ).strip()
            or "docker",
            docker_image=os.environ.get(
                "VLM_DOCKER_IMAGE",
                os.environ.get("GENERATOR_DOCKER_IMAGE", DEFAULT_DOCKER_IMAGE),
            ).strip(),
            reasoning_effort=reasoning or None,
            tested_model=os.environ.get("OPENAI_MODEL", "").strip() or None,
        )

    def generator_config(self) -> GeneratorConfig:
        return GeneratorConfig(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            timeout=self.timeout,
            max_attempts=self.max_attempts,
            runtime=self.runtime,
            codex_binary=self.codex_binary,
            docker_binary=self.docker_binary,
            docker_image=self.docker_image,
            reasoning_effort=self.reasoning_effort,
            verbosity="low",
        )


def _schema() -> dict[str, Any]:
    item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "criterion": {"type": "string", "enum": list(CRITERIA)},
            "score": {"type": "integer", "minimum": 0, "maximum": 4},
            "evidence": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "not_judgeable": {"type": "boolean"},
        },
        "required": [
            "criterion",
            "score",
            "evidence",
            "confidence",
            "not_judgeable",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "criteria": {
                "type": "array",
                "minItems": len(CRITERIA),
                "maxItems": len(CRITERIA),
                "items": item,
            },
            "summary": {"type": "string"},
        },
        "required": ["criteria", "summary"],
    }


def _prompt(
    instruction: str,
    reference_images: list[Path],
    candidate_images: list[Path],
) -> str:
    reference_names = ", ".join(path.name for path in reference_images) or "none"
    candidate_names = ", ".join(path.name for path in candidate_images) or "none"
    return f"""\
You are the visual evaluator for a 3D-generation benchmark. Do not call tools,
read files, or write files. Inspect only the images attached to this message.
They are attached in this exact order: first REFERENCE images ({reference_names}),
then CANDIDATE images ({candidate_names}). A reference may be an example rather
than a pixel-exact target; follow the task instruction when deciding that.

Score each required criterion exactly once from 0 (absent/wrong) to 4
(excellent). Base evidence only on visible content. Mark not_judgeable when the
attached views genuinely cannot establish the criterion. Keep evidence concise.

Task instruction:
{instruction.strip()}
"""


def _error_tail(
    completed: subprocess.CompletedProcess[str], redactions: tuple[str, ...] = ()
) -> str:
    output = completed.stderr.strip() or completed.stdout.strip()
    for sensitive_value in redactions:
        if sensitive_value:
            output = output.replace(sensitive_value, "<redacted-base-url>")
    lines = output.splitlines()
    return "\n".join(lines[-20:]) if lines else "no diagnostic output"


def evaluate_with_vlm(
    config: VLMConfig,
    instruction: str,
    reference_images: list[Path],
    candidate_images: list[Path],
) -> dict[str, Any]:
    reference_limit = config.max_images // 2 if candidate_images else config.max_images
    selected_references = reference_images[:reference_limit]
    remaining = config.max_images - len(selected_references)
    selected_candidates = candidate_images[:remaining]
    images = [*selected_references, *selected_candidates]
    if not selected_candidates:
        raise ValueError("VLM evaluation requires at least one candidate image")

    with tempfile.TemporaryDirectory(prefix="3dbench-vlm-") as temp_name:
        workdir = Path(temp_name)
        output = workdir / "judgment.json"
        schema = workdir / "schema.json"
        schema.write_text(json.dumps(_schema()), encoding="utf-8")
        command = build_codex_command(
            config.generator_config(),
            output_path=output,
            working_directory=workdir,
            image_paths=images,
            output_schema=schema,
        )
        environment = os.environ.copy()
        environment["CODEX_API_KEY"] = config.api_key
        last_error = "Codex VLM failed without diagnostic output"
        for attempt in range(1, config.max_attempts + 1):
            try:
                completed = subprocess.run(
                    command,
                    input=_prompt(
                        instruction, selected_references, selected_candidates
                    ),
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=config.timeout,
                    cwd=workdir,
                    env=environment,
                )
            except FileNotFoundError as error:
                raise RuntimeError(
                    "Codex CLI for VLM evaluation was not found"
                ) from error
            except subprocess.TimeoutExpired:
                last_error = f"Codex VLM timed out after {config.timeout:g} seconds"
            else:
                if completed.returncode != 0:
                    last_error = (
                        f"Codex VLM exited with code {completed.returncode}: "
                        f"{_error_tail(completed, (config.base_url,))}"
                    )
                elif output.is_file():
                    break
                else:
                    last_error = "Codex VLM wrote no final judgment"
            if attempt < config.max_attempts:
                output.unlink(missing_ok=True)
                time.sleep(min(2 ** (attempt - 1), 8))
        else:
            raise RuntimeError(last_error)

        judgment = json.loads(output.read_text(encoding="utf-8"))

    criteria = judgment.get("criteria", [])
    names = [item.get("criterion") for item in criteria]
    if sorted(names) != sorted(CRITERIA):
        raise ValueError("VLM judgment did not contain each rubric criterion once")
    scores = [
        item["score"] for item in criteria if not item.get("not_judgeable", False)
    ]
    judgment.update(
        {
            "score": (100.0 * sum(scores) / (4 * len(scores))) if scores else None,
            "model": config.model,
            "backend": "codex",
            "self_judge": config.self_judge,
            "reference_images": [path.name for path in selected_references],
            "candidate_images": [path.name for path in selected_candidates],
        }
    )
    return judgment
