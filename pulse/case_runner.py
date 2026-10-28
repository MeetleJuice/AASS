"""One bounded benchmark subprocess; exceptions never serialize free-form text."""

import argparse
import json
import os
import time
from pathlib import Path

from circuit_breaker import CircuitBreaker, SafetyStop
from crdal_supervisor import CRDALSupervisor
from pulse.benchmarks import BROKEN_STORE, setup_project
from pulse.events import EventStream, digest
from sandboxes.container import ContainerSandbox
from telemetry import Trajectory, atomic_json
from worker_agent import WorkerAgent, WorkerProtocolError

COMMAND = ["python", "-m", "unittest", "discover", "-v"]


class FixtureWorker:
    def __init__(self, decisions):
        self.decisions = iter(decisions)

    def step(self, task, context, strategy, budget):
        budget.reserve("fixture", 1)
        choice = next(self.decisions)
        if isinstance(choice, Exception):
            raise choice
        return choice


class FixtureJudge:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def evaluate(self, task, evidence, budget):
        if not self.enabled:
            raise SafetyStop("Independent live review was not enabled")
        return {
            "approved": True,
            "reason": "Deterministic fixture verdict, not live review",
            "issues": [],
        }


def write(path, content):
    return dict(action="write", reason="benchmark fixture", path=path, content=content)


def fixture_case(case_id, workspace, stream):
    task = setup_project(case_id, workspace)
    sandbox = ContainerSandbox(
        workspace, owner_label=digest(workspace.parent.parent.resolve())[:32]
    )
    if case_id in ("data-integrity", "expense-regression"):
        (workspace / "expense_tracker.py").write_text(BROKEN_STORE)
        (workspace / "test_expense_tracker.py").write_text("# deficient generated coverage\n")
        (workspace / "README.md").write_text("Run unittest\n")
        result = sandbox.run(COMMAND)
        stream.emit(
            component="acceptance",
            event_type="tool_finished",
            action="test",
            returncode=result.returncode,
        )
        # Negative control: a deficient app MUST fail independent assertions.
        assert result.returncode != 0 and "FAIL" in result.stderr
        assert "test_malformed_preserved" in result.stderr
        return {
            "status": "passed",
            "evidence": "negative_control_detected",
            "acceptance_passed": False,
            "agent_completed": False,
            "real_tools": True,
            "review": "not_requested",
            "output_hash": digest(result.stdout + result.stderr),
        }
    if case_id == "schema-recovery":
        invalid = {"action": "test", "reason": "fixture"}
        try:
            WorkerAgent.validate(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Missing command accepted")
        decisions = [
            WorkerProtocolError(
                "worker_action_schema",
                details={
                    "action_type": "test",
                    "field": "command",
                    "retry": 1,
                    "schema_version": "v2",
                },
            ),
            write("sample.py", "def add(a,b): return a+b\n"),
            dict(action="finish", reason="verify"),
        ]
    elif case_id == "resume-integrity":
        supervisor = CRDALSupervisor(
            workspace,
            FixtureWorker([write("sample.py", "def add(a,b): return a+b\n")]),
            FixtureJudge(),
            sandbox=sandbox,
            budget=CircuitBreaker(iteration_limit=1),
            observer=stream.emit,
        )
        report = supervisor.run(task)
        assert report["status"] == "stopped"
        events = Trajectory(workspace / ".aass/trajectory.json").events()
        assert events and (workspace / "sample.py").is_file()
        assert json.loads((workspace / ".aass/canvas.json").read_text())["status"] == "stopped"
        return {
            "status": "passed",
            "evidence": "interruption_retained",
            "agent_completed": False,
            "real_tools": False,
            "review": "not_requested",
            "acceptance_passed": False,
        }
    else:
        decisions = []
        if case_id == "existing-repair":
            decisions.append(dict(action="test", command=COMMAND, reason="observe seeded defect"))
        decisions += [write("sample.py", "def add(a,b): return a+b\n")]
        if case_id == "multi-file":
            decisions += [
                write(
                    "test_sample.py",
                    "import unittest\nfrom sample import add\nclass AgentTests(unittest.TestCase):\n def test_sum(self): self.assertEqual(add(2,3),5)\n",
                ),
                write("README.md", "Tests: python -m unittest discover -v\n"),
            ]
        if case_id == "rewrite-loop":
            # Same snapshot returns across alternating files, not three same-path writes.
            decisions += [
                write("notes.py", "VALUE=1\n"),
                write("sample.py", "def add(a,b): return a+b\n"),
                write("notes.py", "VALUE=1\n"),
            ]
        decisions.append(dict(action="finish", reason="request review"))
    supervisor = CRDALSupervisor(
        workspace,
        FixtureWorker(decisions),
        FixtureJudge(),
        sandbox=sandbox,
        observer=stream.emit,
        acceptance_command=COMMAND,
        protected_paths=["test_acceptance.py"],
    )
    report = supervisor.run(task)
    assert report["status"] == "approved", report["status"]
    assert supervisor.tested and supervisor.evidence[-1]["returncode"] == 0
    assert (workspace / "unrelated.txt").read_text() == "preserve me\n"
    if case_id == "existing-repair":
        assert supervisor.evidence[0]["returncode"] != 0
    return {
        "status": "passed",
        "evidence": "fixture_harness",
        "agent_completed": True,
        "real_tools": True,
        "review": "fixture",
        "acceptance_passed": True,
        "reserved_tokens": report["reserved_tokens"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--live-local", action="store_true")
    parser.add_argument("--live-cloud", action="store_true")
    parser.add_argument("--tokens", type=int, default=64000)
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args(argv)
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    workspace = root / "workspace"
    workspace.mkdir(exist_ok=True)
    stream = EventStream(
        root, root.name, callback=lambda event: print("PULSE_CASE " + json.dumps(event), flush=True)
    )
    started = time.monotonic()
    try:
        if args.live_local:
            from initialize_aass import (
                configure_provider,
                discover_api_keys,
                select_worker,
                verify_ollama,
            )
            from orchestration_canvas import make_judge

            discover_api_keys(configure=False)
            models = verify_ollama()
            if not models:
                result = {"status": "blocked", "error_category": "worker_unavailable"}
            else:
                task = setup_project(args.case, workspace)
                worker = WorkerAgent(
                    os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
                    select_worker(models),
                    observer=stream.emit,
                )
                judge = FixtureJudge(enabled=False)
                if args.live_cloud:
                    from settings import provider_preferences

                    service = provider_preferences().get("service", "auto")
                    os.environ["AASS_JUDGE_SERVICE"] = service
                    configure_provider()
                    judge = make_judge()
                budget = CircuitBreaker(token_limit=args.tokens, iteration_limit=args.iterations)
                supervisor = CRDALSupervisor(
                    workspace,
                    worker,
                    judge,
                    sandbox=ContainerSandbox(
                        workspace, owner_label=digest(workspace.parent.parent.resolve())[:32]
                    ),
                    budget=budget,
                    observer=stream.emit,
                    acceptance_command=COMMAND,
                    protected_paths=["test_acceptance.py"],
                )
                report = supervisor.run(task)
                accepted = supervisor.tested
                reason = report.get("reason", "")
                category = (
                    "budget_exhausted"
                    if "kill-switch" in reason
                    else "worker_unavailable"
                    if "Model service" in reason
                    else "review_not_enabled"
                    if not args.live_cloud and accepted
                    else "task_incomplete"
                )
                result = {
                    "status": "passed"
                    if report["status"] == "approved" and accepted
                    else "blocked"
                    if category in {"review_not_enabled", "worker_unavailable"}
                    else "failed",
                    "error_category": category,
                    "agent_completed": report["status"] == "approved",
                    "acceptance_passed": accepted,
                    "evidence": "live",
                    "review": "live" if args.live_cloud else "not_enabled",
                    "reserved_tokens": budget.tokens,
                    "iterations": budget.iterations,
                    "real_tools": bool(supervisor.evidence),
                }
        else:
            result = fixture_case(args.case, workspace, stream)
    except Exception as error:
        # No exception bodies/paths/raw model output are persisted.
        result = {
            "status": "blocked" if isinstance(error, (OSError, SafetyStop)) else "failed",
            "error_category": "tool_unavailable"
            if isinstance(error, OSError)
            else "assertion_failed"
            if isinstance(error, AssertionError)
            else "execution_error",
        }
    result["duration"] = round(time.monotonic() - started, 3)
    atomic_json(root / "result.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
