"""Test visible agentic-analysis progress without terminal control leakage."""

from __future__ import annotations

import io

from screwdriver.progress import AnalysisProgress


def test_noninteractive_progress_shows_provider_model_effort_and_real_stages() -> None:
    output = io.StringIO()
    progress = AnalysisProgress(output, heartbeat_seconds=60)

    progress.start("Anthropic", "claude-sonnet-5", "medium")
    progress.stage(1, "Preparing and redacting system evidence…")
    progress.stage(3, "Waiting for claude-sonnet-5 analysis…", True)
    progress.stage(4, "Validating findings against collected evidence…")
    progress.finish()

    rendered = output.getvalue()
    assert "Using Anthropic · claude-sonnet-5 · medium effort" in rendered
    assert "[1/6] Preparing and redacting system evidence" in rendered
    assert "[3/6] Waiting for claude-sonnet-5 analysis" in rendered
    assert "[4/6] Validating findings against collected evidence" in rendered
    assert "✓ Agentic analysis completed" in rendered
    assert "\x1b" not in rendered
