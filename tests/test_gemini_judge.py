"""Native Gemini requests match the catalog's generateContent capability."""

import json

import httpx
import pytest

from circuit_breaker import MAX_CALL_TOKENS, CircuitBreaker, SafetyStop
from judge_evaluator import JudgeEvaluator, gemini_verdict_text
from orchestration_canvas import failure_report

KEY = "fixture-private-gemini-key"
BASE = "https://generativelanguage.googleapis.com/v1beta"
VERDICT = {"approved": True, "reason": "Evidence satisfies the task", "issues": []}


def envelope(verdict=VERDICT, *, finish="STOP", parts=None):
    return {
        "candidates": [
            {
                "finishReason": finish,
                "content": {
                    "role": "model",
                    "parts": [{"text": json.dumps(verdict)}] if parts is None else parts,
                },
            }
        ]
    }


@pytest.fixture
def transport(monkeypatch):
    original = httpx.Client

    def install(handler):
        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
        )

    return install


def test_native_request_headers_schema_budget_and_one_generation(transport):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "POST"
        assert str(request.url) == BASE + "/models/gemini-current-flash:generateContent"
        assert request.headers["x-goog-api-key"] == KEY
        assert "authorization" not in request.headers
        assert not request.url.query
        payload = json.loads(request.content)
        assert KEY not in request.content.decode()
        assert payload["systemInstruction"]["parts"][0]["text"].startswith("Independently review")
        user = json.loads(payload["contents"][0]["parts"][0]["text"])
        assert user == {"task": "review task", "evidence": {"tests": 3}}
        config = payload["generationConfig"]
        assert config["maxOutputTokens"] == MAX_CALL_TOKENS
        assert config["candidateCount"] == 1
        assert config["responseMimeType"] == "application/json"
        assert config["responseSchema"]["required"] == ["approved", "reason", "issues"]
        assert config["responseSchema"]["properties"]["approved"] == {"type": "BOOLEAN"}
        return httpx.Response(200, json=envelope())

    transport(handler)
    budget = CircuitBreaker()
    result = JudgeEvaluator(KEY, "gemini-current-flash", BASE, "gemini").evaluate(
        "review task", {"tests": 3}, budget
    )
    assert result == VERDICT
    assert budget.tokens > MAX_CALL_TOKENS
    assert len(calls) == 1


@pytest.mark.parametrize(
    "base,provider,expected",
    [
        (BASE + "/openai", "openai", BASE),
        (BASE + "/openai/", "openai", BASE),
        (BASE, "openai", BASE),
        (BASE, "gemini", BASE),
        (BASE + "/", "gemini", BASE),
        (
            "https://generativelanguage.googleapis.com/v1",
            "openai",
            "https://generativelanguage.googleapis.com/v1",
        ),
    ],
)
def test_old_generic_config_and_native_bases_use_native_protocol(base, provider, expected):
    judge = JudgeEvaluator(KEY, "models/gemini-current-flash", base, provider)
    assert judge.provider == "gemini"
    assert judge.base_url == expected
    assert judge.model == "gemini-current-flash"


@pytest.mark.parametrize(
    "base,provider",
    [
        ("https://generativelanguage.googleapis.com/v1beta/other", "openai"),
        ("https://generativelanguage.googleapis.com/v1beta?key=secret", "openai"),
        ("http://generativelanguage.googleapis.com/v1beta", "openai"),
        ("https://user@generativelanguage.googleapis.com/v1beta", "openai"),
        ("https://generativelanguage.googleapis.com.attacker.example/v1beta", "openai"),
        ("https://api.openai.com/v1", "gemini"),
        ("https://api.anthropic.com/v1", "gemini"),
        ("https://judge.test/v1beta", "gemini"),
    ],
)
def test_wrong_host_path_or_protocol_is_rejected_before_any_request(base, provider):
    with pytest.raises(ValueError):
        JudgeEvaluator(KEY, "gemini-current-flash", base, provider)


@pytest.mark.parametrize(
    "model",
    [
        "../other",
        "models/models/other",
        "gemini:test",
        "model?key=x",
        "a/b",
        "https://bad.test/model",
        "x" * 129,
        1,
    ],
)
def test_model_identifiers_cannot_change_the_request_path(model):
    with pytest.raises(ValueError, match="model"):
        JudgeEvaluator(KEY, model, BASE, "gemini")


@pytest.mark.parametrize("model", [KEY, "gemini-" + KEY])
def test_secret_accidentally_pasted_as_model_never_enters_a_url(model, transport):
    transport(lambda _request: pytest.fail("a credential must never appear in a model URL"))
    with pytest.raises(ValueError) as caught:
        JudgeEvaluator(KEY, model, BASE, "gemini")
    assert KEY not in str(caught.value)


def test_http_failure_preserves_safe_code_without_paid_retry(transport):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            404, json={"error": {"status": "NOT_FOUND", "message": KEY + " private body"}}
        )

    transport(handler)
    budget = CircuitBreaker()
    with pytest.raises(httpx.HTTPStatusError) as caught:
        JudgeEvaluator(KEY, "gemini-current-flash", BASE, "gemini").evaluate("task", {}, budget)
    report = failure_report(caught.value, "cloud_judge")
    assert report["http_status"] == 404
    assert report["provider_code"] == "NOT_FOUND"
    assert report["api_host"] == "generativelanguage.googleapis.com"
    assert KEY not in json.dumps(report)
    assert "private body" not in json.dumps(report)
    assert budget.tokens > MAX_CALL_TOKENS
    assert len(calls) == 1


def test_budget_kill_switch_prevents_network_request(transport):
    transport(lambda _request: pytest.fail("over-budget request must not run"))
    with pytest.raises(SafetyStop):
        JudgeEvaluator(KEY, "gemini-current-flash", BASE, "gemini").evaluate(
            "task", {}, CircuitBreaker(token_limit=1)
        )


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {"candidates": []},
        {"candidates": [None]},
        {"candidates": [envelope()["candidates"][0]] * 2},
        envelope(finish="MAX_TOKENS"),
        envelope(finish="SAFETY"),
        {"candidates": [{"finishReason": "STOP"}]},
        envelope(parts=[None]),
        envelope(parts=[{"functionCall": {"name": "anything"}}]),
        envelope(parts=[{"text": 1}]),
        envelope(parts=[{"thought": True, "text": "private reasoning"}]),
    ],
)
def test_blocked_incomplete_or_nontext_response_never_becomes_approval(payload):
    with pytest.raises(ValueError):
        gemini_verdict_text(payload)


def test_thoughts_are_not_used_or_returned_as_the_verdict(transport):
    transport(
        lambda _request: httpx.Response(
            200,
            json=envelope(
                parts=[
                    {"thought": True, "text": "private reasoning"},
                    {"text": json.dumps(VERDICT)},
                ]
            ),
        )
    )
    assert (
        JudgeEvaluator(KEY, "gemini-current-flash", BASE, "gemini").evaluate(
            "task", {}, CircuitBreaker()
        )
        == VERDICT
    )


@pytest.mark.parametrize(
    "verdict",
    [
        {"approved": "true", "reason": "wrong type", "issues": []},
        {"approved": True, "reason": "missing issues"},
        {"approved": True, "reason": "wrong issue type", "issues": [1]},
        [],
    ],
)
def test_native_verdict_still_requires_existing_review_schema(transport, verdict):
    transport(lambda _request: httpx.Response(200, json=envelope(verdict)))
    with pytest.raises(ValueError, match="verdict"):
        JudgeEvaluator(KEY, "gemini-current-flash", BASE, "gemini").evaluate(
            "task", {}, CircuitBreaker()
        )


def test_reported_issues_override_native_approval(transport):
    transport(
        lambda _request: httpx.Response(
            200, json=envelope({"approved": True, "reason": "issues", "issues": ["failing test"]})
        )
    )
    result = JudgeEvaluator(KEY, "gemini-current-flash", BASE, "gemini").evaluate(
        "task", {}, CircuitBreaker()
    )
    assert result["approved"] is False
