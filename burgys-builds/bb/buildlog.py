"""Per-build log file.

Plain text, one line per event, redacted on the way in.  Kept separate from
the manifest so that a long log never makes the state file slow to read -
the dashboard reads manifests constantly and logs only on demand.
"""
from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

from .redact import redact_text
from .store import FileLock

MAX_BYTES = 8 * 1024 * 1024


class BuildLog:
    def __init__(self, paths, build_id: str) -> None:
        self.path: Path = paths.log_file(build_id)

    def append(self, text: str, level: str = "INFO") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().isoformat(timespec="seconds")
        line = f"{stamp} {level:<5} {redact_text(str(text)).rstrip()}\n"
        with FileLock(self.path.parent / (self.path.name + ".lock"), timeout=10):
            if self.path.exists() and self.path.stat().st_size > MAX_BYTES:
                # Truncating beats filling the disk; the manifest keeps the
                # state history either way.
                with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(f"{stamp} WARN  Log ueber {MAX_BYTES} Bytes - abgeschnitten\n")
                self.path.write_text("", encoding="utf-8")
            with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())

    def read(self, tail: int = 500) -> list:
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            return []
        return lines[-tail:] if tail else lines
