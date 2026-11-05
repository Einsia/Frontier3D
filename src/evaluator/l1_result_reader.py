"""Isolated stdlib-only reader; stdout is bytes, stderr is bounded receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import sys
import time
from pathlib import Path


def receipt(value):
    value.update(
        protocol="l1-result-reader-v1", pid=os.getpid(), process_group=os.getpgrp()
    )
    data = (json.dumps(value, allow_nan=False) + "\n").encode()
    if len(data) > 2048:
        raise ValueError("Oversized reader receipt")
    os.write(sys.stderr.fileno(), data)


def signature(info):
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "bytes": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--deadline", type=float, required=True)
    parser.add_argument("--limit", type=int, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.deadline) or args.limit <= 0:
        raise ValueError("Invalid reader deadline/limit")
    receipt({"phase": "started", "entered_monotonic": time.monotonic()})
    try:
        digest, count = hashlib.sha256(), 0
        # A blocked open, metadata operation or read remains inside this
        # independently terminable process, never in its parent.
        with os.fdopen(
            os.open(args.source, os.O_RDONLY | os.O_NOFOLLOW), "rb"
        ) as stream:
            info = os.fstat(stream.fileno())
            before = signature(info)
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= args.limit:
                raise ValueError("Result must be a nonempty bounded regular file")
            while True:
                if time.monotonic() >= args.deadline:
                    raise TimeoutError("Result read exhausted deadline")
                chunk = stream.read(65536)
                if not chunk:
                    break
                count += len(chunk)
                if count > args.limit:
                    raise ValueError("Result grew beyond byte limit")
                digest.update(chunk)
                sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            if (
                signature(os.fstat(stream.fileno())) != before
                or signature(args.source.stat(follow_symlinks=False)) != before
            ):
                raise ValueError("Result source changed during read")
        if count != before["bytes"] or time.monotonic() >= args.deadline:
            raise ValueError("Incomplete or late result read")
        receipt(
            {
                "phase": "finished",
                "status": "completed",
                "bytes": count,
                "sha256": digest.hexdigest(),
                "source_stat": before,
                "completed_monotonic": time.monotonic(),
            }
        )
        return 0
    except (OSError, ValueError) as error:
        receipt(
            {
                "phase": "finished",
                "status": "failed",
                "error_type": type(error).__name__,
                "completed_monotonic": time.monotonic(),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
