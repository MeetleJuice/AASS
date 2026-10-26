"""Bounded dual-loop supervisor. Runtime control code lives outside the target workspace."""

import hashlib
import os
import re
import tempfile
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
from worker_agent import WorkerAgent

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
    def __init__(self, workspace, worker, judge, *, sandbox=None, budget=None, tools=None):
        self.root = Path(workspace).resolve(strict=True)
        runtime = Path(__file__).resolve().parent
        if self.root == runtime or runtime.is_relative_to(self.root):
            raise ValueError("Use a separate target checkout, not the AASS runtime checkout")
        self.worker, self.judge = worker, judge
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

    def _context(self, observation):
        return {
            "observation": str(observation)[-MAX_CONTEXT_BYTES:],
            "changed_files": sorted(self.changed),
            "verified_since_write": self.tested,
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
                return content.decode("utf-8")
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
            return "File written. A new successful test is required."
        if kind == "test":
            result = self.sandbox.run(action["command"])
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
                raise RuntimeError(f"test:{result.returncode}:{digest}")
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
        observation = "Start by mapping or reading the target repository."
        self.save_state("running")
        try:
            while True:
                self.budget.tick()
                action = {"action": "model"}
                try:
                    proposed = self.worker.step(
                        task,
                        self._context(observation),
                        STRATEGIES[self.strategy_index],
                        self.budget,
                    )
                    WorkerAgent.validate(proposed)
                    action = proposed
                    if action["action"] == "finish":
                        if not self.tested:
                            raise ValueError(
                                "Cannot finish without a passing test since the last write"
                            )
                        verdict = self.judge.evaluate(
                            task,
                            {"changes": self.changed, "tests": self.evidence[-3:]},
                            self.budget,
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
                            return self.save_state("approved", review=verdict)
                        observation = {"judge_rejected": verdict}
                        signature = "JUDGE_REJECTED"
                    else:
                        observation = self.execute(action)
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
                    signature = (
                        str(error)
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
                if (
                    check_fixation(self.history.path, run_id=self.run_id)
                    and len(self.history.events()) >= 3
                    and all(
                        e.get("strategy") == self.strategy_index for e in self.history.events()[-3:]
                    )
                ):
                    if self.strategy_index + 1 >= len(STRATEGIES):
                        raise SafetyStop("Fixation persisted after all strategy pivots")
                    self.strategy_index += 1
                    observation = {
                        "forced_pivot": STRATEGIES[self.strategy_index],
                        "last_observation": observation,
                    }
                self.save_state("running")
        except SafetyStop as error:
            return self.save_state("stopped", reason=str(error))
        except Exception as error:
            self.save_state("failed", error_type=type(error).__name__)
            raise
