"""Universal custom file analysis: supported formats, grounding and CLI compatibility."""

import json

import pytest

from screwdriver.agent_providers import AgentProviderError, ProviderResponse
from screwdriver.cli import main
from screwdriver.custom_analysis import (
    _checked_issues,
    _read_file,
    _redact,
    _structured_evidence,
    analyze_custom_file,
    is_native_snapshot,
)


class FakeProvider:
    name = "openai"
    display_name = "OpenAI (mock)"

    def __init__(self, analysis):
        self.analysis = analysis
        self.request = None

    def analyze(self, request):
        self.request = request
        return ProviderResponse(
            analysis=self.analysis,
            requested_effort=request.effort,
            api_effort="medium",
        )


def issue(code: str, refs: list[str]) -> dict:
    return {
        "code": code,
        "title": "Microphone missing",
        "severity": "HIGH",
        "diagnosis_status": "PROBABLE",
        "confidence": 83,
        "evidence_references": refs,
        "observed": "Microphone was unavailable",
        "likely_root_cause": "Device was disconnected",
        "impact": "Speech capture unavailable",
        "suggested_solutions": ["Restore the correct USB device configuration"],
        "resolution_steps": ["Verify the configured device path"],
        "diagnostic_commands": ["lsusb"],
        "suggested_checks": ["Inspect USB inventory without altering the robot"],
        "verification": ["Confirm the USB device enumerates"],
        "limitations": "Log-only evidence cannot prove current state",
    }


@pytest.mark.parametrize(
    "extension,content,format_name",
    [
        (".json", '{"device":"mic","error":"missing"}', "json"),
        (".yaml", "device: mic\nerror: missing\n", "yaml"),
        (".yml", "device: mic\nerror: missing\n", "yaml"),
        (".jsonl", '{"error":"one"}\n{"error":"two"}\n', "jsonl"),
        (".txt", "ERROR: driver unavailable", "text"),
        (".log", "ERROR: driver unavailable", "text"),
        (".csv", "time,error\n1,device missing", "text"),
        (".ini", "[failure]\nerror=missing", "text"),
        (".xml", "<error>missing</error>", "text"),
        (".cfg", "error=missing", "text"),
    ],
)
def test_supported_formats(tmp_path, extension, content, format_name):
    path = tmp_path / ("events" + extension)
    path.write_text(content)
    text, fmt, data = _read_file(path)
    assert text == content
    assert fmt == format_name
    assert data is not None if fmt != "text" else data is None


def test_unmodified_native_snapshot_is_routed_to_original_analyzer(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "3.3",
                "created_at": "2026-10-21T08:00:00-07:00",
                "identity": {},
                "operating_system": {},
                "cpu": {},
                "memory": {},
                "network": {},
                "findings": [],
            }
        )
    )
    assert is_native_snapshot(path)
    path.write_text('{"scenarios": [{"evidence": {"error":"failed"}}]}')
    assert not is_native_snapshot(path)


def test_custom_file_end_to_end_with_two_independent_failures(tmp_path, monkeypatch, capsys):
    path = tmp_path / "inspection_log.json"
    path.write_text(
        json.dumps(
            {
                "logs": [
                    {"message": "ERROR: microphone device not found"},
                    {"message": "ERROR: LLM request timeout"},
                ]
            }
        )
    )
    fake = FakeProvider(
        {
            "summary": "Two distinct runtime problems.",
            "unknowns": [],
            "issues": [
                issue("MIC_MISSING", ["/logs/0/message"]),
                issue("LLM_TIMEOUT", ["/logs/1/message"]),
            ],
        }
    )
    monkeypatch.setattr("screwdriver.custom_analysis.get_provider", lambda _: fake)
    assert (
        main(["analyze", str(path), "--provider", "openai", "--output", str(tmp_path / "output")])
        == 0
    )
    reports = list((tmp_path / "output" / "custom").glob("*/diagnostic-report.html"))
    assert len(reports) == 2  # timestamped report and latest symlink
    report = tmp_path / "output" / "custom" / "latest" / "diagnostic-report.html"
    assert report.is_file()
    assert not list((tmp_path / "output" / "custom").rglob("*.json"))
    assert "Microphone missing" in report.read_text()
    assert "Read-only diagnostic checks" in report.read_text()
    assert not (tmp_path / "output" / "agentic").exists()
    assert "Problems reported: 2" in capsys.readouterr().out
    assert fake.request.schema["properties"]["issues"]
    assert '"ref":"/logs/0/message"' in fake.request.user


def test_severity_is_not_accepted_without_source_reference():
    evidence = [{"ref": "L1", "value": "ERROR: camera failure"}]
    results = _checked_issues(
        [issue("GROUNDED", ["L1"]), issue("INVENTED", ["L999"]), issue("EMPTY", [])],
        evidence,
    )
    assert [item["code"] for item in results] == ["GROUNDED"]
    assert results[0]["evidence"][0]["value"] == "ERROR: camera failure"


def test_scenario_finding_must_reference_actual_fault_evidence():
    evidence = [
        {"ref": "/scenarios/0/id", "value": "CUTIE-F001"},
        {"ref": "/scenarios/0/evidence/observed_log", "value": "ERROR: model missing"},
    ]
    ungrounded = issue("UNSUPPORTED", ["/scenarios/0/id"])
    grounded = issue("SUPPORTED", ["/scenarios/0/evidence/observed_log"])
    results = _checked_issues([ungrounded, grounded], evidence, scenario_fixture=True)
    assert [item["code"] for item in results] == ["SUPPORTED"]


def test_golden_answer_metadata_is_excluded_from_provider_evidence():
    source = {
        "scenarios": [
            {
                "title": "Solution is A",
                "expected_diagnosis": "Solution is A",
                "evidence": {
                    "observed_log": "ERROR: stt model file not found",
                    "expected_node": "/cutie_stt",
                },
            }
        ]
    }
    values = _structured_evidence(source)
    flattened = json.dumps(values)
    assert "Solution is A" not in flattened
    assert "/scenarios/0/evidence/observed_log" in flattened
    assert "expected_node" in flattened


def test_sensitive_text_redaction_and_html_escaping(tmp_path, monkeypatch):
    raw = "ERROR <script>alert('x')</script> password=hunter2 token=abc"
    path = tmp_path / "robot.log"
    path.write_text(raw)
    fake = FakeProvider(
        {
            "summary": "Potential microphone error",
            "unknowns": [],
            "issues": [issue("SENSITIVE", ["L1"])],
        }
    )
    monkeypatch.setattr("screwdriver.custom_analysis.get_provider", lambda _: fake)
    outcome = analyze_custom_file(path, tmp_path / "output", provider="openai")
    report = outcome.report.read_text()
    assert "<script>" not in report
    assert "&lt;script&gt;" in report
    assert "hunter2" not in report
    assert "hunter2" not in _redact(raw)
    assert "password=[redacted]" in report
    assert outcome.issue_count == 1
    assert set(p.name for p in outcome.report.parent.iterdir()) == {"diagnostic-report.html"}


def test_validation_binary_pdf_and_malformed_structured_text(tmp_path):
    binary = tmp_path / "events.log"
    binary.write_bytes(b"\x00\xff")
    with pytest.raises(ValueError, match="binary"):
        _read_file(binary)
    pdf = tmp_path / "events.pdf"
    pdf.write_text("Text that looks readable but is unsupported")
    with pytest.raises(ValueError, match="PDF is not supported"):
        _read_file(pdf)
    for extension, content in (
        (".json", "{invalid: json}"),
        (".yaml", "a: [unclosed"),
        (".jsonl", '{"ok":1}\n{broken\n'),
    ):
        path = tmp_path / ("events" + extension)
        path.write_text(content)
        text, fmt, data = _read_file(path)
        assert fmt == "text" and data is None
        assert text == content


def test_custom_file_requires_agentic_provider(tmp_path):
    path = tmp_path / "events.log"
    path.write_text("ERROR sensor missing")
    with pytest.raises(ValueError, match="requires --provider"):
        analyze_custom_file(path, tmp_path / "report", provider="none")


def test_diagnostic_description_and_severity_are_preserved():
    source = {
        "events": [
            {
                "description": "ERROR unable to open USB microphone",
                "severity": "HIGH",
                "notes": "service keeps restarting",
                "solution": "checking the USB path might help",
            }
        ]
    }
    entries = _structured_evidence(source)
    by_ref = {item["ref"]: item["value"] for item in entries}
    assert "unable to open USB microphone" in by_ref["/events/0/description"]
    assert by_ref["/events/0/severity"] == '"HIGH"'
    assert "service keeps restarting" in by_ref["/events/0/notes"]
    assert "USB path" in by_ref["/events/0/solution"]


def test_diagnostic_solutions_appear_in_html(tmp_path, monkeypatch):
    path = tmp_path / "fault.log"
    path.write_text("ERROR: camera driver failed to load")
    finding = issue("DRIVER", ["L1"])
    finding.update(
        {
            "suggested_solutions": ["Reconfigure camera driver"],
            "resolution_steps": ["Confirm the installed kernel module"],
            "diagnostic_commands": ["lsmod | grep uvcvideo"],
        }
    )
    fake = FakeProvider({"summary": "One problem", "unknowns": [], "issues": [finding]})
    monkeypatch.setattr("screwdriver.custom_analysis.get_provider", lambda _: fake)
    outcome = analyze_custom_file(path, tmp_path / "output", provider="openai")
    html_text = outcome.report.read_text()
    assert "Suggested solutions" in html_text
    assert "Reconfigure camera driver" in html_text
    assert "Resolution steps" in html_text
    assert "Confirm the installed kernel module" in html_text
    assert "Diagnostic commands" in html_text
    assert "lsmod | grep uvcvideo" in html_text
    assert all(
        key in fake.request.schema["properties"]["issues"]["items"]["required"]
        for key in ("suggested_solutions", "resolution_steps", "diagnostic_commands")
    )


def test_two_custom_runs_preserve_history_and_latest(tmp_path, monkeypatch):
    from screwdriver.storage import create_custom_report_directory

    path = tmp_path / "fault.txt"
    path.write_text("ERROR device unavailable")
    fake = FakeProvider(
        {"summary": "One problem", "unknowns": [], "issues": [issue("FAULT", ["L1"])]}
    )
    monkeypatch.setattr("screwdriver.custom_analysis.get_provider", lambda _: fake)
    output_root = tmp_path / "reports"
    first_directory = create_custom_report_directory(output_root)
    first = analyze_custom_file(path, first_directory, provider="openai")
    second_directory = create_custom_report_directory(output_root)
    second = analyze_custom_file(path, second_directory, provider="openai")
    assert first_directory != second_directory
    assert first.report.is_file() and second.report.is_file()
    assert (output_root / "custom" / "latest" / "diagnostic-report.html").resolve() == (
        second.report.resolve()
    )
    assert not list((output_root / "custom").rglob("*.json"))
    assert not (output_root / "agentic").exists()


def test_provider_errors_do_not_silently_report_health(tmp_path, monkeypatch):
    class BrokenProvider(FakeProvider):
        def analyze(self, request):
            raise AgentProviderError("connection refused")

    path = tmp_path / "robot.log"
    path.write_text("ERROR microphone disconnected")
    monkeypatch.setattr("screwdriver.custom_analysis.get_provider", lambda _: BrokenProvider({}))
    with pytest.raises(ValueError, match="custom-file analysis failed"):
        analyze_custom_file(path, tmp_path / "report", provider="openai")
    assert not list((tmp_path / "report").glob("*.html"))
