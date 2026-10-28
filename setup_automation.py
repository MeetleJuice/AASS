"""Bounded same-provider first-run checks; no billing without explicit consent."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from provider_registry import CONFIG_NAMES, providers
from settings import SECRET_NAMES, is_link, provider_preferences, save_provider_preferences
from telemetry import atomic_json


def fingerprint():
    names = (
        SECRET_NAMES
        | (CONFIG_NAMES - {"AASS_SETUP_ALLOW_BILLABLE_CHECK"})
        | {"OLLAMA_HOST", "AASS_WORKER_MODEL", "AASS_JUDGE_BASE_URL", "AASS_JUDGE_PROVIDER"}
    )
    names |= {key for row in providers().values() for key in row["keys"]}
    values = {name: os.environ[name] for name in sorted(names) if os.environ.get(name)}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def saved_result(root):
    path = Path(root) / ".aass/automatic-setup.json"
    if is_link(path) or not path.is_file() or path.stat().st_size > 16384:
        return None
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        prefs = provider_preferences(root)
        if (
            isinstance(result, dict)
            and result.get("fingerprint") == fingerprint()
            and result.get("service") == prefs.get("service")
            and result.get("model") == prefs.get("model")
        ):
            safe = {
                k: result[k]
                for k in ("status", "service", "model", "message", "last_failure")
                if k in result
            }
            if safe.get("status") == "ready" and not local_services_ready():
                return {
                    **safe,
                    "status": "needs_action",
                    "message": "Start Docker Desktop and Ollama, then Refresh detection. Your verified cloud settings are retained.",
                }
            return safe
    except (OSError, ValueError):
        pass
    return None


def local_services_ready():
    from initialize_aass import select_worker, verify_ollama
    from settings import subprocess_environment

    models = verify_ollama()
    if select_worker(models) not in models:
        return False
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=5,
            check=False,
            env=subprocess_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def run(root):
    import setup_api as api
    from setup_wizard import preferred_model

    root = Path(root)
    if os.environ.get("AASS_SETUP_ALLOW_BILLABLE_CHECK") != "1":
        return {
            "status": "needs_action",
            "code": "consent_required",
            "message": "Automatic cloud validation awaits authorization. Click Test connections to authorize API use, or set AASS_SETUP_ALLOW_BILLABLE_CHECK=1 in your private file.",
        }
    previous = saved_result(root)
    if previous:
        return previous
    available = [service for service in api.PROVIDERS if api.provider_key(service)[0]]
    prefs = provider_preferences(root)
    chosen = prefs.get("service") or os.environ.get("AASS_JUDGE_SERVICE")
    service = chosen if chosen in available else None
    if service is None and len(available) == 1:
        service = available[0]
    if service is None:
        return {
            "status": "needs_action",
            "message": "Choose a configured provider. Automatic setup never switches between providers.",
        }
    if not local_services_ready():
        return {
            "status": "needs_action",
            "message": "Start Docker Desktop and Ollama, then retry Prepare / check. Cloud validation has not started.",
        }
    model = prefs.get("model", "")
    result = {"status": "needs_action", "service": service, "model": model}
    # Persist consent consumption before any model call. An interrupted child
    # must not silently repeat paid requests on the next application launch.
    save_provider_preferences(service, model, root)
    pending = {
        **result,
        "message": "Automatic verification was interrupted. Use Test connections to retry explicitly.",
        "fingerprint": fingerprint(),
    }
    atomic_json(root / ".aass/automatic-setup.json", pending)
    stage = "verify-worker"
    try:
        api.verify_worker_report()
        stage = "models"
        models = api.models_report(service)["models"]
        ids = [m["id"] for m in models]
        first = preferred_model(models, model)
        candidates = list(dict.fromkeys([first, *sorted(ids)]))[:3]
        stage = "verify-judge"
        for attempt, candidate in enumerate(candidates, 1):
            atomic_json(root / ".aass/automatic-setup.json", {**pending, "attempts": attempt})
            model = candidate
            try:
                api.verify_judge_report(service, candidate)
                result.update(
                    status="ready",
                    model=candidate,
                    message="Ready to run tasks. Local worker and independent judge verified.",
                )
                break
            except Exception as error:
                safe = api._error_report(error, "verify-judge")
                result["last_failure"] = {k: safe.get(k) for k in ("stage", "code", "http_status")}
                # Authentication, quota, transport and unknown errors stop here.
                if safe.get("http_status") not in (400, 404) or safe.get("provider_code") in {
                    "API_KEY_INVALID",
                    "BILLING_DISABLED",
                    "SERVICE_DISABLED",
                }:
                    result.update(
                        message=safe.get(
                            "hint",
                            "Check the selected provider account, then retry Test connections.",
                        )
                    )
                    break
        else:
            result["message"] = (
                "No compatible model passed within three checks. Choose another listed model and Test connections."
            )
    except Exception as error:
        safe = api._error_report(error, stage)
        result["last_failure"] = {k: safe.get(k) for k in ("stage", "code", "http_status")}
        result["message"] = safe.get(
            "hint", "Check local services and provider access, then retry."
        )
    result.setdefault(
        "message",
        "Setup needs user action. Check the selected provider and retry Test connections.",
    )
    result["model"] = result.get("model") or model
    if result["model"]:
        save_provider_preferences(service, result["model"], root)
    atomic_json(root / ".aass/automatic-setup.json", {**result, "fingerprint": fingerprint()})
    return result
