"""Bounded parent-side pipe collection for L1 candidate processes."""

from __future__ import annotations

import os
import select
import subprocess
import time
from typing import Any

MAX_PIPE_BYTES = 16 * 1024 * 1024


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _strict_text(value: bytes | str | None) -> str:
    """Decode candidate output without silently accepting invalid UTF-8."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


class PipeLimitError(ValueError):
    """A candidate output pipe exceeded its evaluator-owned bound."""

    def __init__(self, message: str, *, stdout: bytes = b"", stderr: bytes = b"") -> None:
        super().__init__(message)
        self.stdout = _text(stdout)
        self.stderr = _text(stderr)


class PipeEncodingError(ValueError):
    """A candidate pipe contained bytes outside the declared UTF-8 protocol."""

    def __init__(self, message: str, *, stdout: bytes = b"", stderr: bytes = b"") -> None:
        super().__init__(message)
        self.stdout = _text(stdout)
        self.stderr = _text(stderr)


def communicate_bounded(
    process: Any,
    *,
    timeout: float,
    input_bytes: bytes | None = None,
    max_input_bytes: int | None = None,
    max_pipe_bytes: int = MAX_PIPE_BYTES,
) -> tuple[str, str]:
    """Collect stdout/stderr without allowing the parent to grow unbounded.

    Real ``Popen`` streams are read with nonblocking descriptors. Small test
    doubles that do not expose file descriptors retain the compatibility
    ``communicate`` path and are not production boundary evidence.
    """
    if timeout < 0:
        raise ValueError("non-negative pipe timeout required")
    if max_pipe_bytes <= 0 or (max_input_bytes is not None and max_input_bytes <= 0):
        raise ValueError("positive pipe limits required")
    payload = input_bytes or b""
    if max_input_bytes is not None and len(payload) > max_input_bytes:
        raise PipeLimitError("candidate input exceeds bounded size")
    if "communicate" in getattr(process, "__dict__", {}) or not all(
        hasattr(process, name) for name in ("stdin", "stdout", "stderr")
    ):
        value = payload if input_bytes is not None else None
        stdout, stderr = process.communicate(value, timeout=timeout)
        try:
            stdout_text, stderr_text = _strict_text(stdout), _strict_text(stderr)
        except UnicodeDecodeError as error:
            raise PipeEncodingError(
                "candidate stdout/stderr is not valid UTF-8",
                stdout=stdout if isinstance(stdout, bytes) else b"",
                stderr=stderr if isinstance(stderr, bytes) else b"",
            ) from error
        if len(stdout_text.encode("utf-8", errors="replace")) > max_pipe_bytes:
            raise PipeLimitError("candidate stdout exceeds bounded pipe size", stdout=stdout_text.encode())
        if len(stderr_text.encode("utf-8", errors="replace")) > max_pipe_bytes:
            raise PipeLimitError("candidate stderr exceeds bounded pipe size", stderr=stderr_text.encode())
        return stdout_text, stderr_text

    stdout_fd = process.stdout.fileno()
    stderr_fd = process.stderr.fileno()
    read_fds = {stdout_fd, stderr_fd}
    pending = memoryview(payload)
    input_fd = None
    if input_bytes is not None and process.stdin is not None:
        input_fd = process.stdin.fileno()
        os.set_blocking(input_fd, False)
    for fd in read_fds:
        os.set_blocking(fd, False)
    stdout = bytearray()
    stderr = bytearray()
    started = time.monotonic()
    while read_fds or pending:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise subprocess.TimeoutExpired(
                process.args, timeout, output=bytes(stdout), stderr=bytes(stderr)
            )
        ready_read, ready_write, _ = select.select(
            list(read_fds), [input_fd] if pending and input_fd is not None else [],
            [], min(0.05, remaining),
        )
        for fd in ready_write:
            written = os.write(fd, pending)
            pending = pending[written:]
            if not pending and process.stdin is not None:
                process.stdin.close()
        for fd in ready_read:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                read_fds.remove(fd)
                continue
            target = stdout if fd == stdout_fd else stderr
            target.extend(chunk)
            if len(target) > max_pipe_bytes:
                raise PipeLimitError(
                    "candidate stdout/stderr exceeds bounded pipe size",
                    stdout=bytes(stdout), stderr=bytes(stderr),
                )
    process.wait(timeout=max(0.0, timeout - (time.monotonic() - started)))
    try:
        return bytes(stdout).decode("utf-8"), bytes(stderr).decode("utf-8")
    except UnicodeDecodeError as error:
        raise PipeEncodingError(
            "candidate stdout/stderr is not valid UTF-8",
            stdout=bytes(stdout), stderr=bytes(stderr),
        ) from error


__all__ = [
    "MAX_PIPE_BYTES", "PipeEncodingError", "PipeLimitError", "communicate_bounded",
]
