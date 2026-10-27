"""Standard-library process controller for the graphical setup window.

Methods are synchronous so the UI can run them in one background thread. Only
the controller's own subprocess tree is stopped by cancellation or a deadline.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from settings import SECRET_NAMES, subprocess_environment

ROOT = Path(__file__).resolve().parent
MAX_OUTPUT = 262144
MAX_LINE = 16384
CREATE_SUSPENDED = 0x00000004


class ControllerError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class WindowsJobError(OSError):
    """A Windows-owned process tree could not be tracked or stopped."""


class _WindowsJob:
    """Track descendants before the suspended primary process can execute.

    The job has no kill-on-close flag: successful installers may start services
    that should remain running. Cancellation explicitly terminates the job.
    All Windows imports and API initialization stay behind the platform branch.
    """

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.types = wintypes
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([wintypes.LPVOID, wintypes.LPCWSTR], wintypes.HANDLE),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            "Thread32First": ([wintypes.HANDLE, wintypes.LPVOID], wintypes.BOOL),
            "Thread32Next": ([wintypes.HANDLE, wintypes.LPVOID], wintypes.BOOL),
            "OpenThread": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise WindowsJobError("Windows could not create owned process tracking")

    def _close_handle(self, handle):
        if not self.api.CloseHandle(handle):
            raise WindowsJobError("Windows could not release an owned tracking handle")

    def assign_and_resume(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise WindowsJobError("Windows could not assign the suspended owned process")
        ctypes, types = self.ctypes, self.types

        class ThreadEntry(ctypes.Structure):
            _fields_ = [
                ("dwSize", types.DWORD),
                ("cntUsage", types.DWORD),
                ("th32ThreadID", types.DWORD),
                ("th32OwnerProcessID", types.DWORD),
                ("tpBasePri", types.LONG),
                ("tpDeltaPri", types.LONG),
                ("dwFlags", types.DWORD),
            ]

        # Popen closes CreateProcess's primary-thread handle. Enumerate only
        # this suspended process's threads to resume it with documented APIs.
        snapshot = self.api.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
        if snapshot in (None, ctypes.c_void_p(-1).value):
            raise WindowsJobError("Windows could not locate the owned process thread")
        resumed = False
        try:
            entry = ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            found = self.api.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.th32OwnerProcessID == process.pid:
                    thread = self.api.OpenThread(0x0002, False, entry.th32ThreadID)
                    if not thread:
                        raise WindowsJobError("Windows could not open the owned process thread")
                    try:
                        previous = self.api.ResumeThread(thread)
                        if previous == 0xFFFFFFFF:
                            raise WindowsJobError("Windows could not resume the owned process")
                        resumed = resumed or previous > 0
                    finally:
                        self._close_handle(thread)
                entry.dwSize = ctypes.sizeof(entry)
                found = self.api.Thread32Next(snapshot, ctypes.byref(entry))
            if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                raise WindowsJobError("Windows could not finish owned thread discovery")
            if not resumed:
                raise WindowsJobError("Windows did not find the suspended owned process thread")
        finally:
            self._close_handle(snapshot)

    def terminate(self):
        if self.handle and not self.api.TerminateJobObject(self.handle, 130):
            raise WindowsJobError("Windows could not stop the owned process tree")

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            self._close_handle(handle)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str
    cancelled: bool = False
    timed_out: bool = False

    @property
    def ok(self):
        return self.returncode == 0 and not self.cancelled and not self.timed_out


class SetupController:
    def __init__(self, root=ROOT, base_python=sys.executable, *, heartbeat=15):
        self.root = Path(root).resolve()
        interpreter = Path(base_python)
        if (
            os.name == "nt"
            and interpreter.name.lower() == "pythonw.exe"
            and interpreter.with_name("python.exe").is_file()
        ):
            interpreter = interpreter.with_name("python.exe")
        self.base_python = str(interpreter)
        self.heartbeat = heartbeat
        self._job_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._process = None
        self._cancelled = threading.Event()

    @property
    def runtime(self):
        return (
            self.root
            / ".venv"
            / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        )

    def _runtime(self):
        if not self.runtime.is_file():
            raise ControllerError(
                "runtime_missing", "Prepare the local tools first, then retry this step."
            )
        return str(self.runtime)

    def install(self, callback=None, *, install_prerequisites=False):
        command = [self.base_python, str(self.root / "install_aass.py"), "--skip-live"]
        if install_prerequisites:
            command.append("--install-prerequisites")
        return self._execute(
            command, callback=callback, timeout=3600, label="Preparing local tools"
        )

    def json_operation(self, args, *, timeout=240):
        result = self._execute(
            [self._runtime(), str(self.root / "setup_api.py"), *args],
            timeout=timeout,
            credentials=True,
            label="Checking configuration",
        )
        if result.cancelled:
            raise ControllerError("cancelled", "The check was cancelled. You can retry it.")
        if result.timed_out:
            raise ControllerError(
                "timeout", "The check took too long. Check the connection and retry this step."
            )
        try:
            payload = json.loads(result.output)
        except (ValueError, TypeError):
            raise ControllerError(
                "invalid_response", "The check did not return a usable result. Retry this step."
            ) from None
        if (
            not isinstance(payload, dict)
            or payload.get("status") not in {"ok", "error"}
            or (result.returncode != 0 and payload.get("status") == "ok")
        ):
            raise ControllerError(
                "invalid_response", "The check did not finish successfully. Retry this step."
            )
        return payload

    def run_task(self, target, task, callback=None):
        project = Path(target).expanduser().resolve()
        if project.is_relative_to(self.root) or self.root.is_relative_to(project):
            raise ControllerError(
                "invalid_project", "Choose a project folder outside the AASS application folder."
            )
        if not isinstance(task, str) or not task.strip():
            raise ControllerError("task_required", "Enter what you want AASS to build or fix.")
        if len(task) > 32768:
            raise ControllerError(
                "task_too_long", "Keep the task description below 32,768 characters."
            )
        runtime = self._runtime()
        project.mkdir(parents=True, exist_ok=True)
        return self._execute(
            [
                runtime,
                "-m",
                "orchestration_canvas",
                "run",
                "--workspace",
                str(project),
                "--task",
                task.strip(),
            ],
            callback=callback,
            credentials=True,
            timeout=7200,
            label="Running the task",
        )

    def cancel(self):
        with self._process_lock:
            if self._process is None and not self._job_lock.locked():
                return False
            self._cancelled.set()
            return True

    @staticmethod
    def _stop(process, windows_job=None):
        try:
            if windows_job is not None:
                # Job membership survives the primary process exiting. This
                # also stops a descendant that still holds the output pipe.
                windows_job.terminate()
            elif os.name != "nt":
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
        finally:
            with contextlib.suppress(OSError):
                if process.poll() is None:
                    process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=10)

    @staticmethod
    def _redactor():
        values = sorted(
            (
                value
                for name, value in os.environ.items()
                if value
                and (
                    name.upper() in SECRET_NAMES
                    or name.upper().endswith(("_API_KEY", "_TOKEN", "_PASSWORD", "_DSN"))
                )
            ),
            key=len,
            reverse=True,
        )

        def redact(text):
            for value in values:
                text = text.replace(value, "[REDACTED]")
            text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)
            text = re.sub(
                r"(?i)([?&](?:token|key|api_key|access_token|password)=)[^&\s]+",
                r"\1[REDACTED]",
                text,
            )
            text = re.sub(
                r"(?i)(\b(?:[A-Z0-9_]*(?:API_KEY|TOKEN|PASSWORD|DSN))\s*[=:]\s*)[^\s,;]+",
                r"\1[REDACTED]",
                text,
            )
            return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)

        return redact

    def _execute(self, command, *, callback=None, timeout, credentials=False, label="Working"):
        with self._process_lock:
            if not self._job_lock.acquire(blocking=False):
                raise ControllerError(
                    "busy", "A check is already running. Wait for it or cancel it."
                )
            self._cancelled.clear()
        process = None
        windows_job = None
        reader_started = completed = False
        stop_reader = threading.Event()
        try:
            redact = self._redactor()
            if os.name == "nt":
                windows_job = _WindowsJob()
            process = subprocess.Popen(
                command,
                cwd=self.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=os.name != "nt",
                creationflags=(subprocess.CREATE_NO_WINDOW | CREATE_SUSPENDED)
                if os.name == "nt"
                else 0,
                env=subprocess_environment(credentials=credentials),
            )
            with self._process_lock:
                self._process = process
            if windows_job is not None:
                windows_job.assign_and_resume(process)
            chunks = queue.Queue(maxsize=128)

            def offer(item):
                while not stop_reader.is_set():
                    try:
                        chunks.put(item, timeout=0.1)
                        return
                    except queue.Full:
                        pass

            def read():
                try:
                    while True:
                        chunk = process.stdout.readline(MAX_LINE)
                        if not chunk:
                            break
                        offer(chunk)
                finally:
                    process.stdout.close()
                    offer(None)

            threading.Thread(target=read, daemon=True).start()
            reader_started = True
            started = last_tick = time.monotonic()
            output, ended, timed_out = "", False, False
            while not ended or process.poll() is None:
                now = time.monotonic()
                timed_out = now - started > timeout
                if self._cancelled.is_set() or timed_out:
                    self._stop(process, windows_job)
                    break
                try:
                    chunk = chunks.get(timeout=0.05)
                    if chunk is None:
                        ended = True
                    else:
                        safe = redact(chunk)
                        output = (output + safe)[-MAX_OUTPUT:]
                        if callback:
                            callback(safe.rstrip("\r\n"))
                except queue.Empty:
                    pass
                if callback and now - last_tick >= self.heartbeat:
                    callback(f"[AASS] {label} ({int(now - started)}s)...")
                    last_tick = now
            code = process.wait(timeout=10)
            completed = True
            return CommandResult(code, output, self._cancelled.is_set(), timed_out)
        except WindowsJobError:
            raise ControllerError(
                "process_tracking_failed",
                "Windows could not safely track or stop this operation. Close AASS and retry it.",
            ) from None
        except OSError:
            raise ControllerError(
                "launch_failed", "This step could not start. Check the application files and retry."
            ) from None
        finally:
            stop_reader.set()
            try:
                if process is not None and not completed:
                    self._stop(process, windows_job)
            finally:
                try:
                    if process is not None and not reader_started and process.stdout is not None:
                        process.stdout.close()
                    if windows_job is not None:
                        windows_job.close()
                finally:
                    with self._process_lock:
                        self._process = None
                    self._job_lock.release()
