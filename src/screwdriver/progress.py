"""Visible, TTY-safe progress for long-running agentic analysis."""

from __future__ import annotations

import sys
import threading
import time
from typing import TextIO

_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class AnalysisProgress:
    """Report real stages and elapsed provider wait time without fake percentages."""

    def __init__(self, stream: TextIO | None = None, *, heartbeat_seconds: float = 5.0) -> None:
        self.stream = stream or sys.stderr
        self.heartbeat_seconds = heartbeat_seconds
        self.interactive = bool(getattr(self.stream, "isatty", lambda: False)())
        self._started = time.monotonic()
        self._waiting_started = self._started
        self._waiting_label = "Agentic analysis in progress"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, provider: str, model: str, effort: str) -> None:
        self._started = time.monotonic()
        self._write(
            f"Using {provider} · {model} · {effort} effort for in-depth analysis…",
            replace=False,
        )

    def stage(self, number: int, label: str, waiting: bool = False) -> None:
        self._stop_waiting()
        self._write(f"[{number}/6] {label}", replace=False)
        if waiting:
            self._waiting_label = label.rstrip("…")
            self._waiting_started = time.monotonic()
            self._stop.clear()
            self._thread = threading.Thread(target=self._heartbeat, daemon=True)
            self._thread.start()

    def finish(self, message: str = "Agentic analysis completed") -> None:
        self._stop_waiting()
        elapsed = time.monotonic() - self._started
        self._write(f"✓ {message} in {elapsed:.1f} seconds", replace=False)

    def fail(self, message: str) -> None:
        self._stop_waiting()
        elapsed = time.monotonic() - self._started
        self._write(f"⚠ {message} after {elapsed:.1f} seconds", replace=False)

    def close(self) -> None:
        """Stop the heartbeat and restore a clean terminal line."""

        self._stop_waiting()

    def _heartbeat(self) -> None:
        frame = 0
        interval = 0.1 if self.interactive else self.heartbeat_seconds
        while not self._stop.wait(interval):
            elapsed = int(time.monotonic() - self._waiting_started)
            prefix = _FRAMES[frame % len(_FRAMES)] if self.interactive else "…"
            self._write(
                f"{prefix} {self._waiting_label}… {elapsed}s elapsed",
                replace=self.interactive,
            )
            frame += 1

    def _stop_waiting(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self.interactive:
            self.stream.write("\r\x1b[2K")
            self.stream.flush()

    def _write(self, message: str, *, replace: bool) -> None:
        prefix = "\r\x1b[2K" if replace else ""
        suffix = "" if replace else "\n"
        self.stream.write(prefix + message + suffix)
        self.stream.flush()


__all__ = ["AnalysisProgress"]
