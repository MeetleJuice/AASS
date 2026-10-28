"""Repeatable AASS bootstrap. Secret values never enter generated artifacts."""

import argparse
import json
import os
import shlex
import urllib.error
import urllib.request
from pathlib import Path

from settings import (
    CREDENTIAL_SETTINGS,
    is_link,
    ollama_url,
    provider_preferences,
    selected_credentials_file,
)

BUILD_ORDER = [
    (1, "Infrastructure & Safety", ["sandboxes/container.py", "circuit_breaker.py"]),
    (2, "Connectivity & MCP", ["tools/mcp_gateway.py", "tools/repo_mapper.py"]),
    (3, "Execution Engine", ["worker_agent.py", "tools/computer_use.py"]),
    (4, "Quality Assurance", ["trajectory.json", "stall_detector.py", "judge_evaluator.py"]),
    (5, "Executive Canvas", ["orchestration_canvas.py", "crdal_supervisor.py"]),
]


def load_credentials(path, *, provider_config=True):
    """Import simple KEY=value assignments into this process without evaluating code."""
    count = 0
    path = Path(path)
    if is_link(path) or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("Credentials file must be a regular file no larger than 64 KiB")
    content = path.read_bytes()
    encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    lines = content.decode(encoding).splitlines()
    extra_binding = None
    if provider_config:
        import re

        for line in lines:
            if "=" in line and line.split("=", 1)[0].strip() == "AASS_CUSTOM_KEY_VARIABLE":
                candidate = line.strip().split("=", 1)[1].strip().strip("\"'")
                if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}_(?:KEY|TOKEN)", candidate):
                    extra_binding = candidate
                    os.environ.setdefault("AASS_CUSTOM_KEY_VARIABLE", candidate)
                    from settings import SECRET_NAMES

                    SECRET_NAMES.add(candidate)
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        from provider_registry import CONFIG_NAMES

        if (key not in CREDENTIAL_SETTINGS and key != extra_binding) or (
            not provider_config and key in CONFIG_NAMES
        ):
            continue
        lexer = shlex.shlex(value.strip(), posix=True)
        lexer.whitespace_split = True
        lexer.commenters = "#"
        lexer.escape = ""
        value = " ".join(lexer)
        if value:
            os.environ.setdefault(key, value)
            count += 1
    return count


def configure_provider():
    """Resolve one explicit provider without sending credentials to a different host."""
    from urllib.parse import urlsplit

    preferences = provider_preferences()
    selected = os.environ.get("AASS_JUDGE_SERVICE") or preferences.get("service", "auto")
    from provider_registry import providers as registry

    providers = {
        service: (row["keys"], row["url"], row["model"], row["adapter"])
        for service, row in registry().items()
    }
    if selected not in {"auto", *providers}:
        raise ValueError("Unsupported provider selection")
    if selected == "auto" and os.environ.get("AASS_JUDGE_API_KEY"):
        if preferences.get("model"):
            os.environ["AASS_JUDGE_MODEL"] = preferences["model"]
        return
    candidates = providers.items() if selected == "auto" else [(selected, providers[selected])]
    for _service, (names, endpoint, model, adapter) in candidates:
        key = next((os.environ[name] for name in names if os.environ.get(name)), None)
        if not key and selected != "auto":
            base = os.environ.get("AASS_JUDGE_BASE_URL", "")
            if urlsplit(base).hostname == urlsplit(endpoint).hostname:
                key = os.environ.get("AASS_JUDGE_API_KEY")
        if not key:
            continue
        base = os.environ.get("AASS_JUDGE_BASE_URL")
        if selected == "auto" and base and urlsplit(base).hostname != urlsplit(endpoint).hostname:
            raise ValueError(
                "Cloud key and configured endpoint conflict. Select the intended provider in Start AASS settings"
            )
        os.environ["AASS_JUDGE_API_KEY"] = key
        os.environ["AASS_JUDGE_BASE_URL"] = endpoint
        os.environ["AASS_JUDGE_PROVIDER"] = adapter
        os.environ["AASS_JUDGE_MODEL"] = (
            preferences.get("model") or os.environ.get("AASS_JUDGE_MODEL") or model
        )
        return
    if selected != "auto":
        raise ValueError(
            "The selected cloud provider has no matching key in the environment or private credentials file"
        )


def discover_api_keys(*, configure=True):
    """Import fixed app-local .env files, Desktop .env and bounded credential folders."""
    scanned = 0
    # A user-selected application-local credential file is a fixed path, never a recursive scan.
    application = Path(__file__).resolve().parent
    selected_file = selected_credentials_file(application)
    if selected_file is not None:
        # A stale or unreadable explicit choice needs attention, not silent fallback.
        load_credentials(selected_file)
        if configure:
            configure_provider()
        return sorted(k for k in os.environ if k.startswith("AASS_") and k.endswith("API_KEY"))
    for name in (".env", ".env.txt"):
        local = application / name
        if local.is_file() and not is_link(local):
            try:
                load_credentials(local)
            except (OSError, UnicodeError, ValueError):
                continue
    for desktop in (Path.home() / "Desktop", Path.home() / "OneDrive/Desktop"):
        if not desktop.is_dir() or is_link(desktop):
            continue
        candidates = [desktop / ".env"]
        for folder in sorted(desktop.iterdir()):
            if (
                is_link(folder)
                or not folder.is_dir()
                or not any(
                    term in folder.name.lower() for term in ("key", "api", "token", "credential")
                )
            ):
                continue
            for directory, dirs, files in os.walk(folder, followlinks=False):
                base = Path(directory)
                dirs[:] = (
                    [d for d in sorted(dirs) if not d.startswith(".") and not is_link(base / d)]
                    if base == folder
                    else []
                )
                candidates.extend(
                    base / name
                    for name in sorted(files)
                    if name == ".env" or name.lower().endswith((".env", ".txt"))
                )
        for file in candidates:
            if is_link(file) or not file.is_file():
                continue
            scanned += 1
            if scanned > 100:
                raise RuntimeError(
                    "Credential folder scan exceeded 100 files; use --credentials-file"
                )
            try:
                load_credentials(file, provider_config=False)
            except (OSError, UnicodeError, ValueError):
                continue
    if configure:
        configure_provider()
    return sorted(k for k in os.environ if k.startswith("AASS_") and k.endswith("API_KEY"))


def select_worker(models):
    explicit = os.environ.get("AASS_WORKER_MODEL")
    if explicit:
        return explicit
    if "qwen3.5:9b" in models:
        return "qwen3.5:9b"
    usable = [model for model in models if "embed" not in model.lower()]
    return next(
        (model for model in usable if "qwen" in model.lower()),
        usable[0] if usable else "qwen3.5:9b",
    )


def verify_ollama():
    host = ollama_url()
    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=3) as response:  # nosec B310 # scheme/host validated by ollama_url
            return [m["name"] for m in json.load(response).get("models", [])]
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        return []


def bootstrap_workspace(root, models):
    root = Path(root)
    for directory in ("generated", "tools", "sandboxes", ".aass"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    blueprint = {
        "stack_version": "1.0.0",
        "primary_local_worker": select_worker(models),
        "available_models": models,
        "ollama_reachable": bool(models),
        "active_credentials": sorted(
            k for k in os.environ if k.startswith("AASS_") and k.endswith("API_KEY")
        ),
        "build_order": [
            {
                "layer": n,
                "name": name,
                "status": "implemented"
                if all((root / p).exists() for p in paths if p != "trajectory.json")
                else "pending",
                "files": paths,
            }
            for n, name, paths in BUILD_ORDER
        ],
    }
    (root / "generated/architecture_spec.json").write_text(json.dumps(blueprint, indent=2) + "\n")
    trajectory = root / "trajectory.json"
    if not trajectory.exists():
        trajectory.write_text(
            '[{"iteration": 0, "files_modified": [], "error_signature": "INIT"}]\n'
        )
    return blueprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--no-desktop-discovery", action="store_true")
    args = parser.parse_args()
    if args.credentials_file:
        load_credentials(args.credentials_file)
    if not args.no_desktop_discovery:
        try:
            discover_api_keys(configure=False)
        except (OSError, ValueError):
            # Architecture generation and package setup do not need cloud keys.
            import sys

            print(
                "Private credential-file selection needs attention; choose it again in the setup window. Local bootstrap will continue.",
                file=sys.stderr,
            )
    spec = bootstrap_workspace(args.root, verify_ollama())
    print(
        json.dumps(
            {
                "architecture_spec": str(args.root / "generated/architecture_spec.json"),
                "ollama_reachable": spec["ollama_reachable"],
                "available_models": spec["available_models"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
