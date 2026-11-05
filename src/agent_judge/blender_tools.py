"""Small stdio MCP broker for fixed Blender tools; stdlib only.

Inputs, worker and audit ledger live outside the judge's writable workspace.
The model supplies JSON parameters, never executable Blender/Python code.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def slots(budget):
    return [
        f"{role}/judge_generated/{i:03d}.{ext}"
        for role in ("candidate", "reference")
        for i in range(1, budget + 1)
        for ext in ("json", "png")
    ]


def tool_schema(scenes, render=False):
    properties = {
        "scene": {"type": "string", "enum": scenes},
        "purpose": {"type": "string", "minLength": 1, "maxLength": 500},
        "frame": {"type": "integer", "minimum": 1, "maximum": 10000},
    }
    if render:
        properties.update(
            {
                "camera": {
                    "type": "string",
                    "description": "Existing camera name; omit for a custom view.",
                },
                "azimuth": {"type": "number", "minimum": -360, "maximum": 360},
                "elevation": {"type": "number", "minimum": -90, "maximum": 90},
                "projection": {"enum": ["ORTHO", "PERSP"], "type": "string"},
                "lighting": {"enum": ["authored", "neutral"], "type": "string"},
                "focus_objects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 50,
                },
                "target": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "scale": {"type": "number", "minimum": 0.05, "maximum": 10},
                "distance": {"type": "number", "minimum": 0.1, "maximum": 20},
                "resolution": {"type": "integer", "minimum": 256, "maximum": 1024},
            }
        )
    if not render:
        properties.update(
            {
                "offset": {"type": "integer", "minimum": 0, "maximum": 100000},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            }
        )
    return {
        "type": "object",
        "properties": properties,
        "required": ["scene", "purpose"],
        "additionalProperties": False,
    }


def validate(value, schema):
    """Validate the small schema subset used here without installing deps in the MCP venv."""
    kind = schema.get("type")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "number": type(value) in (int, float) and math.isfinite(value),
    }
    if kind and not valid[kind]:
        raise ValueError("Invalid parameter type")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Parameter outside allowed values")
    if kind == "object":
        if set(value) - set(schema["properties"]) or set(
            schema.get("required", [])
        ) - set(value):
            raise ValueError("Missing or unknown parameters")
        for key, item in value.items():
            validate(item, schema["properties"][key])
    if kind in ("number", "integer") and (
        value < schema.get("minimum", -math.inf)
        or value > schema.get("maximum", math.inf)
    ):
        raise ValueError("Parameter outside limits")
    if kind in ("array", "string") and (
        len(value) < schema.get("minItems", schema.get("minLength", 0))
        or len(value) > schema.get("maxItems", schema.get("maxLength", math.inf))
    ):
        raise ValueError("Parameter length outside limits")
    if kind == "array":
        for item in value:
            validate(item, schema["items"])


class Broker:
    def __init__(self, config):
        self.config = config
        self.private = Path(config["private"])
        self.workspace = Path(config["workspace"])
        self.ledger_path = self.private / "generated" / "manifest.json"
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger = {
            "calls": [],
            "sha256": {},
            "sources": config["scenes"],
            "worker_sha256": sha(config["worker"]),
        }
        if self.ledger_path.exists():
            self.ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        else:
            # A native audit can finish from original views without rendering.
            # Persist the empty, bound ledger so that this remains verifiable.
            self.ledger_path.write_text(json.dumps(self.ledger, ensure_ascii=False, indent=2), encoding="utf-8")

    def tools(self):
        return [
            {
                "name": name,
                "description": description,
                "inputSchema": tool_schema(
                    list(self.config["scenes"]), name == "render_view"
                ),
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                },
            }
            for name, description in (
                (
                    "inspect_scene",
                    "Read objects, transforms, mesh counts, materials and camera names at a frame. Names/bounds do not prove geometry.",
                ),
                (
                    "render_view",
                    "Render and return an IMAGE of the unchanged .blend. Choose authored camera or custom azimuth/elevation, frame and object close-up. Focus only frames objects; never hides other geometry. Outputs are registered evidence.",
                ),
            )
        ]

    def call(self, name, args):
        started = time.monotonic()
        if name not in {"inspect_scene", "render_view"}:
            raise ValueError("Unknown tool")
        validate(args, tool_schema(list(self.config["scenes"]), name == "render_view"))
        if len(self.ledger["calls"]) >= self.config["budget"]:
            raise ValueError(
                "Blender tool budget exhausted; report remaining checks unobservable"
            )
        number = len(self.ledger["calls"]) + 1
        relative = args["scene"]
        role = relative.split("/")[0]
        source = self.private / "inputs" / relative
        if sha(source) != self.config["scenes"][relative]:
            raise ValueError("Native input changed")
        stem = f"{role}/judge_generated/{number:03d}"
        output = self.private / "generated" / stem
        output.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "tool": name,
            "arguments": args,
            "source_sha256": sha(source),
            "status": "running",
            "files": [],
        }
        self.ledger["calls"].append(record)
        content = []
        try:
            request = {
                "source": str(source),
                "asset_root": str(self.private / "inputs" / role),
                "output": str(output),
                "arguments": args,
                "action": "render" if name == "render_view" else "inspect",
            }
            request_path = self.private / f"request-{number:03d}.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            command = [
                self.config["blender"],
                "--background",
                "--factory-startup",
                "--disable-autoexec",
                "--threads",
                "2",
                "--python-exit-code",
                "1",
                "--python",
                self.config["worker"],
                "--",
                str(request_path),
            ]
            # No inherited provider keys, Python paths, user Blender startup or proxies.
            env = {
                k: v
                for k, v in os.environ.items()
                if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG"}
            }
            env.update(
                HOME=str(self.private),
                USERPROFILE=str(self.private),
                BLENDER_USER_CONFIG=str(self.private / "blender-config"),
            )
            process = subprocess.run(
                command,
                cwd=self.private,
                env=env,
                capture_output=True,
                timeout=self.config["timeout"],
                check=False,
            )
            log = output.with_suffix(".log")
            log.write_bytes(process.stdout + process.stderr)
            if process.returncode:
                raise RuntimeError(
                    "Blender failed; input may have missing assets or unsupported data (see tool log)"
                )
            extensions = ["json", "png"] if name == "render_view" else ["json"]
            for ext in extensions:
                path = f"{stem}.{ext}"
                private_file = self.private / "generated" / path
                destination = self.workspace / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                if (
                    destination.exists()
                    or destination.is_symlink()
                    or not destination.resolve().is_relative_to(
                        self.workspace.resolve()
                    )
                ):
                    raise ValueError(
                        "Generated evidence destination is occupied or outside workspace"
                    )
                shutil.copyfile(private_file, destination)
                self.ledger["sha256"][path] = sha(private_file)
                record["files"].append(path)
            facts = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
            objects = facts.pop("objects", [])
            facts["object_count"] = len(objects)
            if name == "inspect_scene":
                offset, limit = args.get("offset", 0), args.get("limit", 100)
                facts["objects"] = objects[offset : offset + limit]
                facts["next_offset"] = (
                    offset + limit if offset + limit < len(objects) else None
                )
                facts["cameras"] = [o["name"] for o in objects if o["type"] == "CAMERA"]
            content.append(
                {
                    "type": "text",
                    "text": json.dumps(
                        {"evidence": record["files"], "facts": facts},
                        ensure_ascii=False,
                    ),
                }
            )
            if name == "render_view":
                image_path=output.with_suffix('.png');mime='image/png'
                transport_mode=self.config.get('image_transport')
                if transport_mode in {'lossless_webp','preview_webp'}:
                    try:
                        from image_codec import encode_lossless_webp, encode_preview_webp
                    except ImportError:
                        from .image_codec import encode_lossless_webp, encode_preview_webp
                    wire=self.private/'generated/transport'/f'{number:03d}.webp'
                    proof=(encode_preview_webp if transport_mode=='preview_webp' else encode_lossless_webp)(image_path,wire)
                    record['image_transport']={'mode':transport_mode,'resized':False,'lossy':False,
                        'source_evidence':f'{stem}.png','source_sha256':sha(image_path),
                        'archive':str(wire.relative_to(self.private/'generated')),'provided_sha256':sha(wire),**proof}
                    image_path=wire;mime='image/webp'
                content.append(
                    {
                        "type": "image",
                        "mimeType": mime,
                        "data": base64.b64encode(
                            image_path.read_bytes()
                        ).decode(),
                    }
                )
            record["status"] = "success"
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            record["status"] = "failed"
            record["error"] = str(error)[:400]
            content = [
                {
                    "type": "text",
                    "text": record["error"]
                    + "; tool failure is not proof that the candidate is wrong.",
                }
            ]
        finally:
            record["seconds"] = round(time.monotonic() - started, 3)
            self.ledger_path.write_text(
                json.dumps(self.ledger, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return {"content": content, "isError": record["status"] != "success"}


def main():
    broker = Broker(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if "id" not in message:
                continue
            method = message["method"]
            if method == "initialize":
                result = {
                    "protocolVersion": message["params"]["protocolVersion"],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "judge-blender", "version": "1.0"},
                    "instructions": "Inspect scene then render chosen views. Images are returned directly. Cite returned evidence paths. Tools cannot edit source geometry or execute supplied code. Tool failures imply missing evidence, not candidate failure.",
                }
            elif method == "tools/list":
                result = {"tools": broker.tools()}
            elif method == "tools/call":
                params = message["params"]
                try:
                    result = broker.call(params["name"], params.get("arguments", {}))
                except (ValueError, OSError) as error:
                    result = {
                        "isError": True,
                        "content": [{"type": "text", "text": str(error)}],
                    }
            elif method == "ping":
                result = {}
            else:
                print(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "error": {"code": -32601, "message": "Method not found"},
                        }
                    ),
                    flush=True,
                )
                continue
            print(
                json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}),
                flush=True,
            )
        except (ValueError, KeyError, TypeError):
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32600, "message": "Invalid request"},
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
