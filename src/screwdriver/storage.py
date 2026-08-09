"""Save Screwdriver inspection results as JSON, text, HTML, and log files."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

from screwdriver.models import SystemSnapshot


@dataclass(frozen=True, slots=True)
class ReportPaths:
    """Hold paths to all files created for one inspection."""

    snapshot: Path
    text_report: Path
    html_report: Path
    diagnostic_log: Path


def save_reports(
    snapshot: SystemSnapshot,
    terminal_report: str,
    output_directory: Path,
) -> ReportPaths:
    """Persist reports without changing the inspected system."""

    output_directory.mkdir(parents=True, exist_ok=True)
    paths = build_report_paths(output_directory)

    paths.snapshot.write_text(
        json.dumps(snapshot.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    paths.text_report.write_text(
        terminal_report + "\n",
        encoding="utf-8",
    )
    paths.html_report.write_text(
        _build_html_report(
            snapshot.identity.hostname,
            terminal_report,
        ),
        encoding="utf-8",
    )
    paths.diagnostic_log.write_text(
        "\n".join(
            [
                f"created_at={snapshot.created_at.isoformat()}",
                f"hostname={snapshot.identity.hostname}",
                f"schema_version={snapshot.schema_version}",
                f"findings={len(snapshot.findings)}",
                "inspection_mode=passive",
                "state_changed=false",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return paths


def build_report_paths(output_directory: Path) -> ReportPaths:
    """Return the paths used for one inspection report set."""

    return ReportPaths(
        snapshot=output_directory / "snapshot.json",
        text_report=output_directory / "report.txt",
        html_report=output_directory / "report.html",
        diagnostic_log=output_directory / "inspection.log",
    )


def _build_html_report(hostname: str, report: str) -> str:
    """Build a standalone HTML version of the terminal report."""

    title = html.escape(f"Screwdriver report — {hostname}")
    content = html.escape(report)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{
      margin: 0;
      background: #0b1020;
      color: #e8edf7;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    }}
    main {{
      max-width: 1040px;
      margin: 0 auto;
      padding: 32px 20px 64px;
    }}
    pre {{
      margin: 0;
      padding: 24px;
      overflow-x: auto;
      white-space: pre-wrap;
      background: #11182b;
      border: 1px solid #26314d;
      border-radius: 14px;
      box-shadow: 0 18px 50px #0006;
      line-height: 1.45;
    }}
  </style>
</head>
<body>
  <main><pre>{content}</pre></main>
</body>
</html>
"""
