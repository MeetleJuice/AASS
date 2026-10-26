"""Repeatable AASS bootstrap. Secret values never enter generated artifacts."""

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

BUILD_ORDER = [
    (1, "Infrastructure & Safety", ["sandboxes/container.py", "circuit_breaker.py"]),
    (2, "Connectivity & MCP", ["tools/mcp_gateway.py", "tools/repo_mapper.py"]),
    (3, "Execution Engine", ["worker_agent.py", "tools/computer_use.py"]),
    (4, "Quality Assurance", ["trajectory.json", "stall_detector.py", "judge_evaluator.py"]),
    (5, "Executive Canvas", ["orchestration_canvas.py", "crdal_supervisor.py"]),
]


def load_credentials(path):
    """Import simple KEY=value assignments into this process without evaluating code."""
    count = 0
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("Credentials file must be a regular file no larger than 64 KiB")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        if not re.fullmatch(
            r"(?:AASS_[A-Z0-9_]+|OLLAMA_HOST|OPENAI_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|ANTHROPIC_API_KEY)",
            key,
        ):
            continue
        value = value.strip().strip("\"'")
        if value:
            os.environ.setdefault(key, value)
            count += 1
    return count


PROVIDER_DEFAULTS = (
    ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4.1"),
    ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-pro"),
    ("GOOGLE_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-pro"),
)


def configure_provider():
    """Map known provider bindings without copying secrets to files or printing values."""
    if os.environ.get("AASS_JUDGE_API_KEY"):
        return
    if os.environ.get("ANTHROPIC_API_KEY") and not any(
        os.environ.get(item[0]) for item in PROVIDER_DEFAULTS
    ):
        os.environ["AASS_JUDGE_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
        os.environ.setdefault("AASS_JUDGE_PROVIDER", "anthropic")
        os.environ.setdefault("AASS_JUDGE_BASE_URL", "https://api.anthropic.com/v1")
        os.environ.setdefault("AASS_JUDGE_MODEL", "claude-sonnet-4-5")
        return
    for name, endpoint, model in PROVIDER_DEFAULTS:
        if os.environ.get(name):
            os.environ["AASS_JUDGE_API_KEY"] = os.environ[name]
            os.environ.setdefault("AASS_JUDGE_BASE_URL", endpoint)
            os.environ.setdefault("AASS_JUDGE_MODEL", model)
            return


def discover_api_keys():
    """Bounded automatic Desktop discovery. Only recognized settings are imported."""
    scanned = 0
    for desktop in (Path.home() / "Desktop", Path.home() / "OneDrive/Desktop"):
        if not desktop.is_dir() or desktop.is_symlink():
            continue
        for directory, dirs, files in os.walk(desktop, followlinks=False):
            base = Path(directory)
            depth = len(base.relative_to(desktop).parts)
            dirs[:] = (
                sorted(d for d in dirs if not d.startswith(".") and not (base / d).is_symlink())
                if depth < 3
                else []
            )
            credentials_folder = any(
                term in part.lower()
                for part in base.relative_to(desktop).parts
                for term in ("key", "api", "token", "credential")
            )
            for name in sorted(files):
                file = base / name
                if (
                    file.is_symlink()
                    or not file.is_file()
                    or not (
                        name == ".env"
                        or name.endswith(".env")
                        or (credentials_folder and name.endswith(".txt"))
                    )
                ):
                    continue
                scanned += 1
                if scanned > 100:
                    raise RuntimeError(
                        "Desktop credentials scan exceeded 100 files; use --credentials-file"
                    )
                if file.stat().st_size <= 64 * 1024:
                    try:
                        load_credentials(file)
                    except (OSError, UnicodeError):
                        continue
    configure_provider()
    return sorted(k for k in os.environ if k.startswith("AASS_") and k.endswith("API_KEY"))


def select_worker(models):
    explicit = os.environ.get("AASS_WORKER_MODEL")
    if explicit:
        return explicit
    if "qwen3.5:9b" in models:
        return "qwen3.5:9b"
    return next(
        (model for model in models if "qwen" in model.lower()),
        models[0] if models else "qwen3.5:9b",
    )


def verify_ollama():
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=3) as response:
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
        discover_api_keys()
    configure_provider()
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
