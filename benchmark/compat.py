"""Small reporting helpers, independent of the private experiment website."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib


def now():
    return datetime.now(timezone.utc).isoformat()


def checked(item):
    path = Path(item["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise ValueError("Evidence changed: " + str(path))
    return path


def classify(run, generation, report):
    if report.get("status") == "scored":
        return "scored"
    if run.get("status") in {"failed", "budget_exhausted"}:
        return "model_failure" if run.get("generation_attempts") else "technical_failure"
    return "technical_failure"
