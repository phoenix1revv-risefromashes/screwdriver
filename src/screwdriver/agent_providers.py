"""Provider adapters for structured agentic analysis."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol, cast

_ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"
_REQUEST_TIMEOUT_SECONDS = 120
_TRANSIENT_ATTEMPTS = 3

PROVIDER_CHOICES = ("anthropic", "openai", "none")
EFFORT_CHOICES = ("light", "medium", "high")
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-5.6-terra",
}

_API_EFFORT = {
    "light": "low",
    "medium": "medium",
    "high": "high",
}


class AgentProviderError(RuntimeError):
    """Raised when a configured provider cannot return valid analysis."""


class UnsupportedEffortError(AgentProviderError):
    """Raised when a model rejects an otherwise valid effort parameter."""


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """Provider-neutral request for one structured analysis."""

    model: str
    effort: str
    max_output_tokens: int
    system: str
    user: str
    schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """Structured analysis plus the effort behavior used for the request."""

    analysis: dict[str, Any]
    requested_effort: str
    api_effort: str | None
    used_model_default_effort: bool = False
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_duration_ms: int = 0


class AgentProvider(Protocol):
    """Contract implemented by every remote model provider."""

    name: str
    display_name: str

    def analyze(self, request: ProviderRequest) -> ProviderResponse:
        """Return one validated structured analysis object."""


class AnthropicProvider:
    """Anthropic Messages API adapter."""

    name = "anthropic"
    display_name = "Anthropic"

    def analyze(self, request: ProviderRequest) -> ProviderResponse:
        started = time.monotonic()
        api_key = _required_key("ANTHROPIC_API_KEY")
        api_effort = _translate_effort(request.effort)
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
            "output_config": {
                "effort": api_effort,
                "format": {"type": "json_schema", "schema": request.schema},
            },
        }
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
            "Anthropic-Version": _ANTHROPIC_VERSION,
        }
        used_model_default = False
        try:
            body = _post_json(
                _ANTHROPIC_ENDPOINT,
                payload,
                headers,
                provider_name="Anthropic",
            )
        except UnsupportedEffortError:
            # Keep strict structured output, but let an older compatible model
            # use its own default when it does not implement effort.
            payload["output_config"].pop("effort", None)
            body = _post_json(
                _ANTHROPIC_ENDPOINT,
                payload,
                headers,
                provider_name="Anthropic",
            )
            used_model_default = True
        stop_reason = body.get("stop_reason")
        if stop_reason == "refusal":
            raise AgentProviderError("Anthropic refused the diagnostic request")
        content = "".join(
            str(block.get("text") or "")
            for block in _records(body.get("content"))
            if block.get("type") == "text"
        )
        try:
            analysis = _parse_analysis_json(content, "Anthropic")
        except AgentProviderError:
            if stop_reason == "max_tokens":
                raise AgentProviderError(
                    "Anthropic response reached the configured output limit before valid "
                    "JSON completed"
                ) from None
            raise
        usage = _mapping(body.get("usage"))
        return ProviderResponse(
            analysis=analysis,
            requested_effort=request.effort,
            api_effort=None if used_model_default else api_effort,
            used_model_default_effort=used_model_default,
            request_id=_optional_text(body.get("id")),
            input_tokens=_optional_int(usage.get("input_tokens")),
            output_tokens=_optional_int(usage.get("output_tokens")),
            request_duration_ms=int((time.monotonic() - started) * 1000),
        )


class OpenAIProvider:
    """OpenAI Responses API adapter."""

    name = "openai"
    display_name = "OpenAI"

    def analyze(self, request: ProviderRequest) -> ProviderResponse:
        started = time.monotonic()
        api_key = _required_key("OPENAI_API_KEY")
        api_effort = _translate_effort(request.effort)
        payload: dict[str, Any] = {
            "model": request.model,
            "instructions": request.system,
            "input": request.user,
            "max_output_tokens": request.max_output_tokens,
            "reasoning": {"effort": api_effort},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "screwdriver_analysis",
                    "strict": True,
                    "schema": request.schema,
                }
            },
            "store": False,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        used_model_default = False
        try:
            body = _post_json(
                _OPENAI_ENDPOINT,
                payload,
                headers,
                provider_name="OpenAI",
            )
        except UnsupportedEffortError:
            # Non-reasoning models can still support Responses + strict JSON.
            # Retry once without reasoning so the model uses its native default.
            payload.pop("reasoning", None)
            body = _post_json(
                _OPENAI_ENDPOINT,
                payload,
                headers,
                provider_name="OpenAI",
            )
            used_model_default = True

        if body.get("error"):
            error = _mapping(body.get("error"))
            message = str(error.get("message") or "request failed")[:300]
            raise AgentProviderError(f"OpenAI response error: {message}")

        text_parts: list[str] = []
        for output in _records(body.get("output")):
            for block in _records(output.get("content")):
                if block.get("type") == "refusal":
                    raise AgentProviderError("OpenAI refused the diagnostic request")
                if block.get("type") == "output_text":
                    text_parts.append(str(block.get("text") or ""))

        # Some compatible gateways expose the SDK convenience field in raw JSON.
        if not text_parts and isinstance(body.get("output_text"), str):
            text_parts.append(str(body["output_text"]))
        content = "".join(text_parts)
        try:
            analysis = _parse_analysis_json(content, "OpenAI")
        except AgentProviderError:
            if str(body.get("status") or "") == "incomplete":
                details = _mapping(body.get("incomplete_details"))
                reason = str(details.get("reason") or "unknown reason")
                raise AgentProviderError(f"OpenAI response was incomplete: {reason}") from None
            raise
        usage = _mapping(body.get("usage"))
        return ProviderResponse(
            analysis=analysis,
            requested_effort=request.effort,
            api_effort=None if used_model_default else api_effort,
            used_model_default_effort=used_model_default,
            request_id=_optional_text(body.get("id")),
            input_tokens=_optional_int(usage.get("input_tokens")),
            output_tokens=_optional_int(usage.get("output_tokens")),
            request_duration_ms=int((time.monotonic() - started) * 1000),
        )


_PROVIDERS: dict[str, AgentProvider] = {
    "anthropic": AnthropicProvider(),
    "openai": OpenAIProvider(),
}


def get_provider(name: str) -> AgentProvider:
    """Return the configured provider adapter."""

    provider = _PROVIDERS.get(name)
    if provider is None:
        raise ValueError("provider must be one of: " + ", ".join(PROVIDER_CHOICES))
    return provider


def resolve_model(provider: str, model: str | None) -> str:
    """Resolve and validate an explicit or provider-specific default model."""

    resolved = (model or DEFAULT_MODELS.get(provider) or "").strip()
    if not resolved:
        raise ValueError(f"--model is required for provider {provider}")
    if any(character.isspace() for character in resolved):
        raise ValueError("model name cannot contain whitespace")
    return resolved


def _translate_effort(effort: str) -> str:
    """Translate the public light/medium/high vocabulary to provider APIs."""

    try:
        return _API_EFFORT[effort]
    except KeyError as exception:
        raise ValueError("effort must be one of: " + ", ".join(EFFORT_CHOICES)) from exception


def _required_key(variable: str) -> str:
    value = os.environ.get(variable, "").strip()
    if not value:
        raise AgentProviderError(f"{variable} is not set")
    return value


def _post_json(
    endpoint: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    provider_name: str,
) -> dict[str, Any]:
    body: Any = None
    for attempt in range(_TRANSIENT_ATTEMPTS):
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
                body = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exception:
            message = _http_error_message(exception)
            error = f"{provider_name} API HTTP {exception.code}: {message}"
            if _is_unsupported_effort_error(exception.code, message):
                raise UnsupportedEffortError(error) from exception
            if (
                exception.code not in {429, 500, 502, 503, 504}
                or attempt == _TRANSIENT_ATTEMPTS - 1
            ):
                raise AgentProviderError(error) from exception
        except (OSError, TimeoutError, urllib.error.URLError) as exception:
            if attempt == _TRANSIENT_ATTEMPTS - 1:
                raise AgentProviderError(
                    f"{provider_name} request failed: {exception}"
                ) from exception
        except json.JSONDecodeError as exception:
            raise AgentProviderError(f"{provider_name} returned invalid JSON") from exception
        time.sleep((0.25, 0.75)[min(attempt, 1)])
    if not isinstance(body, dict):
        raise AgentProviderError(f"{provider_name} returned an invalid response envelope")
    return cast(dict[str, Any], body)


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _http_error_message(exception: urllib.error.HTTPError) -> str:
    """Return a bounded API error message without request content or credentials."""

    message = "request failed"
    try:
        body = json.loads(exception.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    else:
        error = _mapping(_mapping(body).get("error"))
        message = str(error.get("message") or message).strip()[:300]
    return message


def _is_unsupported_effort_error(status_code: int, message: str) -> bool:
    """Recognize a model-level rejection of effort, without masking other 400s."""

    if status_code != 400:
        return False
    normalized = message.casefold()
    mentions_setting = "effort" in normalized or "'reasoning'" in normalized
    rejects_setting = any(
        marker in normalized
        for marker in (
            "not supported",
            "unsupported parameter",
            "unknown parameter",
            "extra inputs are not permitted",
            "unrecognized",
        )
    )
    return mentions_setting and rejects_setting


def _parse_analysis_json(content: str, provider_name: str) -> dict[str, Any]:
    if not content:
        raise AgentProviderError(f"{provider_name} returned no structured text content")
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exception:
        raise AgentProviderError(f"{provider_name} returned invalid structured JSON") from exception
    if not isinstance(result, dict):
        raise AgentProviderError(f"{provider_name} result must be a JSON object")
    missing = {
        "summary",
        "architecture_observations",
        "unknowns",
        "issues",
        "probe_requests",
    } - result.keys()
    if missing:
        raise AgentProviderError(
            f"{provider_name} result is missing required fields: " + ", ".join(sorted(missing))
        )
    return cast(dict[str, Any], result)


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [cast(dict[str, Any], item) for item in value if isinstance(item, dict)]


def _mapping(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}
