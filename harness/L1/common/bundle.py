"""Bounded text transport for multi-file L1 submissions in read-only generation."""

from __future__ import annotations

import ast
import base64
import binascii
import json
import re
from pathlib import Path
from typing import Any

from src.generator.client import extract_python_source

from .attempt_log import write_json
from .submission import MANIFEST_NAME, _relative, validate_submission

BUNDLE_PROTOCOL = "l1-submission-bundle-v1"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_BUNDLE_FILES = 128

BUNDLE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["protocol", "entrypoint", "files", "runtime", "dependencies", "run_instructions"],
    "properties": {
        "protocol": {"type": "string", "enum": [BUNDLE_PROTOCOL]},
        "entrypoint": {"type": "string"},
        "files": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["path", "encoding", "content"],
            "properties": {
                "path": {"type": "string"},
                "encoding": {"type": "string", "enum": ["utf-8", "base64"]},
                "content": {"type": "string"},
            },
        }},
        "runtime": {"type": "string"},
        "dependencies": {"type": "array", "items": {"type": "string"}},
        "run_instructions": {"type": "string"},
    },
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key in submission bundle")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("Non-finite JSON value in submission bundle")


def decode_response(raw: str, *, allow_prefixed_bundle: bool = False) -> tuple[str, dict[str, Any] | None]:
    """Decode a bundle or a legacy script; malformed JSON never becomes code."""
    if len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ValueError("Model response exceeds the 16 MiB transport limit")
    content = raw.strip().lstrip("\ufeff")
    if allow_prefixed_bundle:
        # A single explicit JSON fence may be surrounded by commentary. Only
        # the bytes inside that fence are interpreted; never reconstruct JSON.
        fences = list(re.finditer(r'(?ms)^```json[ \t]*\n(.*?)\n```[ \t]*(?:\n|$)', content))
        if len(fences) == 1:
            before, after = content[:fences[0].start()], content[fences[0].end():]
            if '```' not in before + after and not re.search(r'(?m)^\s*\{', before + after):
                content = fences[0].group(1).strip()
    if allow_prefixed_bundle and not content.startswith(("{", "```")):
        # Recover only a complete JSON object occupying the remainder of the
        # final response. All schema, source and path checks below still apply.
        # Do not search inside Python fences or reconstruct truncated JSON.
        start = re.search(r'(?m)^[ \t]*\{', content)
        if start:
            content = content[start.start():].strip()
            if content.endswith("```"):
                content = content[:-3].rstrip()
    is_json_fence = content.startswith("```json")
    if is_json_fence:
        if not content.endswith("```"):
            raise ValueError("Malformed JSON bundle fence")
        content = content[len("```json"): -3].strip()
    if not is_json_fence and not content.startswith("{"):
        return extract_python_source(raw), None
    bundle = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    if not isinstance(bundle, dict) or set(bundle) != set(BUNDLE_SCHEMA["required"]):
        raise ValueError("Submission bundle must have exactly the declared protocol fields")
    if bundle["protocol"] != BUNDLE_PROTOCOL:
        raise ValueError("Unsupported submission bundle protocol")
    entrypoint = _relative(bundle["entrypoint"], "entrypoint").as_posix()
    items = bundle["files"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BUNDLE_FILES:
        raise ValueError("Submission bundle must contain 1 to 128 files")
    files: dict[str, bytes] = {}
    total = 0
    for item in items:
        if not isinstance(item, dict) or set(item) != {"path", "encoding", "content"}:
            raise ValueError("Invalid bundle file fields")
        name = _relative(item["path"], "bundle file").as_posix()
        if name in files:
            raise ValueError("Duplicate bundle file path")
        if not isinstance(item["content"], str):
            raise TypeError("Bundle content must be a string")
        if item["encoding"] == "utf-8":
            data = item["content"].encode("utf-8")
        elif item["encoding"] == "base64":
            try:
                data = base64.b64decode(item["content"], validate=True)
            except (ValueError, binascii.Error) as error:
                raise ValueError("Invalid base64 file in bundle") from error
        else:
            raise ValueError("Unsupported bundle file encoding")
        total += len(data)
        if total > MAX_RESPONSE_BYTES:
            raise ValueError("Decoded bundle exceeds the 16 MiB transport limit")
        if name.lower().endswith(".py") and data:
            # Check syntax without executing or rewriting submitted bytes.
            try:
                ast.parse(data.decode("utf-8"), filename=name)
            except SyntaxError as error:
                raise ValueError(f"Invalid Python source in bundle: {name}") from error
        files[name] = data
    if entrypoint not in files or not entrypoint.lower().endswith(".py"):
        raise ValueError("Bundle must include its Python entrypoint")
    instructions = bundle["run_instructions"]
    if not isinstance(instructions, str) or not instructions.strip() or len(instructions) > 8192:
        raise ValueError("Bundle requires nonempty bounded run_instructions")
    runtime = bundle["runtime"]
    if not isinstance(runtime, str) or not runtime.strip() or len(runtime) > 256:
        raise ValueError("Bundle requires a short nonempty runtime")
    dependencies = bundle["dependencies"]
    if (not isinstance(dependencies, list) or len(dependencies) > 128
            or any(not isinstance(value, str) or not value.strip() or len(value) > 256 for value in dependencies)):
        raise ValueError("Bundle dependencies must be bounded nonempty strings")
    normalized = {
        "protocol": BUNDLE_PROTOCOL,
        "manifest": {
            "schema_version": 1, "entrypoint": entrypoint, "files": list(files),
            "runtime": runtime, "dependencies": dependencies, "run_instructions": instructions,
        },
        "files": files,
    }
    return extract_python_source(files[entrypoint].decode("utf-8")), normalized


def materialize_bundle(bundle: dict[str, Any], destination: Path, *, reserved_outputs: tuple[str, ...], entrypoint_policy: str) -> None:
    """Write only into a fresh attempt-owned directory; never the input tree."""
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in bundle["files"].items():
        relative = _relative(name, "bundle file")
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    write_json(destination / MANIFEST_NAME, bundle["manifest"])
    validate_submission(destination, reserved_outputs=reserved_outputs, entrypoint_policy=entrypoint_policy)


def delivery_prompt(task_id: str) -> str:
    entrypoint = "The entrypoint must be solution.py." if task_id == "L1/CodeEdit" else "Declare any safe Python entrypoint; nested packages are supported."
    return f"""You are an expert Blender Python scene author using Blender 5.2.1.
Return exactly one JSON object conforming to l1-submission-bundle-v1, not prose or Markdown.
The object has protocol, entrypoint, files, runtime, dependencies, run_instructions.
Each files item has path (safe relative path), encoding (utf-8 or base64), and content.
Include the complete source of the entrypoint and every helper/resource it needs.
{entrypoint} Include concise instructions for running it in Blender from the submission root.
List runtime dependencies for audit; the harness will NOT install packages or execute shell instructions.
Return the files as text in this response: the model workspace is read-only, so do not try to write files.
The harness constructs submission_manifest.json itself; do not include it or generated scene artifacts in files.
There are at most 128 files and 16 MiB of response/decoded data; Python files must be UTF-8 source.

The read-only working directory contains only declared model-visible task inputs.
Read only these files, retaining input/... relative paths. Do not search outside the working
directory, access the network, download assets, or rely on undeclared files.
The harness starts Blender factory-empty, runs your declared entrypoint with the submission root
as current directory, and saves scene.blend. Do not save scene.blend yourself. Explicitly open
an input .blend if the task requires editing it. Generate scene.glb/other requested outputs
in Path.cwd(), not next to a nested entrypoint. Read bundled resources relative to __file__;
read task inputs relative to Path.cwd(). Nested identifier paths support package-relative imports.

Create real editable geometry, not reference planes or fake material holes. Make the required
geometry, hierarchy, materials, lighting, animation and exports deterministic. Use BLENDER_EEVEE
(not BLENDER_EEVEE_NEXT), or CYCLES with CPU. Create a World when scene.world is None;
do not use legacy scene.eevee properties. Insert keyframes directly; avoid legacy action.fcurves
because Blender 5.2 uses layered/slotted Actions.
"""
