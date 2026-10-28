"""Model calls are fixtures; these tests do not assert live provider access."""

import json

import httpx
import pytest

import setup_api as api
import setup_automation as auto
from settings import save_provider_preferences


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv("AASS_SETUP_ALLOW_BILLABLE_CHECK", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "private-test-value")
    monkeypatch.setattr(
        api,
        "provider_key",
        lambda service: ("private-test-value", "fixture") if service == "gemini" else (None, None),
    )
    monkeypatch.setattr(api, "verify_worker_report", lambda: {"status": "ok"})
    monkeypatch.setattr(
        api,
        "models_report",
        lambda service: {
            "models": [{"id": "model-b"}, {"id": "model-a"}, {"id": "model-c"}, {"id": "model-d"}]
        },
    )
    monkeypatch.setattr(auto, "local_services_ready", lambda: True)
    return tmp_path


def http_error(code):
    request = httpx.Request(
        "POST", "https://generativelanguage.googleapis.com/v1beta/models/fixture:generateContent"
    )
    return httpx.HTTPStatusError(
        "private-test-value", request=request, response=httpx.Response(code, request=request)
    )


def test_no_consent_makes_no_model_calls(configured, monkeypatch):
    monkeypatch.delenv("AASS_SETUP_ALLOW_BILLABLE_CHECK")
    monkeypatch.setattr(api, "verify_worker_report", lambda: pytest.fail("unauthorized model call"))
    assert auto.run(configured)["status"] == "needs_action"


def test_fallback_404_and_saved_success_are_bounded_and_private(configured, monkeypatch):
    calls = []

    def judge(service, model):
        calls.append((service, model))
        if len(calls) == 1:
            raise http_error(404)
        return {"status": "ok"}

    monkeypatch.setattr(api, "verify_judge_report", judge)
    result = auto.run(configured)
    assert result["status"] == "ready"
    assert len(calls) == 2 and all(service == "gemini" for service, _ in calls)
    assert "private-test-value" not in (configured / ".aass/automatic-setup.json").read_text()
    assert auto.run(configured)["status"] == "ready"
    assert len(calls) == 2
    monkeypatch.setenv("GEMINI_API_KEY", "changed-private-value")
    assert auto.saved_result(configured) is None


@pytest.mark.parametrize("code", [401, 403, 429, 500])
def test_quota_auth_and_server_errors_stop_without_fallback(configured, monkeypatch, code):
    calls = []

    def judge(service, model):
        calls.append(model)
        raise http_error(code)

    monkeypatch.setattr(api, "verify_judge_report", judge)
    assert auto.run(configured)["status"] == "needs_action"
    assert len(calls) == 1
    assert auto.run(configured)["status"] == "needs_action"
    assert len(calls) == 1


def test_saved_choice_is_first_and_failure_budget_is_three(configured, monkeypatch):
    save_provider_preferences("gemini", "model-c", configured)
    calls = []

    def judge(service, model):
        calls.append(model)
        raise http_error(404)

    monkeypatch.setattr(api, "verify_judge_report", judge)
    assert auto.run(configured)["status"] == "needs_action"
    assert calls[0] == "model-c" and len(calls) == 3


def test_multiple_providers_require_choice_without_billing(configured, monkeypatch):
    monkeypatch.setattr(api, "provider_key", lambda service: ("fixture", "fixture"))
    monkeypatch.setattr(api, "verify_worker_report", lambda: pytest.fail("provider was not chosen"))
    assert auto.run(configured)["status"] == "needs_action"


def test_cached_ready_requires_running_local_services(configured, monkeypatch):
    monkeypatch.setattr(api, "verify_judge_report", lambda *args: {"status": "ok"})
    assert auto.run(configured)["status"] == "ready"
    monkeypatch.setattr(auto, "local_services_ready", lambda: False)
    assert auto.saved_result(configured)["status"] == "needs_action"
    data = json.loads((configured / ".aass/automatic-setup.json").read_text())
    assert data["status"] == "ready"  # Preserve working cloud selection for recovery.


def test_interrupted_paid_check_is_not_repeated_on_reopen(configured, monkeypatch):
    calls = []

    def interrupted(service, model):
        calls.append(model)
        raise KeyboardInterrupt()

    monkeypatch.setattr(api, "verify_judge_report", interrupted)
    with pytest.raises(KeyboardInterrupt):
        auto.run(configured)
    assert auto.run(configured)["status"] == "needs_action"
    assert len(calls) == 1
    assert json.loads((configured / ".aass/automatic-setup.json").read_text())["attempts"] == 1
