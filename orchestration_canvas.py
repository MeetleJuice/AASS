"""Headless AASS executive canvas and native CLI."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

from circuit_breaker import CircuitBreaker
from crdal_supervisor import CRDALSupervisor
from initialize_aass import (
    bootstrap_workspace,
    configure_provider,
    discover_api_keys,
    load_credentials,
    select_worker,
    verify_ollama,
)
from judge_evaluator import JudgeEvaluator
from sandboxes.container import DEFAULT_SANDBOX_IMAGE
from worker_agent import WorkerAgent


def doctor():
    checks = {}
    models = verify_ollama()
    worker_model = select_worker(models)
    checks["ollama_worker"] = {
        "ready": worker_model in models,
        "model": worker_model,
        "available_models": models,
    }
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        checks["docker"] = {
            "ready": result.returncode == 0,
            "version": result.stdout.strip() if result.returncode == 0 else None,
        }
    except (OSError, subprocess.TimeoutExpired):
        checks["docker"] = {"ready": False}
    image = os.environ.get("AASS_SANDBOX_IMAGE", DEFAULT_SANDBOX_IMAGE)
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, timeout=10
        )
        checks["sandbox_image"] = {"ready": result.returncode == 0, "image": image}
    except (OSError, subprocess.TimeoutExpired):
        checks["sandbox_image"] = {"ready": False, "image": image}
    checks["judge_configuration"] = {
        "ready": bool(os.environ.get("AASS_JUDGE_API_KEY") and os.environ.get("AASS_JUDGE_MODEL")),
        "note": "Presence only; run verify-live for an authenticated model request.",
    }
    try:
        from playwright.sync_api import sync_playwright

        from tools.computer_use import chromium_executable

        with sync_playwright() as p:
            with p.chromium.launch(headless=True, executable_path=chromium_executable()) as browser:
                page = browser.new_page()
                page.set_content("<title>AASS readiness</title>")
                checks["chromium"] = {"ready": page.title() == "AASS readiness"}
    except Exception as error:
        checks["chromium"] = {"ready": False, "error_type": type(error).__name__}
    return {"ready": all(c["ready"] for c in checks.values()), "checks": checks}


def make_judge():
    return JudgeEvaluator(
        os.environ.get("AASS_JUDGE_API_KEY"),
        os.environ.get("AASS_JUDGE_MODEL"),
        os.environ.get("AASS_JUDGE_BASE_URL", "https://api.openai.com/v1"),
        provider=os.environ.get("AASS_JUDGE_PROVIDER", "openai"),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--credentials-file", type=Path, help="Import runtime credentials only into this process"
    )
    parser.add_argument("--no-desktop-discovery", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("verify-live")
    init = commands.add_parser("init")
    init.add_argument("--root", type=Path, default=Path.cwd())
    run = commands.add_parser("run")
    run.add_argument("--workspace", type=Path, required=True)
    run.add_argument("--task", required=True)
    run.add_argument("--browser-origin", action="append", default=[])
    run.add_argument("--mcp-config", type=Path, help="Operator-owned JSON server configuration")
    run.add_argument("--tokens", type=int, default=64000)
    run.add_argument("--iterations", type=int, default=20)
    status = commands.add_parser("status")
    status.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.credentials_file:
        load_credentials(args.credentials_file)
    if not args.no_desktop_discovery:
        discover_api_keys()
    configure_provider()
    try:
        if args.command == "doctor":
            report = doctor()
            print(json.dumps(report, indent=2))
            return 0 if report["ready"] else 2
        if args.command == "init":
            bootstrap_workspace(args.root, verify_ollama())
            print("Architecture specification generated; trajectory preserved.")
            return 0
        if args.command == "status":
            print((args.workspace / ".aass/canvas.json").read_text())
            return 0
        if args.command == "verify-live":
            budget = CircuitBreaker()
            worker = WorkerAgent(
                os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
                select_worker(verify_ollama()),
            )
            action = worker.step(
                "Return a map action to inspect the repository.",
                {},
                "Protocol readiness check",
                budget,
            )
            verdict = make_judge().evaluate(
                "Validate worker returned a map action", {"worker_action": action}, budget
            )
            print(json.dumps({"worker_action": action["action"], "judge": verdict}, indent=2))
            return 0 if action["action"] == "map" and verdict["approved"] else 2
        from sandboxes.container import ContainerSandbox
        from tools.operator_tools import OperatorTools

        budget = CircuitBreaker(args.tokens, args.iterations)
        operator_tools = OperatorTools(
            browser_origins=args.browser_origin,
            mcp_config=json.loads(args.mcp_config.read_text()) if args.mcp_config else None,
        )
        worker = WorkerAgent(
            os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
            select_worker(verify_ollama()),
        )
        supervisor = CRDALSupervisor(
            args.workspace,
            worker,
            make_judge(),
            budget=budget,
            tools=operator_tools,
            sandbox=ContainerSandbox(
                args.workspace, os.environ.get("AASS_SANDBOX_IMAGE", DEFAULT_SANDBOX_IMAGE)
            ),
        )
        report = supervisor.run(args.task)
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "approved" else 2
    except (ValueError, OSError, httpx.HTTPError, RuntimeError) as error:
        # No exception bodies: upstream responses can contain keys or task contents.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "hint": "Check configuration with aass doctor and docs/OPERATIONS.md",
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
