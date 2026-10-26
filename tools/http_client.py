"""Bounded JSON responses with normal HTTPS verification and no redirect following."""

import json

MAX_RESPONSE_BYTES = 256 * 1024


def post_json(client, url, *, payload, headers=None):
    with client.stream("POST", url, json=payload, headers=headers) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_bytes():
            if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                raise ValueError("Model response exceeds hard size limit")
            data.extend(chunk)
    return json.loads(data)
