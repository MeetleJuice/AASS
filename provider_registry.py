"""Explicit model-provider routes. Key names never infer arbitrary destinations."""

import os
import re
from urllib.parse import urlsplit

BASE = {
    "gemini": (
        "Google Gemini",
        "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta",
        "gemini",
    ),
    "openai": ("OpenAI", "OPENAI_API_KEY", "https://api.openai.com/v1", "openai"),
    "anthropic": ("Anthropic", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", "anthropic"),
    "groq": ("Groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1", "openai"),
    "openrouter": ("OpenRouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "openai"),
    "nvidia": ("NVIDIA", "NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1", "openai"),
    "requesty": ("Requesty", "REQUESTY_API_KEY", "https://router.requesty.ai/v1", "openai"),
    "huggingface": (
        "Hugging Face",
        "HUGGINGFACE_API_KEY",
        "https://router.huggingface.co/v1",
        "openai",
    ),
    "cloudflare": ("Cloudflare Workers AI", "CLOUDFLARE_API_TOKEN", "", "openai"),
    "custom": ("Custom model endpoint", "AASS_CUSTOM_API_KEY", "", "openai"),
}
ALIASES = {"gemini": ("GOOGLE_API_KEY",), "huggingface": ("HF_TOKEN",)}
KEY_NAMES = {row[1] for row in BASE.values()} | {
    name for names in ALIASES.values() for name in names
}
CONFIG_NAMES = {"AASS_" + service.upper() + "_MODEL" for service in BASE} | {
    "AASS_CUSTOM_KEY_VARIABLE",
    "AASS_CUSTOM_BASE_URL",
    "AASS_CUSTOM_PROTOCOL",
    "AASS_CUSTOM_MODEL",
    "AASS_CUSTOM_MODELS_URL",
    "CLOUDFLARE_ACCOUNT_ID",
    "AASS_CLOUDFLARE_MODEL",
    "AASS_JUDGE_SERVICE",
    "AASS_SETUP_ALLOW_BILLABLE_CHECK",
}


def valid_url(value):
    p = urlsplit(value)
    if (
        p.scheme != "https"
        or not p.hostname
        or p.username
        or p.password
        or p.query
        or p.fragment
        or p.port not in (None, 443)
    ):
        raise ValueError(
            "Model endpoints require HTTPS without credentials, query or a custom port"
        )
    secrets = [os.environ.get(name, "") for name in KEY_NAMES | {"AASS_JUDGE_API_KEY"}]
    if any(len(secret) >= 8 and secret in value for secret in secrets):
        raise ValueError("Credentials must not be embedded in provider URLs")
    return value.rstrip("/")


def providers():
    result = {}
    for service, (label, key, url, adapter) in BASE.items():
        model = os.environ.get("AASS_" + service.upper() + "_MODEL", "")
        if service == "cloudflare":
            account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
            if re.fullmatch(r"[a-fA-F0-9]{32}", account):
                url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1"
            model = os.environ.get("AASS_CLOUDFLARE_MODEL", "")
        if service == "custom":
            binding = os.environ.get("AASS_CUSTOM_KEY_VARIABLE", "AASS_CUSTOM_API_KEY")
            if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}_(?:KEY|TOKEN)", binding):
                key = binding
            url = os.environ.get("AASS_CUSTOM_BASE_URL", "")
            adapter = os.environ.get("AASS_CUSTOM_PROTOCOL", "openai")
            model = os.environ.get("AASS_CUSTOM_MODEL", "")
        models_url = url + "/models" if url else ""
        if service == "cloudflare" and url:
            models_url = url.removesuffix("/ai/v1") + "/ai/models/search"
        if service == "custom":
            models_url = os.environ.get("AASS_CUSTOM_MODELS_URL", models_url)
        result[service] = {
            "label": label,
            "keys": (key, *ALIASES.get(service, ())),
            "url": url,
            "adapter": adapter,
            "model": model,
            "models_url": models_url,
        }
    return result


def approved_hosts():
    hosts = set()
    for row in providers().values():
        if row["url"]:
            try:
                hosts.add(urlsplit(valid_url(row["url"])).hostname)
            except ValueError:
                continue
    return hosts
