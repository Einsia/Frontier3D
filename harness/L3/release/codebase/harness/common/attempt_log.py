from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any

def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
