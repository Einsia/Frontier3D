"""Relocate frozen scoring contracts into a run, without private workspace paths."""
from pathlib import Path
import hashlib
import json
import os

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "configs/release"


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def env_path():
    return Path(os.environ.get("THREEDBENCH_ENV_FILE", ROOT / ".env")).resolve()


def judge_settings():
    from dotenv import dotenv_values
    return {**os.environ, **{k:v for k,v in dotenv_values(env_path()).items() if v is not None}}


def judge_key():
    s = judge_settings()
    return s.get("VLM_API_KEY") or s.get("OPENAI_DATA_API_KEY") or s.get("OPENAI_API_KEY", "")


def judge_model():
    return judge_settings().get("VLM_MODEL") or "gpt-6-astra"


def blender_path():
    value = os.environ.get("THREEDBENCH_BLENDER") or judge_settings().get("THREEDBENCH_BLENDER")
    path = Path(value).expanduser() if value else ROOT / "third_party/blender-5.2.1-linux-x64/blender"
    if not path.is_absolute():
        path = env_path().parent / path
    return path.resolve()


def resource(slot):
    index = json.loads((TEMPLATES / "index.json").read_text())
    return Path(os.environ["THREEDBENCH_RESOURCE_ROOT"]) / index["slots"][slot]


def read_public_methods():
    return json.loads(resource("published_methods").read_text())


def prepare(destination):
    """Resolve the acyclic contract graph and recompute only packaging bindings.

    Algorithms, criteria and weights are unchanged. Runtime copies are absolute
    and hash-bound so the retained source code works from a relocated checkout.
    """
    destination = Path(destination).resolve()
    index = json.loads((TEMPLATES / "index.json").read_text())
    destination.mkdir(parents=True, exist_ok=True)
    visiting = set()
    ready = set()

    def resolve_token(value):
        if value.startswith("@repo/"):
            path = ROOT / value.removeprefix("@repo/")
            if not path.exists():
                raise FileNotFoundError("Missing release dependency: " + str(path))
            return str(path)
        if value.startswith("@resource/"):
            key = value.removeprefix("@resource/")
            materialize(key)
            return str(destination / key)
        if value.startswith("@filehash:"):
            return _sha(resolve_token(value.removeprefix("@filehash:")))
        return value

    def resolve(value):
        if isinstance(value, str):
            return resolve_token(value)
        if isinstance(value, list):
            return [resolve(v) for v in value]
        if isinstance(value, dict):
            result = {k:resolve(v) for k,v in value.items()}
            if result.get("sha256") == "@recompute":
                result["sha256"] = _sha(result["path"])
            return result
        return value

    def materialize(key):
        if key in ready:
            return
        if key in visiting:
            raise ValueError("Cyclic release dependency: " + key)
        visiting.add(key)
        source = TEMPLATES / key
        if not source.is_file():
            # Directory references are resolved after individual templates.
            if any(k.startswith(key + "/") for k in index["json_templates"]):
                for child in index["json_templates"]:
                    if child.startswith(key + "/"):
                        materialize(child)
                visiting.remove(key)
                ready.add(key)
                return
            raise FileNotFoundError("Missing release resource " + key)
        target = destination / key
        target.parent.mkdir(parents=True, exist_ok=True)
        if key in index["json_templates"]:
            obj = resolve(json.loads(source.read_text()))
            content = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode()
        else:
            content = source.read_bytes()
        if target.exists():
            if target.read_bytes() != content:
                raise ValueError("Run resource changed: " + key)
        else:
            target.write_bytes(content)
        visiting.remove(key)
        ready.add(key)

    for key in index["json_templates"] + index.get("binary_files", []):
        materialize(key)
    os.environ["THREEDBENCH_RESOURCE_ROOT"] = str(destination)
    return destination
