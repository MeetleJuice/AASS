"""Bounded official-provider model catalogs; credentials remain in HTTPS headers only.

Catalog entries are candidates, not evidence of generation entitlement or quota.
A separate authenticated generation/review check must validate the selected model.
"""

from __future__ import annotations

import json
import re
import time
from contextlib import nullcontext

import httpx

from tools.http_client import MAX_RESPONSE_BYTES

MAX_PAGES = 5
MAX_MODELS = 200
MAX_ITEMS = 1000
MAX_CATALOG_SECONDS = 30
PAGE_SIZE = 100
ENDPOINTS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
}
EXCLUDED_MODEL_TERMS = (
    "embedding",
    "image",
    "tts",
    "audio",
    "live",
    "realtime",
    "robotics",
    "deep-research",
    "transcribe",
    "search",
    "computer-use",
)
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class CatalogError(RuntimeError):
    """User-reviewable metadata only; no raw API message, URL query or credential."""

    def __init__(self, service: str, code: str, hint: str, status_code: int | None = None):
        self.service = service
        self.status_code = status_code
        self.code = code
        self.hint = hint
        super().__init__(hint)

    def as_dict(self):
        return {
            "status": "failed",
            "stage": "model_catalog",
            "service": self.service,
            "http_status": self.status_code,
            "code": self.code,
            "hint": self.hint,
        }


def _http_error(service, status):
    hints = {
        400: "The provider rejected the model-list request. Check the provider/key configuration.",
        401: "The provider rejected authentication. Check the selected provider's private API key.",
        402: "The provider requires available account credit or payment.",
        403: "The provider denied catalog access. Check API permissions, project and region access.",
        404: "The official provider model catalog is unavailable for this request. Check provider/project access.",
        429: "The provider reported a rate or quota limit. Check account usage and limits before retrying.",
    }
    return CatalogError(
        service,
        "provider_http_error",
        hints.get(status, "The provider could not return its model catalog. Check service status."),
        status,
    )


def _get_page(client, service, *, headers, params, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CatalogError(
            service,
            "catalog_timeout",
            "The model catalog took too long. Retry when the service is responsive.",
        )
    try:
        with client.stream(
            "GET",
            ENDPOINTS[service],
            headers=headers,
            params=params,
            follow_redirects=False,
            timeout=min(10.0, remaining),
        ) as response:
            if response.status_code != 200:
                raise _http_error(service, response.status_code)
            data = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline:
                    raise CatalogError(
                        service,
                        "catalog_timeout",
                        "The model catalog took too long. Retry when the service is responsive.",
                    )
                if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise CatalogError(
                        service,
                        "catalog_size_limit",
                        "The provider's catalog response exceeds the supported size limit.",
                    )
                data.extend(chunk)
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise CatalogError(
                service, "invalid_catalog", "The provider returned an invalid model catalog."
            )
        return payload
    except CatalogError:
        raise
    except httpx.TransportError:
        raise CatalogError(
            service,
            "connection_failed",
            "The model catalog could not be reached. Check the connection and provider status.",
        ) from None
    except (ValueError, TypeError, UnicodeError):
        raise CatalogError(
            service, "invalid_catalog", "The provider returned an invalid model catalog."
        ) from None


def _model_id(service, entry, api_key):
    if not isinstance(entry, dict):
        raise CatalogError(
            service, "invalid_catalog", "The provider returned an invalid model catalog entry."
        )
    name = entry.get("name") if service == "gemini" else entry.get("id")
    if not isinstance(name, str):
        raise CatalogError(
            service, "invalid_catalog", "The provider returned an invalid model identifier."
        )
    if service == "gemini":
        name = name.removeprefix("models/")
        methods = entry.get("supportedGenerationMethods", [])
        if not isinstance(methods, list):
            raise CatalogError(
                service, "invalid_catalog", "The provider returned invalid model capabilities."
            )
        if not name.startswith("gemini-") or "generateContent" not in methods:
            return None
    elif service == "anthropic":
        if not name.startswith("claude-"):
            return None
    elif not re.match(r"(?:gpt-|chatgpt-|o[1-9](?:-|$))", name):
        return None
    if (
        not MODEL_ID.fullmatch(name)
        or api_key in name
        or any(term in name.lower() for term in EXCLUDED_MODEL_TERMS)
    ):
        return None
    return name


def _next_cursor(service, payload):
    if service == "gemini":
        cursor = payload.get("nextPageToken")
    elif service == "anthropic":
        more = payload.get("has_more", False)
        if type(more) is not bool:
            raise CatalogError(
                service, "invalid_catalog", "The provider returned invalid pagination data."
            )
        cursor = payload.get("last_id") if more else None
        if more and not cursor:
            raise CatalogError(
                service, "invalid_catalog", "The provider omitted the next catalog cursor."
            )
    else:
        if payload.get("has_more"):
            raise CatalogError(
                service,
                "catalog_page_limit",
                "The provider returned an incomplete catalog that cannot be paginated safely.",
            )
        cursor = None
    if cursor in (None, ""):
        return None
    if not isinstance(cursor, str) or len(cursor) > 4096 or "\x00" in cursor:
        raise CatalogError(
            service, "invalid_catalog", "The provider returned invalid pagination data."
        )
    return cursor


def fetch_models(service: str, api_key: str, *, client: httpx.Client | None = None):
    """Return only actual text-model IDs from a bounded official provider catalog.

    The caller retains control of key lookup and preference persistence. Keys are
    never written to disk, printed, placed in query strings or sent on redirects.
    Passing a client is intended for test transports or caller-managed sessions.
    """
    if service not in ENDPOINTS:
        raise CatalogError(
            "unsupported",
            "unsupported_provider",
            "Choose Gemini, OpenAI or Anthropic for model discovery.",
        )
    if (
        not isinstance(api_key, str)
        or not api_key
        or len(api_key) > 8192
        or any(not 33 <= ord(char) <= 126 for char in api_key)
    ):
        raise CatalogError(
            service, "missing_key", "Select a private file with a usable API key for this provider."
        )
    if service == "gemini":
        headers = {"x-goog-api-key": api_key}
    elif service == "anthropic":
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    else:
        headers = {"Authorization": "Bearer " + api_key}
    owned = httpx.Client(timeout=10, follow_redirects=False) if client is None else client
    context = owned if client is None else nullcontext(owned)
    deadline = time.monotonic() + MAX_CATALOG_SECONDS
    models, seen_cursors, cursor, item_count = set(), set(), None, 0
    with context as session:
        for _ in range(MAX_PAGES):
            params = (
                {"pageSize": PAGE_SIZE}
                if service == "gemini"
                else {"limit": PAGE_SIZE}
                if service == "anthropic"
                else {}
            )
            if cursor is not None:
                params["pageToken" if service == "gemini" else "after_id"] = cursor
            payload = _get_page(session, service, headers=headers, params=params, deadline=deadline)
            entries = payload.get("models" if service == "gemini" else "data")
            if not isinstance(entries, list):
                raise CatalogError(
                    service, "invalid_catalog", "The provider did not return a model list."
                )
            item_count += len(entries)
            if item_count > MAX_ITEMS:
                raise CatalogError(
                    service,
                    "catalog_size_limit",
                    "The model catalog exceeds the supported item limit.",
                )
            for entry in entries:
                model = _model_id(service, entry, api_key)
                if model:
                    models.add(model)
                if len(models) > MAX_MODELS:
                    raise CatalogError(
                        service,
                        "catalog_size_limit",
                        "The provider returned too many text models to select safely.",
                    )
            cursor = _next_cursor(service, payload)
            if cursor is None:
                break
            if api_key in cursor:
                raise CatalogError(
                    service, "invalid_catalog", "The provider returned unsafe pagination data."
                )
            if cursor in seen_cursors:
                raise CatalogError(
                    service,
                    "invalid_catalog",
                    "The provider repeated a catalog page. Try again later.",
                )
            seen_cursors.add(cursor)
        else:
            raise CatalogError(
                service, "catalog_page_limit", "The model catalog exceeds the supported page limit."
            )
    if not models:
        raise CatalogError(
            service,
            "no_text_models",
            "The provider returned no compatible text-generation models. Check API permissions and provider/model availability.",
        )
    return [{"id": model, "label": model} for model in sorted(models, key=str.casefold)]
