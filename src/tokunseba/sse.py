"""Minimal SSE and NDJSON parsing, used only to read usage out of a stream we pass through untouched."""
from __future__ import annotations

import json


class SSECollector:
    """Feed raw bytes; collect (event_name, data_dict) pairs. The stream itself is never modified."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []
        self._buf = ""
        self._event = ""
        self._data: list[str] = []

    def feed(self, chunk: bytes) -> None:
        try:
            self._buf += chunk.decode("utf-8", errors="replace")
        except Exception:
            return
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._line(line.rstrip("\r"))

    def _line(self, line: str) -> None:
        if line == "":
            self._flush()
        elif line.startswith("event:"):
            self._event = line[6:].strip()
        elif line.startswith("data:"):
            self._data.append(line[5:].strip())
        # comments and other fields are ignored

    def _flush(self) -> None:
        if not self._data:
            self._event = ""
            return
        raw = "\n".join(self._data)
        self._data = []
        name = self._event
        self._event = ""
        if raw == "[DONE]":
            return
        try:
            data = json.loads(raw)
        except ValueError:
            return
        if isinstance(data, dict):
            self.events.append((name or data.get("type", ""), data))

    def close(self) -> None:
        self._flush()


class NDJSONCollector:
    def __init__(self):
        self.objects: list[dict] = []
        self._buf = ""

    def feed(self, chunk: bytes) -> None:
        self._buf += chunk.decode("utf-8", errors="replace")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._obj(line)

    def _obj(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            o = json.loads(line)
        except ValueError:
            return
        if isinstance(o, dict):
            self.objects.append(o)

    def close(self) -> None:
        self._obj(self._buf)
        self._buf = ""
