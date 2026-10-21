"""Provider adapters accept the schema requested by each analysis mode."""

import json

import pytest

from screwdriver.agent_providers import (
    AgentProviderError,
    AnthropicProvider,
    OpenAIProvider,
    ProviderRequest,
    _parse_analysis_json,
)
from screwdriver.custom_analysis import _model_schema


def _request(schema):
    return ProviderRequest(
        model="test-model",
        effort="medium",
        max_output_tokens=1000,
        system="Analyze diagnostic evidence",
        user="ERROR: missing microphone",
        schema=schema,
    )


@pytest.mark.parametrize("provider_cls", [OpenAIProvider, AnthropicProvider])
def test_custom_file_schema_succeeds_through_real_adapter_parsing(provider_cls, monkeypatch):
    """The API result for a file has no blueprint/probe fields."""
    analysis = {"summary": "Missing microphone", "unknowns": [], "issues": []}
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder")

    def fake_post_json(endpoint, payload, headers, *, provider_name):
        assert payload  # Each adapter builds its own API request.
        if provider_name == "OpenAI":
            return {
                "output": [{"content": [{"type": "output_text", "text": json.dumps(analysis)}]}]
            }
        return {
            "content": [{"type": "text", "text": json.dumps(analysis)}],
            "stop_reason": "end_turn",
        }

    monkeypatch.setattr("screwdriver.agent_providers._post_json", fake_post_json)
    result = provider_cls().analyze(_request(_model_schema()))
    assert result.analysis == analysis


def test_file_schema_still_rejects_missing_required_fields():
    with pytest.raises(AgentProviderError, match="unknowns"):
        _parse_analysis_json('{"summary":"ok","issues":[]}', "OpenAI", _model_schema())


def test_native_schema_still_requires_native_fields():
    native_schema = {
        "type": "object",
        "required": [
            "summary",
            "architecture_observations",
            "unknowns",
            "issues",
            "probe_requests",
        ],
    }
    custom_response = '{"summary":"ok","unknowns":[],"issues":[]}'
    with pytest.raises(AgentProviderError, match="architecture_observations, probe_requests"):
        _parse_analysis_json(custom_response, "OpenAI", native_schema)


def test_end_to_end_openai_custom_file_creates_html_only(tmp_path, monkeypatch):
    """Exercise CLI, evidence extraction, adapter parsing, and HTML output."""
    from screwdriver.cli import main

    path = tmp_path / "inspection_log.json"
    path.write_text(
        json.dumps(
            {"events": [{"description": "ERROR unable to open USB microphone", "severity": "HIGH"}]}
        )
    )
    analysis = {
        "summary": "USB microphone connection failed",
        "unknowns": ["Current hardware state cannot be established from this file"],
        "issues": [
            {
                "code": "MIC_IO",
                "title": "Microphone unavailable",
                "severity": "HIGH",
                "diagnosis_status": "PROBABLE",
                "confidence": 85,
                "evidence_references": ["/events/0/description"],
                "observed": "Device access error",
                "likely_root_cause": "Missing device path",
                "impact": "Audio capture unavailable",
                "suggested_solutions": ["Correct the configured microphone path"],
                "resolution_steps": ["Verify the path", "Update configuration after review"],
                "diagnostic_commands": ["lsusb"],
                "suggested_checks": ["Check USB enumeration"],
                "verification": ["Confirm microphone enumerates"],
                "limitations": "File evidence only",
            }
        ],
    }
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")

    def fake_post_json(endpoint, payload, headers, *, provider_name):
        assert provider_name == "OpenAI"
        assert "architecture_observations" not in payload["text"]["format"]["schema"]["required"]
        entries = json.loads(payload["input"])["evidence"]
        assert any(entry["ref"] == "/events/0/description" for entry in entries)
        return {"output": [{"content": [{"type": "output_text", "text": json.dumps(analysis)}]}]}

    monkeypatch.setattr("screwdriver.agent_providers._post_json", fake_post_json)
    assert (
        main(["analyze", str(path), "--output", str(tmp_path / "reports"), "--provider", "openai"])
        == 0
    )
    directory = tmp_path / "reports" / "custom" / "latest"
    assert (directory / "diagnostic-report.html").is_file()
    assert set(p.name for p in directory.iterdir()) == {"diagnostic-report.html"}
    report = (directory / "diagnostic-report.html").read_text()
    assert "Correct the configured microphone path" in report
    assert "lsusb" in report
    assert "/events/0/description" in report
