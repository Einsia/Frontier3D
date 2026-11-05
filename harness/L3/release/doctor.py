"""Read-only L3 host preflight; no UE launch or model request."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from check_resources import verify_resources
from prepare_assets import LOCKS, digest, metadata, verify_library
from engine_checks import engine_errors


def check(args):
    result = {"errors": [], "api_calls": 0, "ue_launched": False}
    errors = result["errors"]
    try:
        result["release"] = verify_resources()
    except (OSError, ValueError, KeyError) as error:
        errors.append("Release resources: " + str(error))
    if args.resources_only:
        return result

    def required_path(name):
        value = os.environ.get(name, "")
        if not value or "/absolute/path/" in value or "/private/path/" in value:
            errors.append("Set " + name + " to an existing local path")
            return None
        return Path(value).expanduser().resolve()

    original = required_path("L3_UE_ROOT")
    engine = args.engine.expanduser().resolve() if args.engine else None
    if engine is None:
        errors.append("Supply --engine with a dedicated writable engine copy")
    for label, path in [("L3_UE_ROOT", original), ("--engine", engine)]:
        if path is not None:
            errors.extend(engine_errors(path,label))
    if engine is not None and original is not None and engine == original:
        errors.append("Dedicated engine must differ from L3_UE_ROOT")
    if engine is not None and not os.access(engine, os.W_OK):
        errors.append("Dedicated engine is not writable")

    native = required_path("L3_NATIVE_CLI")
    harness = os.environ.get("L3_GENERATOR_HARNESS", "codex")
    result["generator_harness"] = harness
    policy=json.loads((Path(__file__).resolve().parents[3]/'configs/release/generator-harnesses.json').read_text())
    native_packages={policy['native_names'][key]:(v['package'],v['version'],key) for key,v in policy['cli'].items()}
    if harness not in native_packages:
        errors.append("Unsupported L3_GENERATOR_HARNESS: " + harness)
        native = None
    if native is not None:
        package, expected, label = native_packages[harness]
        try:
            version = json.loads((native / package / "package.json").read_text())[
                "version"
            ]
            if version != expected:
                errors.append("Native " + label + " CLI must be " + expected)
            binary=next(v["binary"] for k,v in policy["cli"].items() if policy["native_names"][k]==harness)
            if not os.access(native / ".bin" / binary, os.X_OK):
                errors.append("Native executable missing: .bin/"+binary)
        except (OSError, ValueError, KeyError):
            errors.append("L3_NATIVE_CLI must contain " + package + "/package.json")

    providers = required_path("L3_PROVIDER_DIR")
    judge = args.provider or os.environ.get("L3_MATRIX_JUDGE_PROVIDER")
    for label, path in [
        ("openai generator provider", providers / "openai.json" if providers else None),
        ("judge provider", Path(judge).expanduser() if judge else None),
    ]:
        try:
            data = json.loads(path.read_text()) if path else {}
            url = urlsplit(data.get("base_url", ""))
            key = data.get("api_key", "")
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or not key
                or any(
                    term in (key + data.get("base_url", "")).lower()
                    for term in ["replace", "example", "your-provider"]
                )
            ):
                raise ValueError("Provider is incomplete")
        except (OSError, ValueError, TypeError, AttributeError):
            errors.append(
                label
                + ": supply a private JSON file with an HTTPS base_url and api_key"
            )

    assets = required_path("L3_ASSET_ROOT")
    if assets is not None:
        for name, manifest in metadata().items():
            try:
                if args.verify_assets:
                    verify_library(name, manifest, assets / name)
                elif digest(assets / name / "manifest.json") != digest(
                    LOCKS / name / "manifest.json"
                ):
                    raise ValueError("Manifest identity differs")
            except (OSError, ValueError):
                errors.append(
                    "Offline library missing or changed: "
                    + name
                    + "; run prepare_assets.py fetch/verify"
                )
    result["asset_check"] = "all_files" if args.verify_assets else "manifests_only"

    def probe(label, command):
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=30, check=False
            )
            if completed.returncode:
                raise ValueError("Failed")
            return True
        except (OSError, subprocess.TimeoutExpired, ValueError):
            errors.append(label + " unavailable or failed (30-second limit)")
            return False

    if not shutil.which("docker"):
        errors.append("Docker executable missing")
    elif probe("Docker daemon", ["docker", "info", "--format", "{{.ServerVersion}}"]):
        image = os.environ.get("L3_UE_IMAGE")
        if not image or "your-local-" in image:
            errors.append("Set L3_UE_IMAGE to the built L3 agent image")
        else:
            probe("L3 Docker image", ["docker", "image", "inspect", image])
    probe("NVIDIA GPU/driver", ["nvidia-smi", "-L"])
    result["api_connectivity"] = "not_checked"
    return result
