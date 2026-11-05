"""Deadline-checked JSON emission with bounded scalar encoding steps.

This is cooperative Python encoding, not hard preemption of the interpreter.
Only exact built-in JSON types are accepted; no user encoders, subclass
iteration, pickle, or arbitrary repr hooks are invoked. Container traversal
and scalar work are bounded by the limits below. Blocking writes are handled
separately by the exec-based request writer.
"""

from __future__ import annotations

import json
import math
import sys
import time

from .l1_budget import BudgetExhausted

STRING_CHARS = 4096
CHUNK_BYTES = 65536
MAX_DEPTH = 128
MAX_CONTAINER_BYTES = 64 * 1024 * 1024
MAX_INTEGER_BITS = 4096


def json_chunks(value, *, deadline: float, max_bytes: int):
    """Produce the bytes of json.dumps(ensure_ascii=False, allow_nan=False).

    String slices, numeric tokens, output aggregation and traversal depth are
    bounded. Exact container backing-store limits also bound scans through
    deleted dictionary slots; this is a tool limit, not a candidate defect.
    Dictionary keys must be strings, matching the compute JSON protocol.
    """
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("Positive byte limit required")
    if (
        isinstance(deadline, bool)
        or not isinstance(deadline, (int, float))
        or not math.isfinite(deadline)
    ):
        raise ValueError("Finite monotonic deadline required")
    active = set()

    def check():
        if time.monotonic() >= deadline:
            raise BudgetExhausted(
                "Shared deadline exhausted while encoding compute request"
            )

    def string(text):
        yield b'"'
        for start in range(0, len(text), STRING_CHARS):
            check()
            # Slicing Unicode codepoints never splits a UTF-8 codepoint.
            yield json.dumps(text[start : start + STRING_CHARS], ensure_ascii=False)[
                1:-1
            ].encode("utf-8")
        yield b'"'

    def tokens(item, depth=0):
        check()
        kind = type(item)
        if kind is str:
            yield from string(item)
        elif item is None:
            yield b"null"
        elif kind is bool:
            yield b"true" if item else b"false"
        elif kind is int:
            if item.bit_length() > MAX_INTEGER_BITS:
                raise ValueError("JSON integer exceeds bounded conversion limit")
            yield str(item).encode("ascii")
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError("Nonfinite JSON number")
            yield json.dumps(item, allow_nan=False).encode("ascii")
        elif kind in (dict, list, tuple):
            if depth >= MAX_DEPTH or sys.getsizeof(item) > MAX_CONTAINER_BYTES:
                raise ValueError("JSON container exceeds depth or backing-store limit")
            if id(item) in active:
                raise ValueError("Circular JSON container")
            active.add(id(item))
            try:
                yield b"{" if kind is dict else b"["
                for index, part in enumerate(item.items() if kind is dict else item):
                    check()
                    if index:
                        yield b", "
                    if kind is dict:
                        key, part = part
                        if type(key) is not str:
                            raise TypeError("Compute JSON object keys must be strings")
                        yield from string(key)
                        yield b": "
                    yield from tokens(part, depth + 1)
                yield b"}" if kind is dict else b"]"
            finally:
                active.remove(id(item))
        else:
            raise TypeError("Compute request contains a non-native JSON value")

    pending = bytearray()
    total = 0
    for token in tokens(value):
        check()
        total += len(token)
        if total > max_bytes:
            raise OverflowError("Compute request exceeds its encoded byte limit")
        if len(pending) + len(token) > CHUNK_BYTES:
            yield bytes(pending)
            pending.clear()
        pending.extend(token)
    check()
    if pending:
        yield bytes(pending)
