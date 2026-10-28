"""Single-suite coordinator. Each benchmark owns a cancellable process tree."""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from filelock import FileLock, Timeout

from pulse.benchmarks import MANIFEST, manifest
from pulse.events import EventStream, digest, read_events
from setup_controller import SetupController
from telemetry import atomic_json

STATUSES = ("passed", "failed", "skipped", "blocked", "cancelled", "timed_out")


def environment(root):
    """No home paths, environment values, exception text, or arbitrary subprocess logs."""
    from setup_wizard import application_version

    root = Path(root)
    info = {
        "aass_version": application_version(root),
        "python": platform.python_version(),
        "system": platform.system(),
        "architecture": platform.machine(),
        "docker_command": shutil.which("docker") is not None,
        "ollama_command": shutil.which("ollama") is not None,
        "cpu_count": os.cpu_count(),
        "ram": "unavailable",
        "gpu": "unavailable",
        "configured_providers": [],
        "browser": "unverified",
        "dependencies": "unverified",
        "installation_integrity": "unavailable",
        "commit": None,
    }
    try:
        from setup_api import credentials_report

        info["configured_providers"] = [
            row["id"] for row in credentials_report()["providers"] if row["key_present"]
        ]
        from settings import provider_preferences

        preferences = provider_preferences(root)
        info["provider"] = preferences.get("service", "auto")
        if preferences.get("model"):
            info["judge_model_hash"] = digest(preferences["model"])
        from orchestration_canvas import doctor

        readiness = doctor()["checks"]
        info["docker_ready"] = readiness["docker"]["ready"]
        info["sandbox_ready"] = readiness["sandbox_image"]["ready"]
        info["browser"] = "ready" if readiness["chromium"]["ready"] else "unavailable"
        worker = readiness["ollama_worker"]
        info["worker_ready"] = worker["ready"]
        info["worker_model_hash"] = digest(worker["model"])
        from settings import subprocess_environment

        check = subprocess.run(
            [sys.executable, "-m", "pip", "check"],
            capture_output=True,
            timeout=15,
            env=subprocess_environment(),
        )
        info["dependencies"] = "consistent" if check.returncode == 0 else "inconsistent"
        import httpx

        from settings import ollama_url

        host = ollama_url(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
        with httpx.Client(timeout=5, follow_redirects=False) as client:
            version = client.get(host + "/api/version").json().get("version")
        info["ollama_version"] = (
            version
            if isinstance(version, str) and re.fullmatch(r"\d+\.\d+\.\d+", version)
            else None
        )
    except Exception:
        info["readiness_note"] = "Some service checks unavailable; see benchmark outcomes"
    try:
        from verify_release import verify

        receipt = verify(root)
        info["commit"] = receipt.get("source_revision")
        info["installation_integrity"] = "verified"
    except (ValueError, OSError):
        if (root / "RELEASE-MANIFEST.json").is_file():
            info["installation_integrity"] = "failed"
    return info


class PulseEngine:
    def __init__(
        self,
        root,
        *,
        directory=None,
        live_local=False,
        live_cloud=False,
        callback=None,
        case_executor=None,
    ):
        self.root = Path(root).resolve()
        self.home = self.root / ".aass/pulse"
        self.run_id = uuid.uuid4().hex
        self.directory = Path(directory) if directory else self.home / self.run_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cancel_file = self.directory / "cancel"
        self.live_local = live_local
        self.live_cloud = live_cloud
        if live_cloud and not live_local:
            raise ValueError("Live cloud requires explicit local evaluation consent")
        self.stream = EventStream(self.directory, self.run_id, callback=callback)
        self.executor = case_executor or self._execute_case
        self.controller = SetupController(self.root)
        self.results = []
        self._forwarded = set()
        self.remaining_tokens = 64000
        self.remaining_iterations = 20
        self.started = time.monotonic()
        self.spec = manifest()
        self.environment = environment(self.root)
        self.summary = self._summary("running")

    def _summary(self, status):
        counts = {name: sum(r["status"] == name for r in self.results) for name in STATUSES}
        return {
            "schema": 1,
            "run_id": self.run_id,
            "status": status,
            "benchmark_version": self.spec["version"],
            "manifest_hash": digest(MANIFEST.read_text()),
            "mode": "live" if self.live_local else "deterministic",
            "cloud_consent": self.live_cloud,
            "counts": counts,
            "completed": sum(r["status"] != "skipped" for r in self.results),
            "total": len(self.spec["cases"]),
            "duration": round(time.monotonic() - self.started, 3),
            "reserved_tokens": 64000 - self.remaining_tokens,
            "remaining_tokens": self.remaining_tokens,
            "actual_cost": "unavailable",
            "events_truncated": self.stream.truncated,
            "live_model_acceptance": "not_verified"
            if not self.live_local
            else "see_individual_results",
        }

    def persist(self, status):
        self.summary = self._summary(status)
        atomic_json(self.directory / "summary.json", self.summary)
        atomic_json(self.directory / "benchmark-results.json", self.results)
        atomic_json(self.directory / "environment.json", self.environment)

    def _forward_event(self, case_id, event):
        identity = event.get("event_id")
        if identity in self._forwarded:
            return
        self._forwarded.add(identity)
        safe = {
            k: v
            for k, v in event.items()
            if k
            not in (
                "schema",
                "timestamp",
                "elapsed",
                "sequence",
                "run_id",
                "event_id",
                "test_id",
                "related_event_id",
            )
        }
        self.stream.emit(test_id=case_id, related_event_id=identity, **safe)

    def _execute_case(self, case, directory, live):
        command = [
            sys.executable,
            "-m",
            "pulse.case_runner",
            "--directory",
            str(directory),
            "--case",
            case["id"],
        ]
        if live:
            command += [
                "--live-local",
                "--tokens",
                str(self.remaining_tokens),
                "--iterations",
                str(self.remaining_iterations),
            ]
        if live and self.live_cloud:
            command += ["--live-cloud"]
        stopped = threading.Event()

        def watch():
            while not stopped.wait(0.1):
                if self.cancel_file.exists():
                    self.controller.cancel()

        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
        try:

            def forward(line):
                if line.startswith("PULSE_CASE "):
                    try:
                        self._forward_event(case["id"], json.loads(line[11:]))
                    except (ValueError, TypeError):
                        pass

            result = self.controller._execute(
                command,
                callback=forward,
                timeout=case["live_timeout"] if live else case["timeout"],
                credentials=live,
                label="Pulse benchmark",
            )
            if result.cancelled:
                return {"status": "cancelled", "error_category": "cancelled"}
            if result.timed_out:
                return {"status": "timed_out", "error_category": "deadline_exceeded"}
            path = directory / "result.json"
            if not result.ok or not path.exists() or path.stat().st_size > 16384:
                return {"status": "failed", "error_category": "process_failed"}
            return json.loads(path.read_text())
        finally:
            stopped.set()
            thread.join(timeout=1)
            # Docker daemon containers outlive a killed CLI process tree. Remove
            # only this suite's explicitly labeled containers after interruption.
            if (
                self.cancel_file.exists()
                or locals().get("result")
                and (result.cancelled or result.timed_out)
            ):
                from settings import subprocess_environment

                try:
                    found = subprocess.run(
                        [
                            "docker",
                            "ps",
                            "-aq",
                            "--filter",
                            "label=aass.pulse=" + digest(self.directory.resolve())[:32],
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        env=subprocess_environment(),
                    )
                    owned = [
                        identifier
                        for identifier in found.stdout.split()
                        if re.fullmatch(r"[0-9a-f]{12,64}", identifier)
                    ][:16]
                    if owned:
                        subprocess.run(
                            ["docker", "rm", "-f", *owned],
                            capture_output=True,
                            timeout=15,
                            env=subprocess_environment(),
                        )
                except (OSError, subprocess.TimeoutExpired):
                    self.stream.emit(
                        component="suite",
                        event_type="cleanup_failed",
                        error_category="docker_cleanup_failed",
                    )

    def run(self):
        self.home.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(str(self.home / "suite.lock"), timeout=0):
                return self._run()
        except Timeout:
            self.stream.emit(
                component="suite",
                event_type="suite_finished",
                outcome="blocked",
                error_category="suite_busy",
            )
            self.persist("blocked")
            return self.summary

    def _run(self):
        self.stream.emit(
            component="suite",
            event_type="suite_started",
            mode="live" if self.live_local else "deterministic",
        )
        self.persist("running")
        try:
            for case in self.spec["cases"]:
                if self.cancel_file.exists():
                    break
                live = self.live_local and case["live"]
                self.stream.emit(
                    component="suite",
                    event_type="test_started",
                    test_id=case["id"],
                    mode="live" if live else "deterministic",
                )
                directory = self.directory / case["id"]
                directory.mkdir(exist_ok=True)
                started = time.monotonic()
                if live and (self.remaining_tokens < 8192 or self.remaining_iterations < 2):
                    row = {
                        "status": "blocked",
                        "error_category": "suite_budget_exhausted",
                        "reserved_tokens": 0,
                        "iterations": 0,
                    }
                elif (
                    not self.environment["docker_command"]
                    or self.environment.get("docker_ready") is False
                    or self.environment.get("sandbox_ready") is False
                ) and case["id"] != "resume-integrity":
                    row = {"status": "blocked", "error_category": "docker_unavailable"}
                else:
                    row = self.executor(case, directory, live)
                if row.get("status") not in STATUSES:
                    row = {"status": "failed", "error_category": "invalid_result"}
                row.update(
                    id=case["id"],
                    mode="live" if live else "deterministic",
                    duration=round(time.monotonic() - started, 3),
                )
                self.results.append(row)
                if live:
                    # Unknown usage after a killed child cannot authorize further calls.
                    used = row.get("reserved_tokens", self.remaining_tokens)
                    self.remaining_tokens = max(0, self.remaining_tokens - used)
                    self.remaining_iterations = max(
                        0, self.remaining_iterations - row.get("iterations", 20)
                    )
                for event in read_events(directory / "events.jsonl"):
                    self._forward_event(case["id"], event)
                self.stream.emit(
                    component="suite",
                    event_type="test_finished",
                    test_id=case["id"],
                    outcome=row["status"],
                    duration=row["duration"],
                )
                self.persist("running")
            if self.cancel_file.exists():
                completed_ids = {row["id"] for row in self.results}
                self.results += [
                    dict(id=case["id"], status="skipped", mode="not_run")
                    for case in self.spec["cases"]
                    if case["id"] not in completed_ids
                ]
                status = "cancelled"
            elif any(r["status"] in ("failed", "timed_out") for r in self.results):
                status = "failed"
            elif any(r["status"] == "blocked" for r in self.results):
                status = "blocked"
            else:
                status = "passed"
        except Exception:
            status = "failed"
            self.stream.emit(
                component="suite", event_type="suite_error", error_category="engine_error"
            )
        self.stream.emit(component="suite", event_type="suite_finished", outcome=status)
        self.persist(status)
        return self.summary


def compare(left, right):
    keys = ["benchmark_version", "manifest_hash", "mode", "cloud_consent"]
    differences = [key for key in keys if left["summary"].get(key) != right["summary"].get(key)]
    for key in ["python", "system", "architecture", "worker_model_hash", "judge_model_hash"]:
        if left["environment"].get(key) != right["environment"].get(key):
            differences.append(key)
    for key in ["python", "system", "architecture"]:
        if any(side["environment"].get(key) in (None, "unavailable") for side in [left, right]):
            differences.append(key + "_unverified")
    if left["summary"].get("cloud_consent"):
        for key in ["provider", "judge_model_hash"]:
            if left["environment"].get(key) != right["environment"].get(key):
                differences.append(key)
            if any(
                side["environment"].get(key) in (None, "unavailable", "auto")
                for side in [left, right]
            ):
                differences.append(key + "_unverified")
    if left["summary"].get("mode") == "live" and any(
        not side["environment"].get("worker_model_hash") for side in [left, right]
    ):
        differences.append("live_model_identity_unverified")
    return {
        "comparable": not differences,
        "differences": differences,
        "counts_before": left["summary"]["counts"],
        "counts_after": right["summary"]["counts"],
    }
