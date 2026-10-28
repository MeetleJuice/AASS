"""Bounded dual-loop supervisor. Runtime control code lives outside the target workspace."""

import ast
import hashlib
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from filelock import FileLock, Timeout

from circuit_breaker import CircuitBreaker, SafetyStop
from sandboxes.container import ContainerSandbox
from settings import is_link
from stall_detector import check_fixation
from telemetry import Trajectory, atomic_json
from tools.operator_tools import OperatorTools
from tools.repo_mapper import RepoMapper
from worker_agent import WorkerAgent, WorkerProtocolError

MAX_FILE_BYTES = 64 * 1024
MAX_CONTEXT_BYTES = 12 * 1024

STRATEGIES = (
    "Implement the smallest change and verify the relevant behavior.",
    "Pivot: inspect interfaces and root assumptions; use a different implementation approach.",
    "Pivot: reduce to a minimal reproduction and repair the failing dependency or contract.",
)
FORBIDDEN_PARTS = frozenset(
    {
        ".git",
        ".aass",
        ".venv",
        "__pycache__",
        "node_modules",
        "generated",
        ".aws",
        ".ssh",
        ".codex",
        ".agents",
    }
)
PROTECTED_NAMES = frozenset({"trajectory.json", "architecture_spec.json"})


def workspace_path(root, name):
    relative = Path(name)
    if not name or relative.is_absolute() or ".." in relative.parts:
        raise SafetyStop("Only relative workspace paths are permitted")
    if any(part.startswith(".") or part in FORBIDDEN_PARTS for part in relative.parts):
        raise SafetyStop("Hidden or runtime paths are not available to the worker")
    if (
        relative.name in PROTECTED_NAMES
        or relative.suffix.lower() in (".key", ".pem", ".env")
        or any(
            term in part.lower()
            for part in relative.parts
            for term in ("credential", "secret", "token")
        )
    ):
        raise SafetyStop("Credential or control file access denied")
    # Reject symlinks even when the target is inside the workspace.
    current = root
    for part in relative.parts:
        current = current / part
        if is_link(current):
            raise SafetyStop("Symlink access denied")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root):
        raise SafetyStop("Path escapes workspace")
    return resolved


class CRDALSupervisor:
    def __init__(
        self,
        workspace,
        worker,
        judge,
        *,
        sandbox=None,
        budget=None,
        tools=None,
        progress=None,
        observer=None,
        acceptance_command=None,
        protected_paths=(),
    ):
        self.root = Path(workspace).resolve(strict=True)
        runtime = Path(__file__).resolve().parent
        if self.root == runtime or runtime.is_relative_to(self.root):
            raise ValueError("Use a separate target checkout, not the AASS runtime checkout")
        self.worker, self.judge = worker, judge
        self.progress = progress
        self.observer = observer
        self.acceptance_command = acceptance_command
        self.protected_paths = frozenset(
            workspace_path(self.root, name) for name in protected_paths
        )
        self._last_test_snapshot = None
        self._first_test = True
        self._started = time.monotonic()
        self._snapshots = {}
        self._failed_snapshots = set()
        self.tools = tools or OperatorTools()
        self.sandbox = sandbox or ContainerSandbox(self.root)
        self.budget = budget or CircuitBreaker()
        self.state_dir = self.root / ".aass"
        if is_link(self.state_dir):
            raise SafetyStop("Runtime state directory cannot be a symlink")
        self.state_dir.mkdir(exist_ok=True, mode=0o700)
        for name in ("trajectory.json", "canvas.json", "run.lock"):
            if is_link(self.state_dir / name):
                raise SafetyStop("Runtime state files cannot be symlinks")
        self.history = Trajectory(self.state_dir / "trajectory.json")
        self.canvas = self.state_dir / "canvas.json"
        self.changed = {}
        self.tested = False
        self.evidence = []
        self.strategy_index = 0
        self.run_id = uuid.uuid4().hex
        self._has_run = False
        self._last_write_path = None
        self._write_streak = 0
        self._untested_writes = 0
        self._known_tests = set()
        self._validation_feedback = None

    def save_state(self, status, **extra):
        state = {
            "status": status,
            "run_id": self.run_id,
            "iterations": self.budget.iterations,
            "reserved_tokens": self.budget.tokens,
            "strategy": STRATEGIES[self.strategy_index],
            "changed_files": sorted(self.changed),
            **extra,
        }
        atomic_json(self.canvas, state)
        return state

    def emit(self, event_type, **data):
        if self.observer:
            self.observer(
                component="supervisor",
                event_type=event_type,
                step=self.budget.iterations,
                reserved_tokens=self.budget.tokens,
                remaining_tokens=self.budget.token_limit - self.budget.tokens,
                **data,
            )

    def _snapshot_hash(self):
        # In-memory contents already passed workspace security checks.
        return hashlib.sha256(repr(sorted(self.changed.items())).encode()).hexdigest()

    def _progress_hash(self):
        meaningful = []
        for name, content in sorted(self.changed.items()):
            try:
                value = (
                    ast.dump(ast.parse(content), include_attributes=False)
                    if name.endswith(".py")
                    else content
                )
            except SyntaxError:
                value = content
            meaningful.append((name, value))
        return hashlib.sha256(repr(meaningful).encode()).hexdigest()

    def _checkpoint(self):
        snapshot = self._snapshot_hash()
        # Runnable unittest sources + implementation changes are readiness evidence.
        # Never infer readiness from an arbitrary number of writes.
        runnable = any(
            name.endswith(".py") and Path(name).name.startswith("test")
            for name in set(self.changed) | self._known_tests
        )
        return (
            bool(self.changed)
            and (runnable or self.acceptance_command)
            and (snapshot != self._last_test_snapshot or self._untested_writes > 0)
        )

    def _artifacts(self):
        summaries = []
        for name, content in list(self.changed.items())[-8:]:
            entry = {"path": name, "bytes": len(content.encode())}
            if name.endswith(".py"):
                try:
                    tree = ast.parse(content)
                    entry["definitions"] = [
                        node.name
                        for node in ast.walk(tree)
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    ][:20]
                except SyntaxError:
                    entry["syntax"] = "needs repair"
            summaries.append(entry)
        return summaries

    def _context(self, observation):
        # Do not charge the same test traceback twice in fresh-context prompts.
        if self.evidence and observation is self.evidence[-1]:
            observation = "Test completed. Inspect latest_test for its command, status and bounded failure output."
        return {
            "observation": str(observation)[-MAX_CONTEXT_BYTES:],
            "changed_files": sorted(self.changed),
            "completed_artifacts": self._artifacts(),
            "verified_since_write": self.tested,
            "validation_feedback": self._validation_feedback,
            "latest_test": {
                "command": self.evidence[-1]["command"],
                "returncode": self.evidence[-1]["returncode"],
                "output_tail": (self.evidence[-1]["stdout"] + self.evidence[-1]["stderr"])[-3000:],
                "current_files_verified": self.tested,
            }
            if self.evidence
            else None,
            "recent_events": [e for e in self.history.events() if e.get("run_id") == self.run_id][
                -3:
            ],
            "capabilities": self.tools.describe(),
            "image_base64": self.tools.consume_image(),
        }

    def execute(self, action):
        kind = action["action"]
        if kind == "mcp":
            return self.tools.mcp_action(action["tool"], action["arguments"])
        if kind == "browser":
            return self.tools.browser_action(action, self.state_dir)
        if kind == "map":
            return RepoMapper(self.root).map()
        if kind in ("read", "write"):
            path = workspace_path(self.root, action["path"])
            if kind == "read":
                if not path.exists():
                    raise FileNotFoundError("Workspace file not found")
                if not path.is_file() or path.stat().st_nlink > 1:
                    raise SafetyStop("Reads require a regular file with no hard links")
                with path.open("rb") as handle:
                    content = handle.read(MAX_FILE_BYTES + 1)
                if len(content) > MAX_FILE_BYTES:
                    raise SafetyStop("File exceeds read limit")
                if path.name.startswith("test") and path.suffix == ".py":
                    self._known_tests.add(action["path"])
                return content.decode("utf-8")
            if path in self.protected_paths:
                raise SafetyStop("Independent acceptance files are read-only")
            content = action["content"]
            if len(content.encode()) > MAX_FILE_BYTES:
                raise SafetyStop("Write exceeds file limit")
            if len(self.changed) >= 100 and action["path"] not in self.changed:
                raise SafetyStop("Changed-file count exceeds run limit")
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and not path.is_file():
                raise SafetyStop("Writes require a regular file")
            # Replacement breaks hard links and preserves the previous file on write failure.
            descriptor, temporary = tempfile.mkstemp(prefix=".aass-write-", dir=path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self.changed[action["path"]] = content
            self.tested = False
            self._write_streak = 0
            self._last_write_path = action["path"]
            self._untested_writes += 1
            snapshot = self._snapshot_hash()
            progress_hash = self._progress_hash()
            repeated = progress_hash in self._snapshots
            self._snapshots[progress_hash] = self._snapshots.get(progress_hash, 0) + 1
            self.emit(
                "file_written",
                artifact_hash=hashlib.sha256(content.encode()).hexdigest(),
                snapshot_hash=snapshot,
                writes_without_test=self._untested_writes,
                repeated_content=repeated,
            )
            if repeated and not self.tested:
                self._write_streak = max(self._write_streak, 3)
            return {
                "written": action["path"],
                "next": "Preserve this implementation. Create remaining requested artifacts, then run unittest. A fresh passing test is required.",
            }
        if kind == "test":
            if self.acceptance_command and action["command"] != self.acceptance_command:
                raise ValueError("Benchmark tests must include independent acceptance")
            self._write_streak = 0
            self._untested_writes = 0
            self._last_test_snapshot = self._snapshot_hash()
            self._snapshots.clear()
            if self._first_test:
                self.emit(
                    "first_test",
                    first_test_seconds=time.monotonic() - self._started,
                    budget_before_test=self.budget.tokens,
                )
                self._first_test = False
            started = time.monotonic()
            self.emit("tool_started", action="test")
            result = self.sandbox.run(action["command"])
            self.emit(
                "tool_finished",
                action="test",
                duration=time.monotonic() - started,
                returncode=result.returncode,
            )
            output = result.stdout + result.stderr
            executed_tests = bool(
                re.search(r"Ran [1-9]\d* tests?", output)
                or re.search(r"\b[1-9]\d* passed\b", output)
            )
            self.tested = (
                result.returncode == 0
                and not result.timed_out
                and not result.output_limited
                and executed_tests
            )
            evidence = {
                "command": action["command"],
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            self.evidence.append(evidence)
            if not self.tested:
                # Only a stable signature reaches persistent logs; raw output stays in memory.
                normalized = re.sub(r"\b\d+(?:\.\d+)?(?:ms|s| seconds?)\b", "<duration>", output)
                normalized = re.sub(r"0x[0-9a-fA-F]+", "<address>", normalized)
                digest = hashlib.sha256(normalized.encode()).hexdigest()[:16]
                failed_state = (self._progress_hash(), digest)
                if failed_state in self._failed_snapshots:
                    self._write_streak = 3
                self._failed_snapshots.add(failed_state)
                raise RuntimeError(f"test:{result.returncode}:{digest}")
            self._failed_snapshots.clear()
            return evidence
        raise ValueError("Unknown executable action")

    def run(self, task):
        if self._has_run:
            raise SafetyStop("Create a new supervisor for each task")
        if not isinstance(task, str) or not task.strip() or len(task.encode()) > 8192:
            raise ValueError("Task must be nonempty and no larger than 8 KiB")
        # A workspace has one writer; losing lock is a visible error, never queued work.
        try:
            with FileLock(str(self.state_dir / "run.lock"), timeout=0):
                try:
                    self._has_run = True
                    return self._run(task)
                finally:
                    self.tools.close()
        except Timeout:
            raise SafetyStop("Another supervisor owns this workspace") from None

    def _run(self, task):
        if self.observer is None:
            from pulse.events import EventStream

            self.observer = EventStream(
                self.state_dir / ("events-" + self.run_id), self.run_id
            ).emit
        if isinstance(self.worker, WorkerAgent) and self.worker.observer is None:
            self.worker.observer = self.observer
        if hasattr(self.judge, "observer") and self.judge.observer is None:
            self.judge.observer = self.observer
        observation = "Start by mapping or reading the target repository."
        self.save_state("running")
        try:
            while True:
                self.budget.tick()
                action = {"action": "model"}
                try:
                    if self._checkpoint():
                        # Run through the same sandbox, evidence and failure path as
                        # worker-selected tests. No model call or approval shortcut.
                        self.emit("verification_checkpoint", automatic=True)
                        proposed = {
                            "action": "test",
                            "reason": "Runnable tests and changed source require verification",
                            "command": self.acceptance_command
                            or (
                                self.evidence[-1]["command"]
                                if self.evidence
                                else ["python", "-m", "unittest", "discover", "-v"]
                            ),
                        }
                    elif self.tested and self.budget.token_limit - self.budget.tokens < (
                        self.judge.required_tokens(
                            task, {"changes": self.changed, "tests": self.evidence[-3:]}
                        )
                        + 8192
                        if hasattr(self.judge, "required_tokens")
                        else 12288
                    ):
                        self.emit("review_budget_checkpoint", automatic=True)
                        proposed = {
                            "action": "finish",
                            "reason": "Reserve remaining budget for independent review",
                        }
                    else:
                        proposed = self.worker.step(
                            task,
                            self._context(observation),
                            STRATEGIES[self.strategy_index],
                            self.budget,
                        )
                    WorkerAgent.validate(proposed)
                    self._validation_feedback = None
                    action = proposed
                    if action["action"] == "finish":
                        if not self.tested:
                            raise ValueError(
                                "Cannot finish without a passing test since the last write"
                            )
                        self.emit("review_requested")
                        verdict = self.judge.evaluate(
                            task,
                            {"changes": self.changed, "tests": self.evidence[-3:]},
                            self.budget,
                        )
                        self.emit(
                            "review_returned",
                            outcome="approved" if verdict["approved"] else "rejected",
                        )
                        if verdict["approved"]:
                            self.history.append(
                                iteration=self.budget.iterations,
                                files_modified=sorted(self.changed),
                                error_signature="SUCCESS",
                                action="approved",
                                strategy=self.strategy_index,
                                run_id=self.run_id,
                            )
                            self.emit("task_finished", outcome="approved")
                            return self.save_state("approved", review=verdict)
                        observation = {"judge_rejected": verdict}
                        signature = "JUDGE_REJECTED"
                    else:
                        started = time.monotonic()
                        self.emit("action_started", action=action["action"])
                        try:
                            observation = self.execute(action)
                        finally:
                            self.emit(
                                "action_returned",
                                action=action["action"],
                                duration=time.monotonic() - started,
                            )
                        signature = "SUCCESS"
                except SafetyStop:
                    raise
                except httpx.TransportError:
                    raise SafetyStop("Model service unavailable; check aass doctor") from None
                except httpx.HTTPStatusError as error:
                    raise SafetyStop(
                        f"Model service returned HTTP {error.response.status_code}"
                    ) from None
                except Exception as error:
                    # Keep actual tool output for the worker; never persist credentials/error bodies.
                    if action.get("action") == "test" and self.evidence:
                        observation = self.evidence[-1]
                    else:
                        observation = {
                            "error_type": type(error).__name__,
                            "guidance": "Check action schema, file paths, and service readiness.",
                        }
                    if isinstance(error, WorkerProtocolError):
                        observation = {
                            "error_code": error.code,
                            "validation": error.details,
                            "guidance": 'Return one JSON action matching its schema. Test example: {"action":"test","reason":"verify","command":["python","-m","unittest","discover","-v"]}. For write supply path and content for ONE file. Inspect latest_test; repair concrete failures instead of regenerating all files.',
                        }
                    if isinstance(error, WorkerProtocolError):
                        self._validation_feedback = error.details
                        self.emit("corrective_feedback", feedback_delivered=False, **error.details)
                    signature = (
                        error.code
                        if isinstance(error, WorkerProtocolError)
                        else str(error)
                        if isinstance(error, RuntimeError) and str(error).startswith("test:")
                        else type(error).__name__
                    )
                self.history.append(
                    iteration=self.budget.iterations,
                    files_modified=[action["path"]]
                    if action.get("action") == "write" and isinstance(action.get("path"), str)
                    else [],
                    error_signature=signature,
                    action=action.get("action", "invalid"),
                    strategy=self.strategy_index,
                    run_id=self.run_id,
                )
                if self._write_streak >= 3 or (
                    check_fixation(self.history.path, run_id=self.run_id)
                    and len(self.history.events()) >= 3
                    and all(
                        e.get("strategy") == self.strategy_index for e in self.history.events()[-3:]
                    )
                ):
                    if self.strategy_index + 1 >= len(STRATEGIES):
                        raise SafetyStop("Fixation persisted after all strategy pivots")
                    self.strategy_index += 1
                    self.emit("strategy_pivot", strategy=self.strategy_index)
                    self._write_streak = 0
                    observation = {
                        "guidance": "Repeated rewriting is not progress. Preserve the existing implementation and create missing tests/documentation or test a concrete defect.",
                        "forced_pivot": STRATEGIES[self.strategy_index],
                        "last_observation": observation,
                    }
                self.save_state("running")
                if self.progress:
                    self.progress(
                        {
                            "iteration": self.budget.iterations,
                            "action": action.get("action", "model"),
                            "outcome": "ok" if signature == "SUCCESS" else "needs repair",
                            "reserved_tokens": self.budget.tokens,
                            "token_limit": self.budget.token_limit,
                            "strategy": self.strategy_index,
                        }
                    )
        except SafetyStop as error:
            self.emit(
                "task_finished",
                outcome="stopped",
                error_category="budget_exhausted" if "kill-switch" in str(error) else "safety_stop",
            )
            return self.save_state("stopped", reason=str(error))
        except Exception as error:
            self.save_state("failed", error_type=type(error).__name__)
            raise
