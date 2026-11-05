"""Incremental, budget-checked UTF-8 JSON for trusted L1 result transport.

This is cooperative parsing, not hard preemption of Python/GC/container
allocation. A final string join or dict insertion can still be proportional
to a scalar's size, which is bounded by the caller's total message limit.
"""

from __future__ import annotations

import codecs
import json
import math
import re
import time

from .l1_budget import BudgetExhausted
from .l1_json_stream import CHUNK_BYTES, MAX_DEPTH, MAX_INTEGER_BITS

SPECIAL = re.compile(r'["\\\x00-\x1f]')
SPACE = re.compile(r"[ \t\r\n]+")
ATOM = re.compile(r'[^ \t\r\n\[\]{}:,"]+')
ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
UNSET = object()


class JSONStreamParser:
    def __init__(self, *, deadline: float, max_bytes: int):
        if (
            type(max_bytes) is not int
            or max_bytes <= 0
            or type(deadline) not in (int, float)
            or not math.isfinite(deadline)
        ):
            raise ValueError("Finite deadline and positive byte limit required")
        self.deadline, self.max_bytes, self.bytes = deadline, max_bytes, 0
        self.decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self.stack, self.root = [], UNSET
        self.mode, self.atom, self.parts, self.escape, self.high = (
            "normal",
            "",
            [],
            "",
            None,
        )
        self.finished = False

    def check(self):
        if time.monotonic() >= self.deadline:
            raise BudgetExhausted("L1 result parsing exhausted shared deadline")

    def _value(self, value):
        if not self.stack:
            if self.root is not UNSET:
                raise ValueError("Trailing JSON data")
            self.root = value
            return
        frame = self.stack[-1]
        if frame["kind"] == "[" and frame["state"] in ("first", "value"):
            frame["value"].append(value)
        elif frame["kind"] == "{" and frame["state"] == "value":
            frame["value"][frame["key"]] = value
            frame["key"] = None
        else:
            raise ValueError("Unexpected JSON value")
        frame["state"] = "separator"

    def _string(self, value):
        if (
            self.stack
            and self.stack[-1]["kind"] == "{"
            and self.stack[-1]["state"] in ("first", "key")
        ):
            frame = self.stack[-1]
            if value in frame["value"]:
                raise ValueError("Duplicate JSON object key")
            frame["key"], frame["state"] = value, "colon"
        else:
            self._value(value)

    def _punctuation(self, token):
        if token in "{[":
            if len(self.stack) >= MAX_DEPTH:
                raise ValueError("JSON nesting exceeds tool limit")
            value = {} if token == "{" else []
            self._value(value)
            self.stack.append(
                {"kind": token, "value": value, "state": "first", "key": None}
            )
        elif token in "}]":
            if not self.stack:
                raise ValueError("Unexpected JSON close")
            frame = self.stack[-1]
            if frame["kind"] != ("{" if token == "}" else "[") or frame[
                "state"
            ] not in ("first", "separator"):
                raise ValueError("Mismatched JSON close or trailing comma")
            self.stack.pop()
        elif not self.stack:
            raise ValueError("Unexpected JSON punctuation")
        elif token == "," and self.stack[-1]["state"] == "separator":
            self.stack[-1]["state"] = (
                "key" if self.stack[-1]["kind"] == "{" else "value"
            )
        elif (
            token == ":"
            and self.stack[-1]["kind"] == "{"
            and self.stack[-1]["state"] == "colon"
        ):
            self.stack[-1]["state"] = "value"
        else:
            raise ValueError("Unexpected JSON separator")

    def _atom(self):
        # Only a bounded scalar reaches the stdlib decoder, never a complete
        # document, container or arbitrary-length string.
        value = json.loads(self.atom)
        if type(value) is float and not math.isfinite(value):
            raise ValueError("Nonfinite JSON scalar")
        if type(value) is int and value.bit_length() > MAX_INTEGER_BITS:
            raise ValueError("JSON integer exceeds tool limit")
        if value is not None and type(value) not in (bool, int, float):
            raise ValueError("Invalid JSON scalar")
        self._value(value)
        self.atom, self.mode = "", "normal"

    def _character(self, char):
        code = ord(char)
        if self.high is not None:
            if not 0xDC00 <= code <= 0xDFFF:
                raise ValueError("Unpaired JSON surrogate")
            self.parts.append(
                chr(0x10000 + ((self.high - 0xD800) << 10) + code - 0xDC00)
            )
            self.high = None
        elif 0xD800 <= code <= 0xDBFF:
            self.high = code
        elif 0xDC00 <= code <= 0xDFFF:
            raise ValueError("Unpaired JSON surrogate")
        else:
            self.parts.append(char)

    def _text(self, text):
        index = 0
        while index < len(text):
            self.check()
            char = text[index]
            if self.mode == "string":
                if self.escape:
                    if self.escape == "\\":
                        if char == "u":
                            self.escape = "u"
                        elif char in ESCAPES:
                            self._character(ESCAPES[char])
                            self.escape = ""
                        else:
                            raise ValueError("Invalid JSON escape")
                    else:
                        if char not in "0123456789abcdefABCDEF":
                            raise ValueError("Invalid JSON unicode escape")
                        self.escape += char
                        if len(self.escape) == 5:
                            self._character(chr(int(self.escape[1:], 16)))
                            self.escape = ""
                    index += 1
                elif char == '"':
                    if self.high is not None:
                        raise ValueError("Unpaired JSON surrogate")
                    value = "".join(self.parts)
                    self.check()
                    self.parts, self.mode = [], "normal"
                    self._string(value)
                    index += 1
                elif char == "\\":
                    self.escape = "\\"
                    index += 1
                else:
                    match = SPECIAL.search(text, index)
                    end = match.start() if match else len(text)
                    if end == index or self.high is not None:
                        raise ValueError("Control character or unpaired surrogate")
                    self.parts.append(text[index:end])
                    index = end
            elif self.mode == "atom":
                match = ATOM.match(text, index)
                if match:
                    self.atom += match.group()
                    if len(self.atom) > 4096:
                        raise ValueError("JSON scalar exceeds tool limit")
                    index = match.end()
                else:
                    self._atom()
            elif char in " \t\r\n":
                index = SPACE.match(text, index).end()
            elif char in "{}[]:,":
                self._punctuation(char)
                index += 1
            elif char == '"':
                self.parts, self.mode = [], "string"
                index += 1
            elif char in "-0123456789tfn":
                self.atom, self.mode = "", "atom"
            else:
                raise ValueError("Invalid JSON token")

    def feed(self, chunk: bytes):
        self.check()
        if self.finished or type(chunk) is not bytes or len(chunk) > CHUNK_BYTES:
            raise ValueError("Invalid JSON stream chunk/state")
        self.bytes += len(chunk)
        if self.bytes > self.max_bytes:
            raise ValueError("JSON result exceeds tool byte limit")
        self._text(self.decoder.decode(chunk))
        self.check()

    def finish(self):
        self.check()
        if self.finished:
            raise ValueError("JSON parser already finished")
        self._text(self.decoder.decode(b"", final=True))
        if self.mode == "atom":
            self._atom()
        if self.mode != "normal" or self.stack or self.root is UNSET:
            raise ValueError("Incomplete JSON result")
        self.finished = True
        self.check()
        return self.root
