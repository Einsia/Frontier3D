"""Offline preflight for the source checkout and configured L1/L2 runtimes."""

import importlib.util
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from benchmark.resources import ROOT, blender_path, judge_settings, prepare


def l3_resources():
    path = ROOT / "harness/L3/release/check_resources.py"
    spec = importlib.util.spec_from_file_location("release_l3_resources", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_resources()


def configured(value):
    """Example values must never satisfy the credential/configuration checks."""
    value = str(value or "").strip()
    return bool(value) and not any(
        marker in value.lower()
        for marker in (
            "replace",
            "example.com",
            "example.invalid",
            "your-provider",
            "your-key",
        )
    )


def check(args):
    from benchmark.__main__ import inventory

    result = {"errors": [], "api_calls": 0}
    errors = result["errors"]
    try:
        with tempfile.TemporaryDirectory(prefix="3dbench-contracts-") as tmp:
            prepare(Path(tmp))
        from orchestrator.tasks import load_task

        rows = list(inventory())
        if len(rows) != 130:
            raise ValueError(f"Expected 130 L1/L2 tasks, found {len(rows)}")
        for row in rows:
            task = load_task(
                row["task_id"], require_harness=row["route"] != "extension"
            )
            if row["route"] != "extension":
                if row["level"] == 1:
                    from src.evaluator.l1_case import load_case
                else:
                    from src.evaluator.l2_case import load_case
                load_case(task.root)
        result.update(
            tasks=len(rows),
            extensions=sum(r["route"] == "extension" for r in rows),
            frozen_resources="passed",
            l3=l3_resources(),
        )
    except (OSError, ValueError, KeyError, ImportError) as error:
        errors.append("Release resources: " + str(error))
    if args.resources_only:
        return result

    settings = judge_settings()
    if getattr(args,'model',None):settings={**settings,'OPENAI_MODEL':args.model}

    # Error messages identify a setting, never its secret value or provider response.
    def require(name, value):
        valid = configured(value)
        if not valid:
            errors.append(name + " is missing or still an example value")
        return valid

    from dotenv import dotenv_values

    from benchmark.resources import env_path

    file_settings = {
        k: v for k, v in dotenv_values(env_path()).items() if v is not None
    }
    generator_credentials = (
        file_settings
        if any(file_settings.get(k) for k in ("OPENAI_DATA_API_KEY", "OPENAI_API_KEY"))
        else settings
    )
    judge_credentials = (
        file_settings
        if any(
            file_settings.get(k)
            for k in ("VLM_API_KEY", "OPENAI_DATA_API_KEY", "OPENAI_API_KEY")
        )
        else settings
    )
    generator_key = generator_credentials.get(
        "OPENAI_DATA_API_KEY"
    ) or generator_credentials.get("OPENAI_API_KEY")
    judge_key = (
        judge_credentials.get("VLM_API_KEY")
        or judge_credentials.get("OPENAI_DATA_API_KEY")
        or judge_credentials.get("OPENAI_API_KEY")
    )
    result["generator_key_configured"] = require("OPENAI_API_KEY", generator_key)
    result["judge_key_configured"] = require(
        "VLM_API_KEY (or generator key fallback)", judge_key
    )
    require("OPENAI_MODEL", settings.get("OPENAI_MODEL"))
    judge = settings.get("VLM_MODEL") or "gpt-6-astra"
    if judge != "gpt-6-astra":
        errors.append("Released scoring requires VLM_MODEL=gpt-6-astra")
    for name, value in (
        ("OPENAI_BASE_URL", settings.get("OPENAI_BASE_URL")),
        (
            "VLM_BASE_URL",
            settings.get("VLM_BASE_URL") or settings.get("OPENAI_BASE_URL"),
        ),
    ):
        if require(name, value):
            try:
                url = urlsplit(value)
                valid = (
                    url.scheme in {"http", "https"}
                    and bool(url.hostname)
                    and not url.username
                    and not url.password
                )
            except ValueError:
                valid = False
            if not valid:
                errors.append(
                    name + " must be an HTTP(S) URL without embedded credentials"
                )

    from harness.L2.vlm_judge import JudgeConfig
    from src.generator.client import GeneratorConfig, GeneratorError

    try:
        GeneratorConfig.from_env(env_path())
    except (GeneratorError, ValueError):
        errors.append(
            "Invalid generator settings: check key/URL/model and numeric GENERATOR_* values"
        )
    try:
        JudgeConfig.from_env(env_path())
    except ValueError:
        errors.append(
            "Invalid judge settings: check VLM_REASONING_EFFORT, VLM_TIMEOUT and VLM_MAX_ATTEMPTS"
        )

    def probe(label, command):
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            errors.append(label + " could not start or exceeded 30 seconds")
            return None
        if completed.returncode:
            errors.append(label + " failed")
            return None
        output = completed.stdout.strip()
        if not output:
            errors.append(label + " returned no version/image information")
            return None
        return output

    binary = blender_path()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        errors.append(
            "Blender missing or not executable: use --blender or THREEDBENCH_BLENDER"
        )
    else:
        version = probe("Blender", [str(binary), "--background", "--version"])
        result["blender"] = version.splitlines()[0] if version else "unavailable"
        if version and version.splitlines()[0].split()[:2] != ["Blender", "5.2.1"]:
            errors.append("Released tasks require Blender 5.2.1")

    generator_runtime = args.generator_runtime
    if generator_runtime not in {"local", "docker"}:
        errors.append("GENERATOR_RUNTIME must be local or docker")
    result["generator_runtime"] = generator_runtime
    from src.generator.harnesses import CLAUDE_DOCKER_IMAGE, CLAUDE_VERSION, NATIVE_DOCKER_IMAGE, generator_harness, native_metadata
    selected_harness = generator_harness(settings.get("OPENAI_MODEL", ""))
    result["generator_harness"] = selected_harness
    if generator_runtime == "local":
        metadata=native_metadata(selected_harness)
        label = {'codex':'Codex','claude-code':'Claude Code'}.get(selected_harness,selected_harness)
        variable = metadata['env']
        executable = settings.get(variable) or metadata['binary']
        if not shutil.which(executable):
            errors.append("Generator " + label + " executable missing: " + variable)
        else:
            version = probe("Generator " + label, [executable, "--version"])
            result["claude" if selected_harness == "claude-code" else "codex"] = version or "unavailable"
            expected = metadata['version']
            import re
            if version and not re.search(r'(?<![\w.])'+re.escape(expected)+r'(?![\w.])',version):
                errors.append("Install the released " + label + " CLI version " + expected)

    images = []
    if args.runtime == "docker":
        images.append(args.image)
    if generator_runtime == "docker":
        images.append((settings.get("GENERATOR_CLAUDE_DOCKER_IMAGE") or CLAUDE_DOCKER_IMAGE) if selected_harness == "claude-code"
                      else (settings.get("GENERATOR_DOCKER_IMAGE") or "3dbench-codex:0.163.0") if selected_harness=='codex'
                      else settings.get('GENERATOR_NATIVE_DOCKER_IMAGE') or NATIVE_DOCKER_IMAGE)
    if images:
        docker = settings.get("GENERATOR_DOCKER_BIN") or "docker"
        if not shutil.which(docker):
            errors.append("Docker executable missing")
        elif probe("Docker daemon", [docker, "info", "--format", "{{.ServerVersion}}"]):
            for image in dict.fromkeys(images):
                probe(
                    "Required Docker image " + image,
                    [docker, "image", "inspect", image],
                )
    if not shutil.which("bwrap"):
        errors.append("bubblewrap missing: install bubblewrap (bwrap)")
    result["api_connectivity"] = "not_checked"
    return result
