"""Validated network and credential configuration; no secret values are logged."""

import os
from urllib.parse import urlsplit

from provider_registry import CONFIG_NAMES, KEY_NAMES, approved_hosts, providers

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
JUDGE_HOSTS = {"api.openai.com", "generativelanguage.googleapis.com", "api.anthropic.com"}
CREDENTIAL_SETTINGS = {
    "AASS_SETUP_ALLOW_BILLABLE_CHECK",
    "OLLAMA_HOST",
    "AASS_WORKER_MODEL",
    "AASS_JUDGE_API_KEY",
    "AASS_JUDGE_MODEL",
    "AASS_JUDGE_BASE_URL",
    "AASS_JUDGE_PROVIDER",
    "AASS_POSTGRES_DSN",
    "AASS_POSTGRES_SCHEMAS",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
}
SECRET_NAMES = {
    "AASS_JUDGE_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "AASS_POSTGRES_DSN",
}


CREDENTIAL_SETTINGS.update(KEY_NAMES | CONFIG_NAMES)
SECRET_NAMES.update(KEY_NAMES)
SECRET_NAMES.update(key for row in providers().values() for key in row["keys"])


def ollama_url(value=None):
    value = (value or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    if "://" not in value:
        value = "http://" + value
    parsed = urlsplit(value)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or parsed.scheme not in ("http", "https")
    ):
        raise ValueError("OLLAMA_HOST must be an HTTP(S) origin without credentials or a path")
    _ = parsed.port
    if parsed.scheme != "https" and parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError("Remote Ollama requires HTTPS; local loopback HTTP is supported")
    return value


def judge_url(value, provider="openai"):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Judge requires HTTPS without credentials, query, fragment or custom port")
    custom = {
        host.strip().lower()
        for host in os.environ.get("AASS_ALLOWED_JUDGE_HOSTS", "").split(",")
        if host.strip()
    }
    if parsed.hostname not in JUDGE_HOSTS | custom | approved_hosts():
        raise ValueError(
            "Judge host is not approved. Set AASS_ALLOWED_JUDGE_HOSTS explicitly in the process environment for a trusted custom provider"
        )
    if parsed.hostname in JUDGE_HOSTS:
        if (provider == "anthropic") != (parsed.hostname == "api.anthropic.com"):
            raise ValueError("Judge adapter and endpoint belong to different providers")
        if (provider == "gemini") and parsed.hostname != "generativelanguage.googleapis.com":
            raise ValueError("Judge adapter and endpoint belong to different providers")
    if provider == "gemini" and (
        parsed.hostname != "generativelanguage.googleapis.com"
        or parsed.path.rstrip("/") not in {"/v1beta", "/v1", "/v1beta/openai"}
    ):
        raise ValueError("Native Gemini requires its official versioned API endpoint")
    return value.rstrip("/")


def subprocess_environment(*, credentials=False):
    environment = os.environ.copy()
    if not credentials:
        for name in list(environment):
            upper = name.upper()
            if (
                upper in SECRET_NAMES
                or upper.endswith(("_API_KEY", "_TOKEN", "_PASSWORD", "_DSN"))
                or upper in ("GITHUB_TOKEN", "GH_TOKEN")
            ):
                environment.pop(name, None)
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def provider_preferences(root=None):
    import json
    from pathlib import Path

    root = Path(root) if root is not None else Path(__file__).resolve().parent
    path = root / ".aass/provider.json"
    if is_link(path):
        raise ValueError("Invalid provider settings file")
    if not path.exists():
        return {}
    if path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError("Invalid provider settings file")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or set(data) - {"service", "model"}
        or data.get("service") not in {"auto", *providers()}
        or not isinstance(data.get("model", ""), str)
    ):
        raise ValueError("Invalid provider settings; choose the provider again in Start AASS")
    return data


def save_provider_preferences(service, model="", root=None):
    import re
    from pathlib import Path

    from telemetry import atomic_json

    if service not in {"auto", *providers()}:
        raise ValueError("Unknown provider selection")
    if model and not re.fullmatch(r"[A-Za-z0-9@][A-Za-z0-9_./:@-]{0,255}", model):
        raise ValueError(
            "Model name must contain only letters, numbers, dots, slashes, colons or hyphens"
        )
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    atomic_json(root / ".aass/provider.json", {"service": service, "model": model})


def is_link(path):
    """Windows directory junctions require the same containment policy as symlinks."""
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def selected_credentials_file(root=None):
    """Read a user-chosen path, never a copy of its credential contents."""
    import json
    from pathlib import Path

    root = Path(root) if root is not None else Path(__file__).resolve().parent
    binding = root / ".aass/credentials.json"
    if is_link(binding):
        raise ValueError("Invalid credential-file selection; choose your file again")
    if not binding.exists():
        return None
    if is_link(binding) or binding.stat().st_size > 8192:
        raise ValueError("Invalid credential-file selection; choose your file again")
    data = json.loads(binding.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"path"} or not isinstance(data["path"], str):
        raise ValueError("Invalid credential-file selection; choose your file again")
    path = Path(data["path"])
    if not path.is_absolute():
        raise ValueError("Choose an absolute credential-file path")
    return path


def save_credentials_file(path, root=None):
    from pathlib import Path

    from telemetry import atomic_json

    path = Path(path).expanduser().absolute()
    if is_link(path) or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("Choose a regular .env or text file no larger than 64 KiB")
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    atomic_json(root / ".aass/credentials.json", {"path": str(path)})
