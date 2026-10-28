from pathlib import Path

import pytest

from circuit_breaker import CircuitBreaker
from crdal_supervisor import CRDALSupervisor
from sandboxes.container import ExecutionResult


class ScriptedWorker:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.strategies = []

    def step(self, task, context, strategy, budget):
        budget.reserve("fixture", 1)
        self.strategies.append(strategy)
        return next(self.actions)


class Judge:
    def __init__(self, approve=True):
        self.calls = []
        self.approve = approve

    def evaluate(self, task, evidence, budget):
        self.calls.append(evidence)
        return {"approved": self.approve, "reason": "test verdict", "issues": []}


class Sandbox:
    def run(self, command):
        return ExecutionResult(0, "", "Ran 1 test in 0.001s\nOK\n")


def action(kind, **kw):
    return {"action": kind, "reason": "test fixture", **kw}


def test_write_test_judge_end_to_end(tmp_path):
    worker = ScriptedWorker(
        [
            action("write", path="hello.py", content="VALUE=42\n"),
            action("test", command=["python", "-m", "unittest"]),
            action("finish"),
        ]
    )
    judge = Judge()
    supervisor = CRDALSupervisor(tmp_path, worker, judge, sandbox=Sandbox())
    assert supervisor.run("Implement VALUE")["status"] == "approved"
    assert (tmp_path / "hello.py").read_text() == "VALUE=42\n"
    assert judge.calls[0]["changes"] == {"hello.py": "VALUE=42\n"}
    assert judge.calls[0]["tests"][0]["returncode"] == 0


def test_write_invalidates_prior_test(tmp_path):
    worker = ScriptedWorker(
        [
            action("test", command=["python", "-m", "unittest"]),
            action("write", path="new.py", content="bad code"),
            action("finish"),
        ]
    )
    judge = Judge()
    supervisor = CRDALSupervisor(
        tmp_path, worker, judge, sandbox=Sandbox(), budget=CircuitBreaker(iteration_limit=3)
    )
    assert supervisor.run("test")["status"] == "stopped"
    assert judge.calls == []


def test_fixation_forces_pivots_then_stops(tmp_path):
    worker = ScriptedWorker([action("read", path="missing.py")] * 15)
    supervisor = CRDALSupervisor(tmp_path, worker, Judge(), sandbox=Sandbox())
    result = supervisor.run("test")
    assert result["status"] == "stopped"
    assert "Fixation" in result["reason"]
    assert len(set(worker.strategies)) == 3


def test_judge_rejection_never_reports_approved(tmp_path):
    worker = ScriptedWorker(
        [action("test", command=["python", "-m", "unittest"])] + [action("finish")] * 4
    )
    supervisor = CRDALSupervisor(
        tmp_path, worker, Judge(False), sandbox=Sandbox(), budget=CircuitBreaker(iteration_limit=4)
    )
    assert supervisor.run("test")["status"] == "stopped"


def test_zero_tests_is_not_success(tmp_path):
    class EmptySandbox:
        def run(self, command):
            return ExecutionResult(0, "", "Ran 0 tests in 0s\nOK")

    worker = ScriptedWorker(
        [action("test", command=["python", "-m", "unittest"]), action("finish")]
    )
    judge = Judge()
    supervisor = CRDALSupervisor(
        tmp_path, worker, judge, sandbox=EmptySandbox(), budget=CircuitBreaker(iteration_limit=2)
    )
    assert supervisor.run("test")["status"] == "stopped"
    assert not judge.calls


def test_runtime_cannot_edit_itself():
    import crdal_supervisor

    with pytest.raises(ValueError, match="separate target"):
        CRDALSupervisor(Path(crdal_supervisor.__file__).parent, ScriptedWorker([]), Judge())


def test_path_violation_stops_immediately(tmp_path):
    worker = ScriptedWorker([action("write", path="../escape", content="no")])
    assert CRDALSupervisor(tmp_path, worker, Judge()).run("test")["status"] == "stopped"
    assert not (tmp_path.parent / "escape").exists()


def test_tool_error_reaches_worker_as_diagnostic_without_persisting_contents(tmp_path):
    class FailingSandbox:
        def run(self, command):
            return ExecutionResult(1, "", "AssertionError: expected 42")

    worker = ScriptedWorker([action("test", command=["python", "-m", "unittest"])])
    supervisor = CRDALSupervisor(
        tmp_path,
        worker,
        Judge(),
        sandbox=FailingSandbox(),
        budget=CircuitBreaker(iteration_limit=1),
    )
    supervisor.run("test")
    assert "AssertionError" not in supervisor.history.path.read_text()
    assert "AssertionError" in supervisor.evidence[0]["stderr"]


def test_variable_test_timings_do_not_defeat_fixation_intercept(tmp_path):
    class VariableTimingSandbox:
        calls = 0

        def run(self, command):
            self.calls += 1
            return ExecutionResult(
                1, "", f"FAIL AssertionError\nRan 1 test in 0.00{self.calls}s\nFAILED"
            )

    worker = ScriptedWorker([action("test", command=["python", "-m", "unittest"])] * 15)
    supervisor = CRDALSupervisor(tmp_path, worker, Judge(), sandbox=VariableTimingSandbox())
    report = supervisor.run("repair failure")
    assert report["status"] == "stopped"
    assert len(set(worker.strategies)) == 3
    assert "Fixation" in report["reason"]


def test_malformed_worker_output_cannot_crash_error_recovery(tmp_path):
    worker = ScriptedWorker([None] * 12)
    result = CRDALSupervisor(tmp_path, worker, Judge()).run("test")
    assert result["status"] == "stopped"


def test_workspace_lock_rejects_second_writer(tmp_path):
    from filelock import FileLock

    from circuit_breaker import SafetyStop

    supervisor = CRDALSupervisor(tmp_path, ScriptedWorker([]), Judge())
    with FileLock(str(supervisor.state_dir / "run.lock")):
        with pytest.raises(SafetyStop, match="Another supervisor"):
            supervisor.run("test")


def test_supervisor_cannot_reuse_prior_task_evidence(tmp_path):
    from circuit_breaker import SafetyStop

    worker = ScriptedWorker(
        [action("test", command=["python", "-m", "unittest"]), action("finish")]
    )
    supervisor = CRDALSupervisor(tmp_path, worker, Judge(), sandbox=Sandbox())
    assert supervisor.run("first task")["status"] == "approved"
    assert supervisor.history.events()[-1]["action"] == "approved"
    with pytest.raises(SafetyStop, match="new supervisor"):
        supervisor.run("a different task")


def test_previous_run_failures_do_not_trigger_early_pivot(tmp_path):
    from telemetry import Trajectory

    history = Trajectory(tmp_path / ".aass/trajectory.json")
    for i in range(3):
        history.append(
            iteration=i,
            files_modified=[],
            error_signature="FileNotFoundError",
            action="read",
            strategy=0,
            run_id="old-task",
        )
    worker = ScriptedWorker([action("read", path="missing.py")])
    supervisor = CRDALSupervisor(
        tmp_path, worker, Judge(), budget=CircuitBreaker(iteration_limit=1)
    )
    assert supervisor.run("new task")["status"] == "stopped"
    assert supervisor.strategy_index == 0


def test_successful_rewrites_interleaved_with_invalid_actions_force_pivot(tmp_path):
    worker = ScriptedWorker(
        [
            action("write", path="calculator.py", content="def add(a,b): return a+b\n"),
            None,
            action("write", path="calculator.py", content="def add(a,b):\n return a+b\n"),
            None,
            action("write", path="calculator.py", content="def add(a,b): return a + b\n"),
            action("write", path="test_calculator.py", content="import unittest\n"),
            action("test", command=["python", "-m", "unittest"]),
            action("finish"),
        ]
    )
    supervisor = CRDALSupervisor(tmp_path, worker, Judge(), sandbox=Sandbox())
    report = supervisor.run("Create calculator and tests")
    assert report["status"] == "approved"
    assert worker.strategies[5] != worker.strategies[0]
    assert supervisor._context("done")["completed_artifacts"][0]["definitions"] == ["add"]


def test_intervening_test_allows_followup_repairs_without_rewrite_pivot(tmp_path):
    worker = ScriptedWorker(
        [
            item
            for _ in range(3)
            for item in (
                action("write", path="calculator.py", content="VALUE=1\n"),
                action("test", command=["python", "-m", "unittest"]),
            )
        ]
        + [action("finish")]
    )
    supervisor = CRDALSupervisor(tmp_path, worker, Judge(), sandbox=Sandbox())
    assert supervisor.run("Repair")["status"] == "approved"
    assert len(set(worker.strategies)) == 1


def test_ready_snapshot_is_verified_before_next_model_call_and_errors_survive_rejection(tmp_path):
    from worker_agent import WorkerProtocolError

    seen = []

    class Worker(ScriptedWorker):
        def step(self, task, context, strategy, budget):
            seen.append(context)
            return super().step(task, context, strategy, budget)

    class FailingSandbox:
        def run(self, command):
            return ExecutionResult(
                1, "", "Ran 1 test in 0.1s\nFAILED (failures=1)\nAssertionError: concrete defect"
            )

    worker = Worker(
        [
            action("write", path="test_app.py", content="import unittest\n"),
            WorkerProtocolError("worker_action_schema"),
            action("map"),
        ]
    )
    # ScriptedWorker normally returns objects; raise the injected protocol error.
    original = worker.step

    def step(*args):
        item = original(*args)
        if isinstance(item, Exception):
            raise item
        return item

    worker.step = step
    supervisor = CRDALSupervisor(
        tmp_path,
        worker,
        Judge(),
        sandbox=FailingSandbox(),
        budget=CircuitBreaker(iteration_limit=4),
    )
    result = supervisor.run("Create and verify")
    assert result["status"] == "stopped"
    assert len(supervisor.evidence) == 1
    assert "AssertionError" in seen[1]["latest_test"]["output_tail"]
    assert "AssertionError" in seen[2]["latest_test"]["output_tail"]


def test_independent_acceptance_cannot_be_replaced_by_worker(tmp_path):
    from circuit_breaker import SafetyStop

    protected = tmp_path / "test_acceptance.py"
    protected.write_text("original")
    supervisor = CRDALSupervisor(
        tmp_path,
        ScriptedWorker([]),
        Judge(),
        sandbox=Sandbox(),
        protected_paths=["test_acceptance.py"],
    )
    with pytest.raises(SafetyStop):
        supervisor.execute(action("write", path="test_acceptance.py", content="pass"))
    assert protected.read_text() == "original"


def test_identical_rewrite_still_requires_fresh_verification(tmp_path):
    worker = ScriptedWorker(
        [
            action("write", path="test_app.py", content="import unittest\n"),
            action("write", path="test_app.py", content="import unittest\n"),
            action("finish"),
        ]
    )
    supervisor = CRDALSupervisor(tmp_path, worker, Judge(), sandbox=Sandbox())
    assert supervisor.run("Verify")["status"] == "approved"
    assert len(supervisor.evidence) == 2


def test_productive_same_file_edits_do_not_count_as_fixation(tmp_path):
    worker = ScriptedWorker(
        [
            action("write", path="sample.py", content="A=1\n"),
            action("write", path="sample.py", content="A=1\nB=2\n"),
            action("write", path="sample.py", content="A=1\nB=2\nC=3\n"),
            action("test", command=["python", "-m", "unittest"]),
            action("finish"),
        ]
    )
    supervisor = CRDALSupervisor(tmp_path, worker, Judge(), sandbox=Sandbox())
    assert supervisor.run("Build")["status"] == "approved"
    assert len(set(worker.strategies)) == 1


def test_unchanged_failure_after_ineffective_repair_forces_pivot(tmp_path):
    class FailingSandbox:
        def run(self, command):
            return ExecutionResult(1, "", "Ran 1 test\nFAILED (failures=1)\n")

    worker = ScriptedWorker(
        [
            action("write", path="test_app.py", content="import unittest\n"),
            action("write", path="test_app.py", content="import unittest\n# cosmetic repair\n"),
            action("map"),
        ]
    )
    supervisor = CRDALSupervisor(
        tmp_path,
        worker,
        Judge(),
        sandbox=FailingSandbox(),
        budget=CircuitBreaker(iteration_limit=5),
    )
    assert supervisor.run("Repair")["status"] == "stopped"
    assert len(supervisor.evidence) == 2
    assert supervisor.strategy_index == 1
