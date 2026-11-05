"""Regression coverage for a checkout with no maintainer paths or credentials."""

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from benchmark import resources

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "harness/L3/release"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def executable(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o700)
    return path


def test_env_file_blender_relative_path_and_export_precedence(tmp_path, monkeypatch):
    env = tmp_path / "config.env"
    env.write_text("THREEDBENCH_BLENDER=runtime/blender\n")
    monkeypatch.delenv("THREEDBENCH_BLENDER", raising=False)
    monkeypatch.setenv("THREEDBENCH_ENV_FILE", str(env))
    assert resources.blender_path() == tmp_path / "runtime/blender"
    monkeypatch.setenv("THREEDBENCH_BLENDER", str(tmp_path / "exported"))
    assert resources.blender_path() == tmp_path / "exported"


@pytest.fixture
def host_setup(tmp_path):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    executable(binaries / "codex", "echo codex-cli 0.163.0\n")
    executable(binaries / "bwrap", "exit 0\n")
    executable(binaries / "docker", "exit 0\n")
    blender = executable(binaries / "blender", "echo Blender 5.2.1\n")
    env = tmp_path / "config.env"
    env.write_text(
        "OPENAI_BASE_URL=https://generator.invalid/v1\nOPENAI_API_KEY=test-generator-token\n"
        "OPENAI_MODEL=test-model\nVLM_BASE_URL=https://judge.invalid/v1\n"
        "VLM_API_KEY=test-judge-token\nVLM_MODEL=gpt-6-astra\n"
        "GENERATOR_RUNTIME=local\n"
        f"THREEDBENCH_BLENDER={blender}\n"
    )
    return binaries, blender, env


def doctor(host_setup, *args):
    binaries, _, env_file = host_setup
    # A stale inherited provider token must not override credentials in the chosen file.
    env = {
        "PATH": str(binaries),
        "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "OPENAI_DATA_API_KEY": "inherited-stale-provider-token",
    }
    cp = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmark",
            "doctor",
            "--level", "1", "2",
            "--env-file",
            str(env_file),
            *args,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return cp, json.loads(cp.stdout)


def test_doctor_cli_blender_overrides_env_file(host_setup, tmp_path):
    _, _, env_file = host_setup
    env_file.write_text(
        env_file.read_text().replace("THREEDBENCH_BLENDER=", "#THREEDBENCH_BLENDER=")
    )
    selected = executable(tmp_path / "selected-blender", "echo Blender 5.2.1\n")
    cp, result = doctor(host_setup, "--runtime", "local", "--blender", str(selected))
    assert cp.returncode == 0 and not result["errors"]
    assert result["blender"] == "Blender 5.2.1"
    assert (
        "test-generator-token" not in cp.stdout and "test-judge-token" not in cp.stdout
    )


@pytest.mark.parametrize("key", ["OPENAI_API_KEY", "VLM_API_KEY"])
def test_doctor_rejects_placeholder_keys(host_setup, key):
    _, _, env_file = host_setup
    text = env_file.read_text()
    text = "\n".join(
        key + "=replace-with-your-key" if line.startswith(key + "=") else line
        for line in text.splitlines()
    )
    env_file.write_text(text + "\n")
    cp, result = doctor(host_setup, "--runtime", "local")
    assert cp.returncode == 2
    assert any("example value" in e for e in result["errors"])


def test_doctor_missing_docker_image_is_failure(host_setup):
    binaries, _, _ = host_setup
    executable(
        binaries / "docker",
        'case "$1" in\ninfo) echo 29.0; exit 0;;\nimage) exit 1;;\nesac\n',
    )
    cp, result = doctor(host_setup)
    assert cp.returncode == 2
    assert "Required Docker image 3dbench-l1-blender:mvp failed" in result["errors"]


def test_doctor_uses_env_generator_runtime_without_host_codex(host_setup):
    binaries, _, env_file = host_setup
    (binaries / "codex").unlink()
    executable(
        binaries / "docker",
        'case "$1" in\ninfo) echo 29.0;;\nimage) echo image-present;;\nesac\n',
    )
    with env_file.open("a") as stream:
        stream.write("GENERATOR_RUNTIME=docker\n")
    cp, result = doctor(host_setup)
    assert cp.returncode == 0 and result["generator_runtime"] == "docker"
    assert "codex" not in result
    cp, result = doctor(host_setup, "--generator-runtime", "local")
    assert cp.returncode == 2
    assert any("Codex executable missing" in e for e in result["errors"])


def test_resources_only_does_not_require_credentials_or_binaries(host_setup):
    cp, result = doctor(host_setup, "--resources-only")
    assert cp.returncode == 0 and result["l3"]["reference_bindings"] == 23
    assert result["api_calls"] == 0


def test_l3_specs_validate_without_access_outside_checkout():
    code = RELEASE / "codebase"
    # Isolate the duplicate L3 package namespace from the root harness modules.
    script = """
import json,sys
from pathlib import Path
code=Path(sys.argv[1]);sys.path.insert(0,str(code))
from harness.L3.Suite.quality_v5 import validate_task_spec
original=Path.open
allowed=code.parents[2].resolve()
def guarded(path,*args,**kwargs):
 if not path.resolve().is_relative_to(allowed):
  raise AssertionError('Attempt to read outside the published checkout: '+str(path))
 return original(path,*args,**kwargs)
Path.open=guarded
count=0
for path in (code/'tasks/L3').glob('*/task.json'):
 meta=json.loads(path.read_text())
 if meta.get('execution_status')!='generation_ready':continue
 spec=json.loads((code.parent/'scoring-specs'/meta['key']/'spec.json').read_text())
 validate_task_spec(path.parent,spec)
 count+=1
assert count==15
"""
    subprocess.run([sys.executable, "-c", script, str(code)], cwd=ROOT, check=True)


def test_l3_spec_rejects_absolute_reference_even_if_file_exists(tmp_path):
    code = RELEASE / "codebase"
    script = """
import json,sys
from pathlib import Path
code=Path(sys.argv[1]);sys.path.insert(0,str(code))
from harness.L3.Suite.quality_v5 import validate_task_spec
spec=json.loads((code.parent/'scoring-specs/l3-e01/spec.json').read_text())
task=code/'tasks/L3/DuplexHome'
name,sha=next(iter(spec['reference_sha256'].items()))
spec['reference_sha256']={str(task/name):sha}
try:validate_task_spec(task,spec)
except ValueError as error:assert 'task-relative' in str(error)
else:raise AssertionError('Absolute reference accepted')
"""
    subprocess.run([sys.executable, "-c", script, str(code)], cwd=ROOT, check=True)


def test_locked_asset_zip_extraction_and_integrity(tmp_path):
    assets = load("release_assets", RELEASE / "prepare_assets.py")
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("Model.txt", b"fixed asset")
        zipped.writestr("../unlisted.txt", b"unlisted")
    import hashlib

    row = {
        "path": "pack/Model.txt",
        "bytes": 11,
        "sha256": hashlib.sha256(b"fixed asset").hexdigest(),
    }
    root = tmp_path / "assets"
    assets.extract_selected(archive, root, [row], "pack/")
    assert (root / "pack/Model.txt").read_bytes() == b"fixed asset"
    assert not (tmp_path / "unlisted.txt").exists()
    row["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="differs"):
        assets.extract_selected(archive, root, [row], "pack/")
    with pytest.raises(ValueError, match="Unsafe asset path"):
        assets.checked_path(root, "../escape")


def test_locked_download_rejects_changed_bytes_without_final_file(
    tmp_path, monkeypatch
):
    assets = load("release_asset_download", RELEASE / "prepare_assets.py")
    import io

    monkeypatch.setattr(
        assets.urllib.request,
        "urlopen",
        lambda *a, **kw: io.BytesIO(b"changed upstream"),
    )
    target = tmp_path / "downloaded"
    with pytest.raises(ValueError, match="hash differs"):
        assets.download("https://assets.invalid/file", target, "0" * 64)
    assert not target.exists() and not list(tmp_path.glob("*.partial"))


def test_l3_host_doctor_reports_setup_failure_without_traceback():
    cp = subprocess.run(
        [sys.executable, str(RELEASE / "run.py"), "doctor"],
        cwd=ROOT,
        env={"PATH": "", "LANG": "C.UTF-8"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert cp.returncode == 2
    result = json.loads(cp.stdout)
    assert result["release"]["tasks"] == 15
    assert result["errors"] and result["api_calls"] == 0 and not result["ue_launched"]
    assert "Traceback" not in cp.stderr


def test_bundled_kenney_archives_reproduce_frozen_libraries_offline(
    tmp_path, monkeypatch
):
    assets = load("bundled_kenney_assets", RELEASE / "prepare_assets.py")

    def no_network(*args, **kwargs):
        raise AssertionError("Bundled Kenney assets must not require network")

    monkeypatch.setattr(assets.urllib.request, "urlopen", no_network)
    for name, manifest in assets.metadata().items():
        if not name.startswith("kenney"):
            continue
        root = tmp_path / name
        assets.fetch_library(name, manifest, root, 1)
        assert assets.verify_library(name, manifest, root) == len(
            assets.entries(manifest)
        )
