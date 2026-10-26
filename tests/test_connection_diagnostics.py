import json

import httpx
import pytest

import orchestration_canvas as cli
from tools.http_client import post_json


@pytest.mark.parametrize(
    "stage,status",
    [("ollama_worker", 404), ("cloud_judge", 401), ("cloud_judge", 429), ("cloud_judge", 403)],
)
def test_http_diagnostics_identify_service_without_disclosing_credentials(stage, status):
    request = httpx.Request(
        "POST",
        "https://user:TOPSECRET_TEST_VALUE@api.example/v1?token=TOPSECRET_TEST_VALUE",
        headers={"Authorization": "Bearer TOPSECRET_TEST_VALUE"},
    )
    response = httpx.Response(status, request=request, json={"error": "TOPSECRET_TEST_VALUE body"})
    error = httpx.HTTPStatusError(
        "TOPSECRET_TEST_VALUE exception text", request=request, response=response
    )
    report = cli.failure_report(error, stage)
    assert report["stage"] == stage
    assert report["http_status"] == status
    assert report["api_host"] == "api.example"
    assert "TOPSECRET_TEST_VALUE" not in json.dumps(report)


def test_known_quota_code_is_preserved_but_error_message_is_not():
    def handler(request):
        return httpx.Response(
            429,
            json={
                "error": {
                    "code": "insufficient_quota",
                    "message": "secret credential and private prompt",
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            post_json(client, "https://api.example/v1", payload={})
    report = cli.failure_report(caught.value, "cloud_judge")
    assert report["provider_code"] == "insufficient_quota"
    assert "credit" in report["hint"]
    assert "secret credential" not in json.dumps(report)


def test_unrecognized_provider_codes_are_not_echoed():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                400, json={"error": {"code": "secret-value", "message": "private"}}
            )
        )
    ) as client:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            post_json(client, "https://api.example/v1", payload={})
    report = cli.failure_report(caught.value, "cloud_judge")
    assert "provider_code" not in report
    assert "secret-value" not in json.dumps(report)


@pytest.mark.parametrize(
    "reason,status,expected",
    [
        ("API_KEY_INVALID", 400, "current Gemini API key"),
        ("SERVICE_DISABLED", 403, "Enable the Generative Language API"),
        ("BILLING_DISABLED", 403, "billing"),
        ("API_KEY_HTTP_REFERRER_BLOCKED", 403, "browser referrers"),
    ],
)
def test_google_error_reasons_provide_specific_private_account_recovery(reason, status, expected):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status,
                json={
                    "error": {
                        "status": "PERMISSION_DENIED",
                        "message": "private response",
                        "details": [{"reason": reason, "metadata": {"key": "private-key"}}],
                    }
                },
            )
        )
    ) as client:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            post_json(client, "https://generativelanguage.googleapis.com/v1beta", payload={})
    report = cli.failure_report(caught.value, "cloud_judge")
    assert report["provider_code"] == reason
    assert expected in report["hint"]
    assert "private-key" not in json.dumps(report)
    assert "private response" not in json.dumps(report)


def test_unknown_google_error_detail_is_never_displayed():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                400, json={"error": {"details": [{"reason": "SECRET_PRIVATE_REASON"}]}}
            )
        )
    ) as client:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            post_json(client, "https://generativelanguage.googleapis.com/v1beta", payload={})
    assert "SECRET_PRIVATE_REASON" not in json.dumps(
        cli.failure_report(caught.value, "cloud_judge")
    )


@pytest.mark.parametrize("failing_stage", ["ollama_worker", "cloud_judge"])
def test_live_cli_reports_which_request_failed(monkeypatch, capsys, failing_stage):
    monkeypatch.setattr(cli, "configure_provider", lambda: None)
    monkeypatch.setattr(cli, "verify_ollama", lambda: ["qwen3.5:9b"])

    def fail():
        request = httpx.Request("POST", "https://api.example/test")
        raise httpx.HTTPStatusError(
            "hidden", request=request, response=httpx.Response(401, request=request)
        )

    class Worker:
        def __init__(self, *args):
            pass

        def step(self, *args):
            if failing_stage == "ollama_worker":
                fail()
            return {"action": "map", "reason": "ready"}

    class Judge:
        def evaluate(self, *args):
            fail()

    monkeypatch.setattr(cli, "WorkerAgent", Worker)
    monkeypatch.setattr(cli, "make_judge", lambda: Judge())
    assert cli.main(["--no-desktop-discovery", "verify-live"]) == 2
    report = json.loads(capsys.readouterr().err)
    assert report["stage"] == failing_stage
    assert report["http_status"] == 401
