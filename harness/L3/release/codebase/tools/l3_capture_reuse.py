"""Reuse only completed, identical-plan, hash-verified independent episodes."""
import json
import shutil
from pathlib import Path
from harness.L3.MinecraftVillage.protocol import digest

def reuse_episode(previous, archived, destination, key, plan):
    archived, destination = Path(archived), Path(destination)
    if previous.get("episodes", {}).get(key, {}).get("status") != "measured":
        return False
    source = archived / key
    if not (source / "completed.json").is_file():
        return False
    if not json.loads((source / "completed.json").read_text()).get("completed"):
        return False
    if not (source / "plan.json").is_file() or json.loads((source / "plan.json").read_text()) != plan:
        return False
    prefix = "workspace/algorithm-v1/" + key + "/"
    hashes = previous.get("evidence_sha256", {})
    files = [p for p in source.rglob("*") if p.is_file() and p.suffix in {".json", ".png"}]
    if not files:
        return False
    expected = {name[len(prefix):]: value for name, value in hashes.items() if name.startswith(prefix)}
    if set(expected) != {str(p.relative_to(source)) for p in files}:
        raise ValueError("Retry episode evidence inventory mismatch: " + key)
    for path in files:
        if digest(path) != expected[str(path.relative_to(source))]:
            raise ValueError("Retry episode evidence hash mismatch: " + key)
    shutil.copytree(source, destination)
    return True
