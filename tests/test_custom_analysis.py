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
    data_files = [
        p
        for p in (tmp_path / "output").glob("agentic/*/custom-analysis.json")
        if p.parent.name != "latest"
    ]
    assert len(data_files) == 1
    output = json.loads(data_files[0].read_text())
    assert [i["code"] for i in output["issues"]] == ["MIC_MISSING", "LLM_TIMEOUT"]
    assert output["issues"][1]["evidence"][0]["ref"] == "/logs/1/message"
    assert (data_files[0].parent / "diagnostic-report.html").is_file()
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


def test_sensitive_text_redaction_and_html_escaping(tmp_path):
    raw = "ERROR <script>alert('x')</script> password=hunter2 token=abc"
    path = tmp_path / "robot.log"
    path.write_text(raw)
    outcome = analyze_custom_file(path, tmp_path / "output", provider="none")
    report = outcome.report.read_text()
    assert "<script>" not in report
    assert "hunter2" not in _redact(raw)
    assert "no model selected" in report
    assert outcome.issue_count == 0


def test_validation_binary_invalid_json_and_invalid_yaml(tmp_path):
    binary = tmp_path / "events.log"
    binary.write_bytes(b"\x00\xff")
    with pytest.raises(ValueError, match="binary"):
        _read_file(binary)
    invalid_json = tmp_path / "events.json"
    invalid_json.write_text("{invalid: json}")
    with pytest.raises(ValueError, match="invalid JSON"):
        _read_file(invalid_json)
    invalid_yaml = tmp_path / "events.yaml"
    invalid_yaml.write_text("a: [unclosed")
    with pytest.raises(ValueError, match="invalid YAML"):
        _read_file(invalid_yaml)


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
