"""Provider protocols use HTTP fixtures, never the attached user's credentials."""

import json

import httpx
import pytest

import setup_api as api
from initialize_aass import load_credentials
from judge_evaluator import JudgeEvaluator
from provider_registry import providers
from settings import provider_preferences, save_provider_preferences, subprocess_environment
from tools.model_catalog import CatalogError, fetch_models


@pytest.mark.parametrize("service", ["groq", "openrouter", "nvidia", "requesty", "huggingface"])
def test_compatible_provider_catalog_keys_are_bound_to_exact_host(service, monkeypatch):
    row = providers()[service]
    key = "PRIVATE_TEST_BINDING"
    monkeypatch.setenv(row["keys"][0], key)
    assert api.provider_key(service)[0] == key

    def route(request):
        assert str(request.url) == row["url"] + "/models"
        assert request.headers["Authorization"] == "Bearer " + key
        assert key not in str(request.url)
        return httpx.Response(
            200, json={"data": [{"id": "vendor/model-name"}, {"id": "vendor/embedding-model"}]}
        )

    with httpx.Client(transport=httpx.MockTransport(route)) as client:
        assert fetch_models(service, key, client=client) == [
            {"id": "vendor/model-name", "label": "vendor/model-name"}
        ]
    assert row["keys"][0] not in subprocess_environment()
    assert (
        JudgeEvaluator(key, "vendor/model-name", row["url"], "openai").model == "vendor/model-name"
    )


def test_custom_endpoint_and_explicit_model_are_available_without_catalog(monkeypatch, tmp_path):
    monkeypatch.setenv("AASS_CUSTOM_API_KEY", "fixture-key")
    monkeypatch.setenv("AASS_CUSTOM_BASE_URL", "https://chosen.example/v1")
    monkeypatch.setenv("AASS_CUSTOM_MODEL", "vendor/model")
    monkeypatch.setattr(api, "discover_api_keys", lambda **kw: None)
    assert api.models_report("custom")["models"][0]["id"] == "vendor/model"
    assert (
        JudgeEvaluator("fixture-key", "vendor/model", providers()["custom"]["url"]).base_url
        == "https://chosen.example/v1"
    )
    save_provider_preferences("custom", "vendor/model", tmp_path)
    assert provider_preferences(tmp_path)["service"] == "custom"


@pytest.mark.parametrize(
    "url",
    [
        "http://evil.example/v1",
        "https://user:pass@evil.example/v1",
        "https://evil.example/v1?key=private",
    ],
)
def test_invalid_custom_endpoint_rejected_before_catalog_request(monkeypatch, url):
    monkeypatch.setenv("AASS_CUSTOM_API_KEY", "fixture-key")
    monkeypatch.setenv("AASS_CUSTOM_BASE_URL", url)
    monkeypatch.setattr(api, "discover_api_keys", lambda **kw: None)
    monkeypatch.setattr(api, "fetch_models", lambda *args: pytest.fail("invalid endpoint used"))
    with pytest.raises(ValueError):
        api.models_report("custom")


def test_cloudflare_catalog_uses_account_and_filters_task(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a" * 32)

    def route(request):
        assert request.url.host == "api.cloudflare.com"
        assert "/accounts/" + "a" * 32 + "/ai/models/search" == request.url.path.removeprefix(
            "/client/v4"
        )
        return httpx.Response(
            200,
            json={
                "result": [
                    {"name": "@cf/vendor/chat", "task": {"name": "Text Generation"}},
                    {"name": "@cf/vendor/vector", "task": {"name": "Text Embeddings"}},
                ],
                "result_info": {"page": 1, "per_page": 50, "total_count": 2},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(route)) as client:
        assert fetch_models("cloudflare", "fixture", client=client)[0]["id"] == "@cf/vendor/chat"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
def test_installer_private_file_parses_quotes_comments_and_new_bindings(
    tmp_path, monkeypatch, encoding
):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    path = tmp_path / ".env.txt"
    path.write_text('  # comment\n\n GROQ_API_KEY = "private#value" # comment\n', encoding=encoding)
    assert load_credentials(path) == 1
    assert api.provider_key("groq")[0] == "private#value"
    assert "private#value" not in json.dumps(providers())


def test_custom_redirect_never_forwards_key(monkeypatch):
    monkeypatch.setenv("AASS_CUSTOM_BASE_URL", "https://chosen.example/v1")
    calls = []

    def route(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://unrelated.example/steal"})

    with httpx.Client(transport=httpx.MockTransport(route), follow_redirects=True) as client:
        with pytest.raises(CatalogError):
            fetch_models("custom", "fixture", client=client)
    assert len(calls) == 1


def test_custom_catalog_cannot_send_key_to_a_different_origin(monkeypatch):
    monkeypatch.setenv("AASS_CUSTOM_BASE_URL", "https://chosen.example/v1")
    monkeypatch.setenv("AASS_CUSTOM_MODELS_URL", "https://unrelated.example/models")
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: pytest.fail("key forwarded"))
    ) as client:
        with pytest.raises(CatalogError, match="configured provider host"):
            fetch_models("custom", "fixture", client=client)


def test_explicit_custom_binding_is_loaded_without_environment_injection(tmp_path, monkeypatch):
    monkeypatch.delenv("MY_VENDOR_API_KEY", raising=False)
    monkeypatch.delenv("AASS_CUSTOM_KEY_VARIABLE", raising=False)
    path = tmp_path / ".env.txt"
    path.write_text(
        "MY_VENDOR_API_KEY=private-custom-value\nAASS_CUSTOM_KEY_VARIABLE = MY_VENDOR_API_KEY\nPATH=must-not-be-imported\n"
    )
    load_credentials(path)
    assert providers()["custom"]["keys"] == ("MY_VENDOR_API_KEY",)
    assert api.provider_key("custom")[0] == "private-custom-value"
    assert "MY_VENDOR_API_KEY" not in subprocess_environment()


def test_legacy_desktop_files_cannot_enable_billing_or_custom_routes(tmp_path, monkeypatch):
    monkeypatch.delenv("AASS_SETUP_ALLOW_BILLABLE_CHECK", raising=False)
    monkeypatch.delenv("AASS_CUSTOM_BASE_URL", raising=False)
    path = tmp_path / "unselected.env"
    path.write_text(
        "AASS_SETUP_ALLOW_BILLABLE_CHECK=1\nAASS_CUSTOM_BASE_URL=https://unrelated.example/v1\n"
    )
    assert load_credentials(path, provider_config=False) == 0
    import os

    assert "AASS_SETUP_ALLOW_BILLABLE_CHECK" not in os.environ
    assert "AASS_CUSTOM_BASE_URL" not in os.environ
