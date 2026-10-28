import json
import os

import httpx
import pytest

import setup_api as api
from settings import CREDENTIAL_SETTINGS
from tools.model_catalog import CatalogError

SECRET = "PRIVATE_TEST_VALUE"


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    for name in CREDENTIAL_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(api, "discover_api_keys", lambda **kwargs: [])
    monkeypatch.setattr(api.settings, "provider_preferences", lambda: {})


def test_credentials_metadata_discloses_binding_names_only(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    report = api.credentials_report()
    assert report["status"] == "ok"
    assert report["providers"][0] == {
        "id": "gemini",
        "label": "Google Gemini",
        "key_present": True,
        "source_binding": "GEMINI_API_KEY",
    }
    assert not report["providers"][1]["key_present"]
    assert SECRET not in json.dumps(report)


@pytest.mark.parametrize(
    "service,base,expected",
    [
        ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", True),
        ("openai", "https://generativelanguage.googleapis.com/v1beta/openai", False),
        ("gemini", "https://api.openai.com/v1", False),
        ("gemini", "https://generativelanguage.googleapis.com.attacker.test/v1", False),
        ("gemini", "http://generativelanguage.googleapis.com/v1", False),
        ("gemini", "https://generativelanguage.googleapis.com/v1?key=private", False),
        ("gemini", "https://user@ generativelanguage.googleapis.com/v1", False),
        ("anthropic", "https://api.anthropic.com/v1", True),
        ("openai", "", False),
    ],
)
def test_generic_key_never_crosses_provider_hosts(monkeypatch, service, base, expected):
    monkeypatch.setenv("AASS_JUDGE_API_KEY", SECRET)
    monkeypatch.setenv("AASS_JUDGE_BASE_URL", base)
    key, binding = api.provider_key(service)
    assert bool(key) is expected
    assert binding == ("AASS_JUDGE_API_KEY" if expected else None)


def test_standard_key_takes_precedence_over_matching_generic_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "standard")
    monkeypatch.setenv("AASS_JUDGE_API_KEY", SECRET)
    monkeypatch.setenv(
        "AASS_JUDGE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
    )
    assert api.provider_key("gemini") == ("standard", "GOOGLE_API_KEY")


def test_models_catalog_keeps_provider_and_exact_ids(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    calls = []
    monkeypatch.setattr(
        api,
        "fetch_models",
        lambda service, key: (
            calls.append((service, key)) or [{"id": "gemini-test", "label": "gemini-test"}]
        ),
    )
    report = api.models_report("gemini")
    assert calls == [("gemini", SECRET)]
    assert report["catalog_only"] is True
    assert report["models"][0]["id"] == "gemini-test"
    assert SECRET not in json.dumps(report)


def test_model_list_without_key_makes_no_request(monkeypatch, capsys):
    monkeypatch.setattr(api, "fetch_models", lambda *args: pytest.fail("unexpected request"))
    assert api.main(["models", "--service", "gemini"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["code"] == "missing_key"
    assert "file" in report["hint"]


def test_empty_model_catalog_is_actionable(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setattr(api, "fetch_models", lambda *args: [])
    assert api.main(["models", "--service", "gemini"]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "no_text_models"


def test_catalog_failure_preserves_safe_status(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)

    def fail(*args):
        raise CatalogError("gemini", "provider_http_error", "Check API permissions.", 403)

    monkeypatch.setattr(api, "fetch_models", fail)
    assert api.main(["models", "--service", "gemini"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["http_status"] == 403
    assert report["status"] == "error"
    assert SECRET not in json.dumps(report)


def test_worker_probe_is_independent_of_cloud_key(monkeypatch):
    monkeypatch.setattr(api, "verify_ollama", lambda: ["qwen3.5:9b"])
    calls = []

    class Worker:
        def __init__(self, host, model):
            calls.append((host, model))

        def step(self, *args):
            return {"action": "map", "reason": SECRET}

    monkeypatch.setattr(api, "WorkerAgent", Worker)
    report = api.verify_worker_report()
    assert calls == [("http://127.0.0.1:11434", "qwen3.5:9b")]
    assert report["worker_action"] == "map"
    assert SECRET not in json.dumps(report)


def test_missing_worker_gives_install_action_without_generation(monkeypatch, capsys):
    monkeypatch.setattr(api, "verify_ollama", lambda: [])
    monkeypatch.setattr(api, "WorkerAgent", lambda *args: pytest.fail("unexpected generation"))
    assert api.main(["verify-worker"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["code"] == "worker_model_missing"
    assert "in Ollama" in report["hint"]
    assert "No large model is downloaded automatically" in report["hint"]


def test_wrong_worker_action_does_not_pass(monkeypatch, capsys):
    monkeypatch.setattr(api, "verify_ollama", lambda: ["qwen3.5:9b"])

    class Worker:
        def __init__(self, *args):
            pass

        def step(self, *args):
            return {"action": "finish", "reason": SECRET}

    monkeypatch.setattr(api, "WorkerAgent", Worker)
    assert api.main(["verify-worker"]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "worker_protocol_failed"


def test_cloud_probe_uses_selected_service_and_does_not_retest_worker(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setattr(api, "verify_ollama", lambda: pytest.fail("unexpected worker probe"))
    calls = []

    class Judge:
        def __init__(self, *args):
            calls.append(args)

        def evaluate(self, *args):
            return {"approved": True, "reason": SECRET, "issues": []}

    monkeypatch.setattr(api, "JudgeEvaluator", Judge)
    report = api.verify_judge_report("gemini", "gemini-test")
    assert calls == [
        (SECRET, "gemini-test", "https://generativelanguage.googleapis.com/v1beta", "gemini")
    ]
    assert report["approved"] is True
    assert SECRET not in json.dumps(report)
    assert "AASS_JUDGE_MODEL" not in os.environ


@pytest.mark.parametrize("model", ["https://bad.test", "gemini test", SECRET])
def test_invalid_model_never_reaches_cloud(monkeypatch, model):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setattr(api, "JudgeEvaluator", lambda *args: pytest.fail("unexpected request"))
    with pytest.raises(api.SetupError, match="Select a model"):
        api.verify_judge_report("gemini", model)


@pytest.mark.parametrize("status", [401, 403, 404, 429])
def test_cloud_http_failures_are_recoverable_and_secret_free(monkeypatch, capsys, status):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)

    class Judge:
        def __init__(self, *args):
            pass

        def evaluate(self, *args):
            request = httpx.Request(
                "POST", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            )
            raise httpx.HTTPStatusError(
                SECRET,
                request=request,
                response=httpx.Response(status, request=request, json={"error": SECRET}),
            )

    monkeypatch.setattr(api, "JudgeEvaluator", Judge)
    assert api.main(["verify-judge", "--service", "gemini", "--model", "gemini-test"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["http_status"] == status
    assert report["stage"] == "cloud_judge"
    assert report["model"] == "gemini-test"
    assert report["service"] == "gemini"
    assert report["api_route"] == "generateContent"
    assert SECRET not in json.dumps(report)
    if status == 404:
        assert "Reload available models" in report["hint"]
        assert "Do not reinstall" in report["hint"]


def test_arbitrary_exception_text_never_reaches_gui(monkeypatch, capsys):
    def fail(**kwargs):
        raise ValueError(SECRET)

    monkeypatch.setattr(api, "discover_api_keys", fail)
    assert api.main(["credentials"]) == 2
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    report = json.loads(output.out)
    assert report["code"] == "credentials_configuration"


def test_discovered_gemini_model_is_checked_using_the_same_native_api(monkeypatch, capsys):
    from tools.model_catalog import ENDPOINTS

    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    original_client = httpx.Client
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["x-goog-api-key"] == SECRET
        assert SECRET not in str(request.url)
        if request.method == "GET":
            assert str(request.url).split("?")[0] == ENDPOINTS["gemini"]
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-listed-flash",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ]
                },
            )
        assert request.method == "POST"
        assert (
            str(request.url)
            == "https://generativelanguage.googleapis.com/v1beta/models/gemini-listed-flash:generateContent"
        )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "approved": True,
                                            "reason": "Protocol sample matches.",
                                            "issues": [],
                                        }
                                    )
                                }
                            ]
                        },
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    assert api.main(["models", "--service", "gemini"]) == 0
    model = json.loads(capsys.readouterr().out)["models"][0]["id"]
    assert api.main(["verify-judge", "--service", "gemini", "--model", model]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["approved"]
    assert [request.method for request in requests] == ["GET", "POST"]
    assert SECRET not in json.dumps(result)


def test_rejected_secret_model_is_never_echoed_in_error_context(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    assert api.main(["verify-judge", "--service", "gemini", "--model", SECRET]) == 2
    result = capsys.readouterr().out
    assert SECRET not in result
    assert "model" not in json.loads(result)
