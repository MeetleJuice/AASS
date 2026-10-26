import json

import httpx
import pytest

from tools.model_catalog import CatalogError, fetch_models

KEY = "fixture-private-model-catalog-key"


def gemini(name, methods=None):
    return {
        "name": "models/" + name,
        "supportedGenerationMethods": ["generateContent"] if methods is None else methods,
    }


def call(handler, service="gemini", **kwargs):
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        return fetch_models(service, KEY, client=client, **kwargs)


def test_gemini_protocol_pagination_and_text_only_candidates():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.scheme == "https"
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path == "/v1beta/models"
        assert KEY not in str(request.url)
        assert request.headers["x-goog-api-key"] == KEY
        assert "Authorization" not in request.headers
        assert request.url.params["pageSize"] == "100"
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "models": [
                        gemini("gemini-current-pro"),
                        gemini("gemini-current-image"),
                        gemini("gemini-current-tts"),
                        gemini("gemini-current-native-audio"),
                        gemini("gemini-current-live"),
                        gemini("gemini-current-robotics"),
                        gemini("gemini-embedding", ["embedContent"]),
                        gemini("gemini-no-generation", ["countTokens"]),
                    ],
                    "nextPageToken": "opaque-next-token",
                },
            )
        assert request.url.params["pageToken"] == "opaque-next-token"
        return httpx.Response(
            200, json={"models": [gemini("gemini-current-pro"), gemini("gemini-flash-latest")]}
        )

    result = call(handler)
    assert result == [
        {"id": "gemini-current-pro", "label": "gemini-current-pro"},
        {"id": "gemini-flash-latest", "label": "gemini-flash-latest"},
    ]
    assert len(requests) == 2


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 429, 500])
def test_http_errors_are_safe_metadata_only(status):
    with pytest.raises(CatalogError) as caught:
        call(
            lambda request: httpx.Response(
                status, json={"error": {"message": KEY + " private provider message", "code": KEY}}
            )
        )
    assert caught.value.status_code == status
    assert caught.value.service == "gemini"
    assert caught.value.as_dict()["http_status"] == status
    assert KEY not in str(caught.value)
    assert KEY not in repr(caught.value)
    assert KEY not in json.dumps(caught.value.as_dict())
    assert caught.value.__cause__ is None


def test_redirect_does_not_forward_the_key_to_another_host():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://untrusted.example/steal"})

    with pytest.raises(CatalogError) as caught:
        call(handler)
    assert caught.value.status_code == 302
    assert len(requests) == 1


def test_transport_error_does_not_echo_request_or_credentials():
    def handler(request):
        raise httpx.ConnectError(KEY + " exception body", request=request)

    with pytest.raises(CatalogError) as caught:
        call(handler)
    assert caught.value.code == "connection_failed"
    assert KEY not in str(caught.value)
    assert KEY not in json.dumps(caught.value.as_dict())
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"models": {}},
        {"models": [None]},
        {"models": [{"name": None}]},
        {"models": [gemini("gemini-current", "generateContent")]},
    ],
)
def test_malformed_catalog_is_not_available_model_success(body):
    with pytest.raises(CatalogError) as caught:
        call(lambda request: httpx.Response(200, json=body))
    assert caught.value.code == "invalid_catalog"


def test_invalid_json_has_no_raw_body_in_exception():
    with pytest.raises(CatalogError) as caught:
        call(lambda request: httpx.Response(200, content=KEY))
    assert caught.value.code == "invalid_catalog"
    assert KEY not in str(caught.value)


def test_empty_text_catalog_is_distinct_from_auth_failure():
    with pytest.raises(CatalogError) as caught:
        call(lambda request: httpx.Response(200, json={"models": [gemini("gemini-image")]}))
    assert caught.value.code == "no_text_models"
    assert caught.value.status_code is None


def test_response_byte_limit_is_enforced():
    from tools.http_client import MAX_RESPONSE_BYTES

    with pytest.raises(CatalogError) as caught:
        call(lambda request: httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1)))
    assert caught.value.code == "catalog_size_limit"


def test_model_limit_is_enforced(monkeypatch):
    monkeypatch.setattr("tools.model_catalog.MAX_MODELS", 2)
    with pytest.raises(CatalogError) as caught:
        call(
            lambda request: httpx.Response(
                200, json={"models": [gemini("gemini-a"), gemini("gemini-b"), gemini("gemini-c")]}
            )
        )
    assert caught.value.code == "catalog_size_limit"


def test_raw_item_limit_is_enforced(monkeypatch):
    monkeypatch.setattr("tools.model_catalog.MAX_ITEMS", 1)
    with pytest.raises(CatalogError) as caught:
        call(
            lambda request: httpx.Response(
                200, json={"models": [gemini("gemini-a"), gemini("gemini-b")]}
            )
        )
    assert caught.value.code == "catalog_size_limit"


def test_page_limit_is_enforced(monkeypatch):
    monkeypatch.setattr("tools.model_catalog.MAX_PAGES", 2)
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(
            200, json={"models": [gemini("gemini-a")], "nextPageToken": f"cursor-{count}"}
        )

    with pytest.raises(CatalogError) as caught:
        call(handler)
    assert caught.value.code == "catalog_page_limit"
    assert count == 2


def test_repeated_and_invalid_cursors_are_rejected():
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(200, json={"models": [gemini("gemini-a")], "nextPageToken": "same"})

    with pytest.raises(CatalogError, match="repeated"):
        call(handler)
    assert count == 2
    with pytest.raises(CatalogError) as caught:
        call(
            lambda request: httpx.Response(
                200, json={"models": [gemini("gemini-a")], "nextPageToken": {"secret": KEY}}
            )
        )
    assert caught.value.code == "invalid_catalog"


def test_total_deadline_is_enforced(monkeypatch):
    ticks = iter([0, 31])
    monkeypatch.setattr("tools.model_catalog.time.monotonic", lambda: next(ticks))
    requested = []
    with pytest.raises(CatalogError) as caught:
        call(lambda request: requested.append(request))
    assert caught.value.code == "catalog_timeout"
    assert requested == []


@pytest.mark.parametrize(
    "key", ["", None, "has\nnewline", "has\rcarriage", "bad\x00key", "key with spaces", "unicode-é"]
)
def test_missing_or_unsafe_key_is_not_sent(key):
    requested = []
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: requested.append(request))
    ) as client:
        with pytest.raises(CatalogError) as caught:
            fetch_models("gemini", key, client=client)
    assert caught.value.code == "missing_key"
    assert requested == []


def test_openai_catalog_uses_bearer_header_and_filters_nonchat_models():
    def handler(request):
        assert request.url == "https://api.openai.com/v1/models"
        assert request.headers["Authorization"] == "Bearer " + KEY
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": name}
                    for name in [
                        "gpt-current",
                        "o3",
                        "gpt-current-audio",
                        "gpt-image-1",
                        "text-embedding-current",
                        "whisper-1",
                        "gpt-realtime",
                        "gpt-current-transcribe",
                    ]
                ]
            },
        )

    assert call(handler, "openai") == [
        {"id": "gpt-current", "label": "gpt-current"},
        {"id": "o3", "label": "o3"},
    ]


def test_anthropic_catalog_has_fixed_header_and_bounded_cursor_pagination():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "api.anthropic.com"
        assert request.url.path == "/v1/models"
        assert request.headers["x-api-key"] == KEY
        assert request.headers["anthropic-version"] == "2023-06-01"
        if len(requests) == 1:
            assert request.url.params["limit"] == "100"
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "claude-first"}],
                    "has_more": True,
                    "last_id": "claude-first",
                },
            )
        assert request.url.params["after_id"] == "claude-first"
        return httpx.Response(200, json={"data": [{"id": "claude-second"}], "has_more": False})

    assert call(handler, "anthropic") == [
        {"id": "claude-first", "label": "claude-first"},
        {"id": "claude-second", "label": "claude-second"},
    ]


def test_anthropic_missing_cursor_and_unknown_provider_are_rejected():
    with pytest.raises(CatalogError) as caught:
        call(
            lambda request: httpx.Response(
                200, json={"data": [{"id": "claude-model"}], "has_more": True}
            ),
            "anthropic",
        )
    assert caught.value.code == "invalid_catalog"
    with pytest.raises(CatalogError) as caught:
        fetch_models(KEY, KEY)
    assert caught.value.service == "unsupported"
    assert KEY not in json.dumps(caught.value.as_dict())


def test_provider_cannot_echo_key_back_into_a_pagination_query():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"models": [gemini("gemini-a")], "nextPageToken": KEY})

    with pytest.raises(CatalogError) as caught:
        call(handler)
    assert caught.value.code == "invalid_catalog"
    assert len(requests) == 1
    assert KEY not in json.dumps(caught.value.as_dict())
