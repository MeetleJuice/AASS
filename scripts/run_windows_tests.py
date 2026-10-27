"""Bound CI tests independently of child native code and blocked log consumers."""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_LOG = 2 * 1024 * 1024


def _safe_test_name(value):
    value = value.split("[", 1)[0].strip().replace("\\", "/")
    filename, separator, functions = value.rpartition(".py::")
    if not separator:
        return "test execution"
    filename = filename.rsplit("/", 1)[-1] + ".py"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.py", filename) or not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*", functions
    ):
        return "test execution"
    return filename + "::" + functions


def _progress(path):
    try:
        if path.is_symlink() or not path.is_file():
            return None
        stat = path.stat()
        if stat.st_size > 4096:
            return None
        return (stat.st_mtime_ns, stat.st_size), _safe_test_name(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return None


def _junit_success(path, initial_stamp):
    try:
        if path.is_symlink() or not path.is_file():
            return False
        stat = path.stat()
        if stat.st_size > 10 * 1024 * 1024 or (stat.st_mtime_ns, stat.st_size) == initial_stamp:
            return False
        root = ET.parse(path).getroot()  # nosec B314 # bounded local pytest output
        suites = list(root.iter("testsuite"))
        return (
            bool(suites)
            and sum(int(suite.get("tests", "0")) for suite in suites) > 0
            and all(
                int(suite.get("failures", "0")) == 0 and int(suite.get("errors", "0")) == 0
                for suite in suites
            )
        )
    except (OSError, ValueError, ET.ParseError):
        return False


def _stop(process):
    """Never capture taskkill output or let cleanup prevent a saved timeout receipt."""
    if process is None:
        return
    try:
        if os.name == "nt" and process.poll() is None:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                pass
        elif os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    except OSError:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    parser.add_argument("--junitxml", required=True)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--collection-timeout", type=float)
    parser.add_argument("--drain-timeout", type=float, default=3)
    parser.add_argument("--output", default="generated/windows-output.txt")
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args(argv)
    if (
        args.timeout <= 0
        or args.drain_timeout <= 0
        or args.collection_timeout is not None
        and args.collection_timeout <= 0
    ):
        parser.error("Timeouts must be positive")
    output_path = Path(args.output).absolute()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path = Path(
        os.environ.get("AASS_CI_PROGRESS", str(output_path.parent / "windows-last-test.txt"))
    ).absolute()
    environment = dict(os.environ, AASS_CI_PROGRESS=str(progress_path), PYTHONUNBUFFERED="1")
    command = [
        args.python,
        "-u",
        "-m",
        "pytest",
        "-vv",
        "-s",
        "-p",
        "scripts.ci_test_progress",
        "--junitxml=" + args.junitxml,
        *args.tests,
    ]
    reader_done, spawn_done = threading.Event(), threading.Event()
    state = {"dropped_stdout_bytes": 0, "output_bytes": 0}
    processes = []
    junit_path = Path(args.junitxml).absolute()
    try:
        junit_stat = junit_path.stat()
        initial_junit_stamp = (junit_stat.st_mtime_ns, junit_stat.st_size)
    except OSError:
        initial_junit_stamp = None
    initial_progress = _progress(progress_path)
    previous_stamp = initial_progress[0] if initial_progress else None
    current = "test collection"
    deadline = time.monotonic() + (
        args.collection_timeout if args.collection_timeout is not None else max(20, args.timeout)
    )

    def reader(process):
        try:
            with output_path.open("w+b", buffering=0) as log:
                while True:
                    chunk = process.stdout.read1(4096)
                    if not chunk:
                        break
                    if log.tell() + len(chunk) > MAX_LOG:
                        log.seek(0)
                        log.truncate()
                    log.write(chunk)
                    state["output_bytes"] += len(chunk)
                    # Retain output on disk, not a potentially blocked console.
                    # In particular, do not leave a Windows CRT writer thread
                    # holding a descriptor lock when the monitor must exit.
                    state["dropped_stdout_bytes"] += len(chunk)
        except (OSError, ValueError) as error:
            state["capture_error"] = type(error).__name__
        finally:
            reader_done.set()

    def spawn():
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
                env=environment,
            )
            processes.append(process)
            threading.Thread(target=reader, args=(process,), daemon=True).start()
        except (OSError, ValueError) as error:
            state["startup_error"] = type(error).__name__
            reader_done.set()
        finally:
            spawn_done.set()

    threading.Thread(target=spawn, daemon=True).start()
    exited_at = None

    def receipt(code, phase, *, wrapper_code, timed_out=False):
        process = processes[0] if processes else None
        data = {
            "returncode": code,
            "wrapper_returncode": wrapper_code,
            "hex": hex(code & 0xFFFFFFFF),
            "timed_out": timed_out,
            "phase": phase,
            "last_started": current,
            "child_returncode": process.poll() if process is not None else None,
            "output_complete": reader_done.is_set(),
            **state,
        }
        path = output_path.parent / "windows-process-exit.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary, path)

    def finish(wrapper_code, child_code, phase, *, timed_out=False):
        # Save evidence before termination or logging; neither can erase the receipt.
        receipt(child_code, phase, wrapper_code=wrapper_code, timed_out=timed_out)
        if wrapper_code:
            _stop(processes[0] if processes else None)
        if timed_out:
            message = "Windows test timeout: Last started check at timeout: " + current
        elif phase == "output_not_closed" and not wrapper_code:
            message = (
                "Pytest exited successfully with a complete passing JUnit report; "
                "an inherited stdout pipe remained open. Remaining child shutdown was not observed."
            )
        else:
            message = f"CI Python process exit: {child_code}; monitor phase: {phase}"
        receipt(child_code, phase, wrapper_code=wrapper_code, timed_out=timed_out)
        # This process has written nothing to stdout before this bounded result.
        # Keep it below the smallest Windows anonymous-pipe buffer (4 KiB).
        try:
            os.write(sys.stdout.fileno(), (message[:1000] + "\n").encode("utf-8"))
        except (OSError, ValueError):
            pass
        return wrapper_code

    while True:
        now = time.monotonic()
        progress = _progress(progress_path)
        if progress and progress[0] != previous_stamp:
            previous_stamp, current = progress
            deadline = now + args.timeout
        if state.get("startup_error"):
            return finish(2, 2, "process_startup")
        if state.get("capture_error"):
            return finish(2, 2, "output_capture")
        process = processes[0] if processes else None
        if process is not None:
            code = process.poll()
            if code is not None:
                if reader_done.is_set():
                    passed = code == 0 and _junit_success(junit_path, initial_junit_stamp)
                    return finish(0 if passed else 1, code, "completed")
                if exited_at is None:
                    exited_at = now
                elif now - exited_at >= args.drain_timeout:
                    state["output_drain_incomplete"] = True
                    state["remaining_child_shutdown_observed"] = False
                    passed = code == 0 and _junit_success(junit_path, initial_junit_stamp)
                    return finish(0 if passed else 2, code, "output_not_closed")
            elif now >= deadline:
                return finish(124, 124, "test_execution", timed_out=True)
        elif now >= deadline:
            return finish(124, 124, "process_startup", timed_out=True)
        time.sleep(0.05)


if __name__ == "__main__":
    # A descendant holding captured output must not delay interpreter shutdown.
    # All authoritative outcome evidence is already atomically saved by main().
    os._exit(main())
