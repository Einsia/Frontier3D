"""Verify active L1/L2 credits, source identity mappings and retained notice hashes."""

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(root=ROOT):
    root = Path(root).resolve()
    index = json.loads((root / "docs/reference/task-attribution-index.json").read_text())
    mapping = json.loads((root / "configs/release/task-id-map.json").read_text())
    expected = {
        r["new_task_id"]: r["old_task_id"]
        for r in mapping["tasks"]
        if r["level"] in {"L1", "L2"}
    }
    rows = index["tasks"]
    if (
        len(rows) != index["task_count"]
        or len(rows) != len(expected)
        or {r["task_id"] for r in rows} != set(expected)
    ):
        raise ValueError("Attribution population does not match active L1/L2 tasks")

    def checked(name, expected_hash):
        path = root / name
        if (
            Path(name).is_absolute()
            or not path.resolve().is_relative_to(root)
            or path.is_symlink()
        ):
            raise ValueError("Unsafe attribution evidence path: " + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            raise ValueError("Attribution file changed: " + name)
        return path

    paths = set()
    notices = 0
    for row in rows:
        tid = row["task_id"]
        if (
            row["source_task_id"] != expected[tid]
            or row["credits"] != "data/3dbench/tasks/" + tid + "/attribution/CREDITS"
        ):
            raise ValueError("Credits task identity differs: " + tid)
        credits = checked(row["credits"], row["sha256"]).read_text()
        if not credits.startswith(
            "Task: " + tid + "\nOriginal source task ID: " + expected[tid] + "\n"
        ):
            raise ValueError("Credits header identity differs: " + tid)
        if not row["sources"]:
            raise ValueError("Credits need original attribution evidence: " + tid)
        for evidence in row["sources"]:
            path = checked(evidence["path"], evidence["sha256"])
            if not path.is_relative_to(root / "data/3dbench/tasks" / tid):
                raise ValueError("Attribution evidence belongs to another task")
            if (
                evidence["use"] == "verbatim_notice"
                and path.read_text(encoding="utf-8-sig").strip() not in credits
            ):
                raise ValueError("Original source notice omitted: " + tid)
            notices += 1
        paths.add(row["credits"])
    checked("docs/en/licenses.md", index["license_summary_sha256"])
    with (root / "docs/reference/asset-attribution-index.csv").open(newline="") as stream:
        listed = {r["attribution_file"] for r in csv.DictReader(stream)}
    if not paths <= listed or any(not (root / name).is_file() for name in listed):
        raise ValueError("Attribution file index is incomplete or has missing files")
    return {"tasks": len(rows), "source_records": notices, "status": "passed"}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
