"""JSON-only setup probes. Credentials stay in this short-lived backend process."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import settings
from circuit_breaker import CircuitBreaker
from initialize_aass import discover_api_keys, select_worker, verify_ollama
from judge_evaluator import JudgeEvaluator
from orchestration_canvas import failure_report
from tools.model_catalog import MODEL_ID, CatalogError, fetch_models
from worker_agent import WorkerAgent

PROVIDERS = {
    "gemini": {
        "label": "Google Gemini",
        "keys": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "url": "https://generativelanguage.googleapis.com/v1beta",
        "adapter": "gemini",
    },
    "openai": {
        "label": "OpenAI",
        "keys": ("OPENAI_API_KEY",),
        "url": "https://api.openai.com/v1",
        "adapter": "openai",
    },
    "anthropic": {
        "label": "Anthropic",
        "keys": ("ANTHROPIC_API_KEY",),
        "url": "https://api.anthropic.com/v1",
        "adapter": "anthropic",
    },
}


class SetupError(RuntimeError):
    def __init__(self, code, message, hint):
        self.code, self.message, self.hint = code, message, hint
        super().__init__(message)


def _provider(service):
    if service not in PROVIDERS:
        raise SetupError(
            "unsupported_provider",
            "Choose a supported cloud provider.",
            "Select Google Gemini, OpenAI or Anthropic in the setup window.",
        )
    return PROVIDERS[service]


def provider_key(service):
    """A generic key is eligible only when its configured official host matches."""
    provider = _provider(service)
    for binding in provider["keys"]:
        if os.environ.get(binding):
            return os.environ[binding], binding
    generic = os.environ.get("AASS_JUDGE_API_KEY")
    if generic:
        try:
            configured = settings.judge_url(
                os.environ.get("AASS_JUDGE_BASE_URL", ""), provider["adapter"]
            )
            if urlsplit(configured).hostname == urlsplit(provider["url"]).hostname:
                return generic, "AASS_JUDGE_API_KEY"
        except ValueError:
            pass
    return None, None


def _ok(operation, **payload):
    return {"status": "ok", "operation": operation, **payload}


def credentials_report():
    discover_api_keys(configure=False)
    root = Path(__file__).resolve().parent
    selection_reader = getattr(settings, "selected_credentials_file", None)
    selected = selection_reader() if selection_reader else None
    candidates = [root / ".env", root / ".env.txt"]
    candidates.extend(
        desktop / name
        for desktop in (Path.home() / "Desktop", Path.home() / "OneDrive/Desktop")
        for name in (".env", ".env.txt")
    )
    providers = []
    for service, provider in PROVIDERS.items():
        key, binding = provider_key(service)
        providers.append(
            {
                "id": service,
                "label": provider["label"],
                "key_present": bool(key),
                "source_binding": binding,
            }
        )
    warning = None
    try:
        preferences = settings.provider_preferences()
    except (OSError, ValueError):
        preferences = {}
        warning = "Saved provider settings need repair. Choose your provider and model again."
    return _ok(
        "credentials",
        providers=providers,
        selected_file=str(selected) if selected else None,
        selection_present=bool(selected and Path(selected).is_file()),
        automatic_file_candidates=[
            str(path) for path in candidates if path.is_file() and not settings.is_link(path)
        ],
        preferences=preferences,
        settings_warning=warning,
    )


def _require_key(service):
    key, _ = provider_key(service)
    if not key:
        raise SetupError(
            "missing_key",
            "No matching API key was found for this provider.",
            "Choose your private .env or .txt credentials file, then select its provider. "
            "A generic AASS_JUDGE_API_KEY also needs the matching official AASS_JUDGE_BASE_URL.",
        )
    return key


def models_report(service):
    discover_api_keys(configure=False)
    key = _require_key(service)
    models = fetch_models(service, key)
    if not models:
        raise SetupError(
            "no_text_models",
            "The provider returned no supported text models.",
            "Check that this key has text-generation API access in the provider console.",
        )
    return _ok("models", service=service, models=models, catalog_only=True)


def verify_worker_report():
    discover_api_keys(configure=False)
    models = verify_ollama()
    model = select_worker(models)
    if model not in models:
        raise SetupError(
            "worker_model_missing",
            "The selected local worker model is not available in Ollama.",
            "Open Ollama and use Prepare local tools in the setup window to finish its model download.",
        )
    worker = WorkerAgent(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"), model)
    action = worker.step(
        "Return a map action to inspect the repository.",
        {},
        "Protocol readiness check",
        CircuitBreaker(),
    )
    if action.get("action") != "map":
        raise SetupError(
            "worker_protocol_failed",
            "Ollama responded, but its model did not produce the required action.",
            "Retry the local check. If it repeats, choose the recommended qwen3.5:9b worker model.",
        )
    return _ok("verify-worker", model=model, worker_action="map")


def verify_judge_report(service, model):
    discover_api_keys(configure=False)
    provider = _provider(service)
    key = _require_key(service)
    if not isinstance(model, str) or not MODEL_ID.fullmatch(model) or key in model:
        raise SetupError(
            "invalid_model",
            "Select a model from the provider's model list.",
            "Load available models and choose a text model before testing the connection.",
        )
    judge = JudgeEvaluator(key, model, provider["url"], provider["adapter"])
    verdict = judge.evaluate(
        "Validate that the provided worker action is a map action.",
        {"worker_action": {"action": "map", "reason": "Protocol readiness check"}},
        CircuitBreaker(),
    )
    if not verdict["approved"] or verdict["issues"]:
        raise SetupError(
            "judge_protocol_failed",
            "The cloud model responded, but did not approve the valid protocol sample.",
            "Retry this cloud check or select a different text model. Local installation is complete.",
        )
    return _ok("verify-judge", service=service, model=model, approved=True)


def _error_report(error, operation):
    stage = {"verify-worker": "ollama_worker", "verify-judge": "cloud_judge"}.get(
        operation, operation
    )
    if isinstance(error, SetupError):
        return {
            "status": "error",
            "stage": stage,
            "code": error.code,
            "message": error.message,
            "hint": error.hint,
        }
    if isinstance(error, CatalogError):
        report = error.as_dict()
        report.update(
            status="error", stage="model_catalog", message="Could not load available models."
        )
        return report
    report = failure_report(error, stage)
    report.update(status="error", code="probe_failed", message="This setup check did not pass.")
    if operation == "verify-worker":
        report["message"] = "The local Ollama worker check did not pass."
    elif operation == "verify-judge":
        report["message"] = "The selected cloud model check did not pass."
        if report.get("http_status") == 404:
            report["hint"] = (
                "This model or endpoint is unavailable for this key. Reload available models and "
                "select a listed text model, then retry the cloud check. Do not reinstall AASS."
            )
    elif isinstance(error, (OSError, ValueError, UnicodeError)):
        report["code"] = "credentials_configuration"
        report["message"] = "The private credentials file or saved setup settings need attention."
        report["hint"] = (
            "Choose your credentials file again. Use a regular .env or .txt file containing "
            "KEY=value lines; do not paste keys into the setup window."
        )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("credentials")
    models = commands.add_parser("models")
    models.add_argument("--service", required=True, choices=PROVIDERS)
    commands.add_parser("verify-worker")
    judge = commands.add_parser("verify-judge")
    judge.add_argument("--service", required=True, choices=PROVIDERS)
    judge.add_argument("--model", required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "credentials":
            report = credentials_report()
        elif args.operation == "models":
            report = models_report(args.service)
        elif args.operation == "verify-worker":
            report = verify_worker_report()
        else:
            report = verify_judge_report(args.service, args.model)
    except Exception as error:
        report = _error_report(error, args.operation)
        if args.operation == "verify-judge":
            # Construct context from validated selections, never error bodies/URLs.
            model = args.model
            secrets = [os.environ[name] for name in settings.SECRET_NAMES if os.environ.get(name)]
            if MODEL_ID.fullmatch(model) and not any(value in model for value in secrets):
                report.update(
                    service=args.service,
                    model=model,
                    api_host=urlsplit(PROVIDERS[args.service]["url"]).hostname,
                )
                report["api_route"] = (
                    "generateContent"
                    if args.service == "gemini"
                    else "messages"
                    if args.service == "anthropic"
                    else "chat/completions"
                )
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
