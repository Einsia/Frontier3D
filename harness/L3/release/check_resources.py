"""Verify the complete portable L3 source/input/spec graph without UE or API calls."""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = HERE / "codebase"
REPO = HERE.parents[2]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_resources():
    index = json.loads((HERE / "task-index.json").read_text())
    tasks = {}
    for path in (CODE / "tasks/L3").glob("*/task.json"):
        data = json.loads(path.read_text())
        if data.get("execution_status") == "generation_ready":
            if data["key"] in tasks:
                raise ValueError("Duplicate native L3 task: " + data["key"])
            tasks[data["key"]] = path.parent
    if len(index) != 15 or set(tasks) != {row["task_key"] for row in index}:
        raise ValueError("L3 release/native task populations differ")
    locks = json.loads((HERE / "asset-locks/index.json").read_text())["files"]
    for name, expected in locks.items():
        if digest(HERE / "asset-locks" / name) != expected:
            raise ValueError("L3 asset lock changed: " + name)
    catalog_hashes = {
        "models": locks["kenney-suite-20261023/manifest.json"],
        "materials": locks["polyhaven-2k-2026-10-16/manifest.json"],
    }
    voxel = json.loads(
        (HERE / "asset-locks/kenney-voxel-1.0-tiles/manifest.json").read_text()
    )
    models = json.loads(
        (HERE / "asset-locks/kenney-suite-20261023/manifest.json").read_text()
    )
    if locks["archives/voxel-pack.zip"] != voxel["archive_sha256"] or any(
        locks["archives/" + pack["id"] + ".zip"] != pack["archive_sha256"]
        for pack in models["packs"]
    ):
        raise ValueError("Bundled Kenney archives differ from the original manifests")
    references = 0
    for row in index:
        task = tasks[row["task_key"]]
        public = REPO / row["path"]
        harbor = json.loads((public / "package-manifest.json").read_text())
        harbor_files = {
            p.relative_to(public).as_posix()
            for p in public.rglob("*")
            if p.is_file() and p.name != "package-manifest.json"
        }
        if harbor_files != set(harbor["files"]):
            raise ValueError("Harbor package inventory differs: " + row["task_key"])
        for name, expected in harbor["files"].items():
            path = public / name
            if (
                not path.resolve().is_relative_to(public.resolve())
                or digest(path) != expected
            ):
                raise ValueError("Harbor packaged dependency changed: " + name)
        for path, expected in (
            (public / "instruction.md", row["instruction_sha256"]),
            (task / "instruction.md", row["source_instruction_sha256"]),
        ):
            if digest(path) != expected:
                raise ValueError("L3 instruction changed: " + str(path))
        manifest = json.loads((task / "package-manifest.json").read_text())
        actual = {
            p.relative_to(task).as_posix()
            for p in task.rglob("*")
            if p.is_file()
            and p.name != "package-manifest.json"
            and "__pycache__" not in p.parts
        }
        if actual != set(manifest["files"]):
            raise ValueError("L3 package file inventory differs: " + row["task_key"])
        for name, expected in manifest["files"].items():
            path = task / name
            if (
                not path.resolve().is_relative_to(task.resolve())
                or digest(path) != expected
            ):
                raise ValueError("L3 packaged dependency changed: " + str(path))
        selection = task / "environment/input/asset-selection.json"
        if selection.is_file() and (
            json.loads(selection.read_text())["catalog_sha256"] != catalog_hashes
            or manifest["libraries"] != catalog_hashes
        ):
            raise ValueError("L3 external library lock differs: " + row["task_key"])
        spec = json.loads(
            (HERE / "scoring-specs" / row["task_key"] / "spec.json").read_text()
        )
        if spec["public_task_sha256"] != digest(task / "instruction.md"):
            raise ValueError("L3 rubric instruction binding differs")
        for name, expected in spec["reference_sha256"].items():
            path = task / name
            if (
                Path(name).is_absolute()
                or ".." in Path(name).parts
                or not path.resolve().is_relative_to(task.resolve())
            ):
                raise ValueError(
                    "L3 reference must be relative to its native task: " + name
                )
            if digest(path) != expected:
                raise ValueError("L3 frozen reference changed: " + name)
            references += 1
    return {
        "tasks": len(index),
        "reference_bindings": references,
        "resources": "passed",
    }


if __name__ == "__main__":
    print(json.dumps(verify_resources(), indent=2))
