"""Visible, TTY-safe progress for Screwdriver workflows."""

from __future__ import annotations

import sys
import threading
import time
from typing import Protocol, TextIO

_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_PROGRESS_WIDTH = 58


class ProgressCallback(Protocol):
    """Callback shape used by collectors and analysis orchestration."""

    def __call__(self, number: int, label: str, waiting: bool = False) -> None: ...


class StageProgress:
    """Render real workflow stages and measured elapsed time without fake percentages."""

    def __init__(
        self,
        total: int,
        stream: TextIO | None = None,
        *,
        heartbeat_seconds: float = 5.0,
    ) -> None:
        if total < 1:
            raise ValueError("total must be at least 1")
        self.total = total
        self.stream = stream or sys.stderr
        self.heartbeat_seconds = heartbeat_seconds
        self.interactive = bool(getattr(self.stream, "isatty", lambda: False)())
        self._started = time.monotonic()
        self._stage_started: float | None = None
        self._stage_number: int | None = None
        self._stage_label: str | None = None
        self._waiting_started = self._started
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, message: str | None = None) -> None:
        """Start a workflow and optionally print one concise context line."""

        self._started = time.monotonic()
        if message:
            self._write(message, replace=False)

    def stage(self, number: int, label: str, waiting: bool = False) -> None:
        """Begin a real stage, completing the previous stage with measured time."""

        if number < 1 or number > self.total:
            raise ValueError(f"stage number must be between 1 and {self.total}")

        self._complete_current_stage()
        self._stage_number = number
        self._stage_label = _clean_label(label)
        self._stage_started = time.monotonic()

        if self.interactive:
            self._render_active()

        if waiting:
            self._waiting_started = self._stage_started
            self._stop.clear()
            self._thread = threading.Thread(target=self._heartbeat, daemon=True)
            self._thread.start()

    def finish(self, message: str) -> None:
        """Complete the final stage and print total measured workflow time."""

        self._complete_current_stage()
        elapsed = time.monotonic() - self._started
        self._write(f"✓ {message} · {elapsed:.1f}s", replace=False)

    def fail(self, message: str) -> None:
        """Stop progress and show where the workflow failed."""

        self._stop_waiting()
        if self._stage_number is not None and self._stage_label is not None:
            elapsed = time.monotonic() - (self._stage_started or self._started)
            self._write(
                _format_stage(
                    self._stage_number,
                    self.total,
                    self._stage_label,
                    marker="✗",
                    elapsed=elapsed,
                ),
                replace=False,
            )
            self._clear_current_stage()
        elapsed = time.monotonic() - self._started
        self._write(f"✗ {message} · {elapsed:.1f}s", replace=False)

    def close(self) -> None:
        """Stop heartbeat output and restore a clean terminal line."""

        self._stop_waiting()

    def _complete_current_stage(self) -> None:
        if self._stage_number is None or self._stage_label is None:
            self._stop_waiting()
            return

        self._stop_waiting()
        elapsed = time.monotonic() - (self._stage_started or self._started)
        self._write(
            _format_stage(
                self._stage_number,
                self.total,
                self._stage_label,
                marker="✓",
                elapsed=elapsed,
            ),
            replace=False,
        )
        self._clear_current_stage()

    def _clear_current_stage(self) -> None:
        self._stage_number = None
        self._stage_label = None
        self._stage_started = None

    def _heartbeat(self) -> None:
        frame = 0
        interval = 0.1 if self.interactive else self.heartbeat_seconds
        while not self._stop.wait(interval):
            if self._stage_number is None or self._stage_label is None:
                return
            elapsed = int(time.monotonic() - self._waiting_started)
            prefix = _FRAMES[frame % len(_FRAMES)] if self.interactive else "…"
            message = (
                f"[{self._stage_number}/{self.total}] {prefix} "
                f"{self._stage_label} · {elapsed}s elapsed"
            )
            self._write(message, replace=self.interactive)
            frame += 1

    def _render_active(self) -> None:
        if self._stage_number is None or self._stage_label is None:
            return
        self._write(
            f"[{self._stage_number}/{self.total}] {self._stage_label}…",
            replace=True,
        )

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


class InspectionProgress(StageProgress):
    """Progress renderer for the eight-stage local inspection pipeline."""

    def __init__(self, stream: TextIO | None = None) -> None:
        super().__init__(8, stream)

    def start(self, mode: str) -> None:  # type: ignore[override]
        super().start(f"Screwdriver inspection · {mode}")


class AnalysisProgress(StageProgress):
    """Report agentic/deterministic analysis stages and provider wait time."""

    def __init__(self, stream: TextIO | None = None, *, heartbeat_seconds: float = 5.0) -> None:
        super().__init__(6, stream, heartbeat_seconds=heartbeat_seconds)

    def start(self, provider: str, model: str, effort: str) -> None:  # type: ignore[override]
        super().start(f"Using {provider} · {model} · {effort} effort for in-depth analysis…")

    def finish(self, message: str = "Agentic analysis completed") -> None:  # type: ignore[override]
        super().finish(message)


def _clean_label(label: str) -> str:
    return label.rstrip().rstrip(".…")


def _format_stage(
    number: int,
    total: int,
    label: str,
    *,
    marker: str,
    elapsed: float,
) -> str:
    prefix = f"[{number}/{total}] {label}"
    dots = "." * max(3, _PROGRESS_WIDTH - len(prefix))
    return f"{prefix} {dots} {marker} {elapsed:.1f}s"


__all__ = [
    "AnalysisProgress",
    "InspectionProgress",
    "ProgressCallback",
    "StageProgress",
]
