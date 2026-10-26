"""Bounded JSON responses with normal HTTPS verification and no redirect following."""

import json

import httpx

MAX_RESPONSE_BYTES = 256 * 1024
GOOGLE_REASONS = {
    "API_KEY_INVALID",
    "API_KEY_EXPIRED",
    "API_KEY_SERVICE_BLOCKED",
    "API_KEY_HTTP_REFERRER_BLOCKED",
    "API_KEY_IP_ADDRESS_BLOCKED",
    "SERVICE_DISABLED",
    "BILLING_DISABLED",
    "CONSUMER_INVALID",
}


def post_json(client, url, *, payload, headers=None):
    with client.stream("POST", url, json=payload, headers=headers) as response:
        data = bytearray()
        for chunk in response.iter_bytes():
            if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                raise ValueError("Model response exceeds hard size limit")
            data.extend(chunk)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            # Report only known machine-readable codes, never arbitrary API messages.
            try:
                detail = json.loads(data).get("error", {})
            except (ValueError, AttributeError):
                detail = {}
            known = {
                "invalid_api_key",
                "insufficient_quota",
                "rate_limit_exceeded",
                "billing_hard_limit_reached",
                "model_not_found",
                "permission_denied",
                "invalid_request_error",
                "context_length_exceeded",
                "NOT_FOUND",
                "RESOURCE_EXHAUSTED",
                "PERMISSION_DENIED",
                "UNAUTHENTICATED",
            }
            if isinstance(detail, dict):
                reasons = detail.get("details", [])
                if isinstance(reasons, list):
                    for entry in reasons:
                        reason = entry.get("reason") if isinstance(entry, dict) else None
                        if isinstance(reason, str) and reason in GOOGLE_REASONS:
                            error.provider_code = reason
                            break
                for field in ("code", "type", "status"):
                    code = detail.get(field)
                    if (
                        not getattr(error, "provider_code", None)
                        and isinstance(code, str)
                        and code in known
                    ):
                        error.provider_code = code
                        break
            raise
    return json.loads(data)
