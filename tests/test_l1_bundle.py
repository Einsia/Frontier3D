from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

from harness.L1.common import bundle, pipeline, runner
from harness.L1.common.blender_executor import Execution
from harness.L1.common.codex_invoker import run_once
from harness.L1.common.submission import stage_submission
from src.generator.client import GeneratorConfig, GeneratorError


def payload(entrypoint="assembly/build.py"):
    return {
        "protocol": bundle.BUNDLE_PROTOCOL, "entrypoint": entrypoint,
        "files": [
            {"path": entrypoint, "encoding": "utf-8", "content": "from assembly.parts import value\n"},
            {"path": "assembly/parts.py", "encoding": "utf-8", "content": "value = 3\n"},
            {"path": "assembly/__init__.py", "encoding": "utf-8", "content": ""},
            {"path": "asset.bin", "encoding": "base64", "content": base64.b64encode(b"\x00\xff").decode()},
            {"path": "README.txt", "encoding": "utf-8", "content": "Run the declared entrypoint in Blender."},
        ],
        "runtime": "Blender Python", "dependencies": ["bpy (bundled)"],
        "run_instructions": "Run from the submission root; do not install external packages.",
    }


def test_bundle_preserves_bytes_empty_package_and_instructions(tmp_path):
    raw = json.dumps(payload())
    source, value = bundle.decode_response(raw)
    assert source.startswith("from assembly.parts")
    assert bundle.decode_response("```json\n" + raw + "\n```") == (source, value)
    bundle.materialize_bundle(value, tmp_path / "decoded", reserved_outputs=("scene.blend", "scene.glb"), entrypoint_policy="declared_python")
    metadata = stage_submission(tmp_path / "decoded", tmp_path / "frozen")
    assert (tmp_path / "frozen/asset.bin").read_bytes() == b"\x00\xff"
    assert (tmp_path / "frozen/assembly/__init__.py").read_bytes() == b""
    assert metadata["entrypoint_mode"] == "module"
    assert metadata["run_instructions"] == payload()["run_instructions"]


@pytest.mark.parametrize("source", ["pass\n", "```python\npass\n```"])
def test_legacy_single_python_response_is_still_accepted(source):
    assert bundle.decode_response(source) == ("pass\n", None)


def test_prefixed_bundle_opt_in_preserves_source_and_rejects_trailing_content():
    raw = json.dumps(payload())
    expected = bundle.decode_response(raw)
    assert bundle.decode_response('Here is the complete bundle.\n\n'+raw,
                                  allow_prefixed_bundle=True) == expected
    assert bundle.decode_response('Here is the complete bundle.\n```json\n'+raw+'\n```',
                                  allow_prefixed_bundle=True) == expected
    assert bundle.decode_response('Complete bundle:\n```json\n'+raw+'\n```\nExplanation after submission.',
                                  allow_prefixed_bundle=True) == expected
    with pytest.raises(GeneratorError):
        bundle.decode_response('Here is the complete bundle.\n'+raw)
    for suffix in ['\n'+raw, '\nAdditional explanation', 'broken']:
        with pytest.raises(ValueError):
            bundle.decode_response('Here is the complete bundle.\n'+raw+suffix,
                                   allow_prefixed_bundle=True)
    unsafe = payload('../escape.py')
    with pytest.raises(ValueError):
        bundle.decode_response('Here is the complete bundle.\n'+json.dumps(unsafe),
                               allow_prefixed_bundle=True)


@pytest.mark.parametrize("bad", [
    "protocol", "unknown", "missing", "empty", "many", "duplicate", "traversal", "absolute",
    "backslash", "normalized_alias", "reserved", "invalid_base64", "encoding", "entry_missing",
    "syntax", "fenced_file", "empty_entry", "instructions", "runtime", "dependencies",
])
def test_invalid_bundles_never_fall_back_to_python(tmp_path, bad):
    value = payload()
    if bad == "protocol": value["protocol"] = "future-version"
    elif bad == "unknown": value["extra"] = True
    elif bad == "missing": value.pop("runtime")
    elif bad == "empty": value["files"] = []
    elif bad == "many": value["files"] *= 30
    elif bad == "duplicate": value["files"].append(value["files"][0])
    elif bad in {"traversal", "absolute", "backslash", "normalized_alias", "reserved"}:
        value["files"][-1]["path"] = {"traversal": "../escape", "absolute": "/escape", "backslash": "a\\b", "normalized_alias": "a//b", "reserved": "configuration/fake.json"}[bad]
    elif bad == "invalid_base64": value["files"][3]["content"] = "%%%"
    elif bad == "encoding": value["files"][0]["encoding"] = "pickle"
    elif bad == "entry_missing": value["entrypoint"] = "not-delivered.py"
    elif bad == "syntax": value["files"][1]["content"] = "this is invalid python !"
    elif bad == "fenced_file": value["files"][1]["content"] = "```python\npass\n```"
    elif bad == "empty_entry": value["files"][0]["content"] = ""
    elif bad == "instructions": value["run_instructions"] = ""
    elif bad == "runtime": value["runtime"] = None
    elif bad == "dependencies": value["dependencies"] = [False]
    with pytest.raises((ValueError, TypeError, RuntimeError)):
        _, decoded = bundle.decode_response(json.dumps(value))
        bundle.materialize_bundle(decoded, tmp_path / "decoded", reserved_outputs=("scene.blend", "scene.glb"), entrypoint_policy="declared_python")
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("raw", ['{"protocol": "a", "protocol": "b"}', '{"x":NaN}', '{broken', '```json\n{}'])
def test_invalid_json_is_not_interpreted_as_a_python_dict(raw):
    with pytest.raises(ValueError):
        bundle.decode_response(raw)


def test_response_and_file_count_limits_are_enforced(monkeypatch):
    monkeypatch.setattr(bundle, "MAX_RESPONSE_BYTES", 32)
    with pytest.raises(ValueError, match="transport limit"):
        bundle.decode_response(json.dumps(payload()))


def _fake_cli(tmp_path, value):
    response = tmp_path / "model-response.json"
    response.write_text(json.dumps(value))
    script = tmp_path / "codex-fixture"
    script.write_text(f"#!{sys.executable}\n" +
        "import json, pathlib, sys\n"
        "args = sys.argv\n"
        "assert args[args.index('--sandbox') + 1] == 'read-only'\n"
        "schema = json.loads(pathlib.Path(args[args.index('--output-schema') + 1]).read_text())\n"
        "assert schema['properties']['protocol']['enum'] == ['l1-submission-bundle-v1']\n"
        f"source = pathlib.Path({str(response)!r})\n"
        "pathlib.Path(args[args.index('--output-last-message') + 1]).write_bytes(source.read_bytes())\n"
        "print('fixture-cli-called')\n")
    script.chmod(0o755)
    return GeneratorConfig(api_key="fixture", base_url="https://example.invalid/v1", model="fixture",
                           codex_binary=str(script), max_attempts=1)


def test_invoker_uses_read_only_schema_and_keeps_input_workspace_unchanged(tmp_path):
    config = _fake_cli(tmp_path, payload())
    work = tmp_path / "workspace"
    work.mkdir()
    (work / "input.txt").write_text("unchanged")
    result = run_once(config, "public task", work, tmp_path / "last-message.json", 3, delivery_format="bundle")
    assert result.status == "success" and result.bundle["protocol"] == bundle.BUNDLE_PROTOCOL
    assert list(work.iterdir()) == [work / "input.txt"]
    assert (work / "input.txt").read_text() == "unchanged"


