"""Bounded log sink used by L1 worker launches.

The parent connects the candidate/tool stdout to this process instead of
opening a log file itself.  The sink performs the blocking open/write/fsync
and emits only a small receipt on stderr.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

PROTOCOL = "l1-log-writer-v1"


def receipt(value: dict) -> None:
    value = {"protocol": PROTOCOL, "pid": os.getpid(),
             "process_group": os.getpgrp(), **value}
    data = (json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n").encode()
    if len(data) > 4096:
        raise ValueError("oversized log-writer receipt")
    os.write(sys.stderr.fileno(), data)


def regular_parent(path: Path) -> None:
    chain = []
    current = path.parent
    while True:
        chain.append(current)
        if current.parent == current:
            break
        current = current.parent
    for item in reversed(chain):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("writer target parent is not a non-symlink directory")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--deadline", type=float, required=True)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--scope", choices=("evaluation", "failure_cleanup", "file"), default="evaluation")
    args = parser.parse_args()
    receipt({"phase": "started", "entered_monotonic": time.monotonic(), "scope": args.scope})
    temporary = None
    try:
        if args.limit <= 0:
            raise ValueError("positive log limit required")
        regular_parent(args.target)
        digest, count = hashlib.sha256(), 0
        with tempfile.NamedTemporaryFile(
            dir=args.target.parent,
            prefix=".file-" if args.scope == "file" else ".log-",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            while True:
                if time.monotonic() >= args.deadline:
                    raise TimeoutError("log write exhausted deadline")
                data = os.read(sys.stdin.fileno(), 65536)
                if not data:
                    break
                count += len(data)
                if count > args.limit:
                    raise ValueError("log byte limit exceeded")
                stream.write(data)
                digest.update(data)
            stream.flush()
            os.fsync(stream.fileno())
        if time.monotonic() >= args.deadline:
            raise TimeoutError("late log cannot be committed")
        try:
            previous = args.target.lstat()
        except FileNotFoundError:
            previous = None
        if previous is not None and not stat.S_ISREG(previous.st_mode):
            raise ValueError("log target is not a regular file")
        if previous is not None:
            raise ValueError("refusing to overwrite an existing log")
        os.link(temporary, args.target)
        temporary = None
        directory = os.open(args.target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        receipt({"phase": "finished", "status": "completed", "bytes": count,
                 "sha256": digest.hexdigest(), "completed_monotonic": time.monotonic(),
                 "path": str(args.target), "scope": args.scope,
                 "directory_synced": True})
        return 0
    except (OSError, ValueError, TimeoutError) as error:
        receipt({"phase": "finished", "status": "failed", "error_type": type(error).__name__,
                 "reason": str(error)[:256], "completed_monotonic": time.monotonic(),
                 "scope": args.scope})
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
