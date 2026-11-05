"""Standalone stdlib-only worker: bounded stdin -> atomic compute request.

Started with exec, not Python code after fork. Receipts contain no payload.
Its supervisor owns the hard deadline, including blocked open/write/fsync.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import sys
import tempfile
import time
from pathlib import Path


def receipt(value):
    value.update(
        protocol="l1-request-writer-v1", pid=os.getpid(), process_group=os.getpgrp()
    )
    data = (json.dumps(value, allow_nan=False) + "\n").encode()
    if len(data) > 2048:
        raise ValueError("Oversized request-writer receipt")
    os.write(sys.stdout.fileno(), data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--deadline", type=float, required=True)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--replace-regular", action="store_true")
    args = parser.parse_args()
    if not math.isfinite(args.deadline) or args.limit <= 0:
        raise ValueError("Finite deadline and positive byte limit required")
    temporary = None
    receipt(
        {
            "phase": "started",
            "pid": os.getpid(),
            "process_group": os.getpgrp(),
            "entered_monotonic": time.monotonic(),
        }
    )
    try:
        digest, count = hashlib.sha256(), 0
        with tempfile.NamedTemporaryFile(
            dir=args.target.parent, prefix=".request-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            while True:
                if time.monotonic() >= args.deadline:
                    raise TimeoutError(
                        "Shared deadline exhausted before request commit"
                    )
                data = os.read(sys.stdin.fileno(), 65536)
                if not data:
                    break
                count += len(data)
                if count > args.limit:
                    raise ValueError("Request byte limit exceeded")
                stream.write(data)
                digest.update(data)
            stream.flush()
            os.fsync(stream.fileno())
        if not count or time.monotonic() >= args.deadline:
            raise TimeoutError("Empty or late request cannot be committed")
        if args.replace_regular:
            # Only evaluator-owned metadata paths opt in to replacement.
            # Never follow an existing symlink or write through a FIFO/device.
            try:
                previous = args.target.lstat()
            except FileNotFoundError:
                previous = None
            if previous is not None and not stat.S_ISREG(previous.st_mode):
                raise ValueError("Metadata replacement requires a regular target")
            if time.monotonic() >= args.deadline:
                raise TimeoutError("Late metadata cannot be committed")
            os.replace(temporary, args.target)
            temporary = None
        else:
            # Compute requests must continue to reject an existing name.
            os.link(temporary, args.target)
        directory = os.open(args.target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        receipt(
            {
                "phase": "finished",
                "status": "completed",
                "pid": os.getpid(),
                "bytes": count,
                "sha256": digest.hexdigest(),
                "completed_monotonic": time.monotonic(),
                "commit_mode": "replace_regular" if args.replace_regular else "create_only",
                "directory_synced": True,
            }
        )
        return 0
    except (OSError, ValueError) as error:
        receipt(
            {
                "phase": "finished",
                "status": "failed",
                "pid": os.getpid(),
                "completed_monotonic": time.monotonic(),
                "error_type": type(error).__name__,
                "reason": str(error)[:256],
            }
        )
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
