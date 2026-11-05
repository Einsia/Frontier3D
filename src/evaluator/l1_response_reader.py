"""Worker that streams one bounded model response and emits a tiny receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from pathlib import Path

PROTOCOL = "l1-response-reader-v1"


def receipt(value: dict) -> None:
    value = {"protocol": PROTOCOL, "pid": os.getpid(), "process_group": os.getpgrp(), **value}
    data = (json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n").encode()
    if len(data) > 4096:
        raise ValueError("oversized response receipt")
    os.write(sys.stderr.fileno(), data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--deadline", type=float, required=True)
    parser.add_argument("--limit", type=int, required=True)
    args = parser.parse_args()
    receipt({"phase": "started", "entered_monotonic": time.monotonic()})
    try:
        if args.limit <= 0:
            raise ValueError("positive response limit required")
        info = args.target.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError("response target is not a regular non-symlink file")
        if info.st_size <= 0 or info.st_size > args.limit:
            raise ValueError("response file size is outside the allowed limit")
        digest, count = hashlib.sha256(), 0
        with args.target.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size) != (info.st_dev, info.st_ino, info.st_size):
                raise ValueError("response changed before read")
            while True:
                if time.monotonic() >= args.deadline:
                    raise TimeoutError("response read exhausted deadline")
                data = stream.read(1024 * 1024)
                if not data:
                    break
                count += len(data)
                if count > args.limit:
                    raise ValueError("response byte limit exceeded")
                pending = memoryview(data)
                while pending:
                    written = os.write(sys.stdout.fileno(), pending)
                    if written <= 0:
                        raise OSError("response pipe made no progress")
                    pending = pending[written:]
                digest.update(data)
            after = os.fstat(stream.fileno())
            if (after.st_dev, after.st_ino, after.st_size) != (info.st_dev, info.st_ino, info.st_size):
                raise ValueError("response changed while reading")
        if time.monotonic() >= args.deadline:
            raise TimeoutError("late response cannot be accepted")
        receipt({
            "phase": "finished",
            "status": "completed",
            "bytes": count,
            "sha256": digest.hexdigest(),
            "completed_monotonic": time.monotonic(),
        })
        return 0
    except (OSError, ValueError, TimeoutError) as error:
        receipt({
            "phase": "finished",
            "status": "failed",
            "error_type": type(error).__name__,
            "reason": str(error)[:256],
            "completed_monotonic": time.monotonic(),
        })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
