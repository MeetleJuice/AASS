"""Exercise the CI runner as a real process, including an undrained stdout pipe."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_windows_tests.py"


def command(tmp_path, body, *, timeout="1", python=None):
    test = tmp_path / "test_runner_fixture.py"
    test.write_text(body, encoding="utf-8")
    return [
        sys.executable,
        str(RUNNER),
        "--python",
        python or sys.executable,
        "--junitxml",
        str(tmp_path / "results.xml"),
        "--output",
        str(tmp_path / "output.txt"),
        "--timeout",
        timeout,
        str(test),
    ]


def environment(tmp_path):
    return dict(
        os.environ,
        AASS_CI_PROGRESS=str(tmp_path / "progress.txt"),
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
    )


def report(tmp_path):
    return json.loads((tmp_path / "windows-process-exit.json").read_text(encoding="utf-8"))


def test_normal_pass_retains_junit_output_and_original_exit(tmp_path):
    result = subprocess.run(
        command(tmp_path, "def test_pass():\n assert True\n", timeout="10"),
        cwd=ROOT,
        env=environment(tmp_path),
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert (tmp_path / "results.xml").is_file()
    receipt = report(tmp_path)
    assert (
        receipt["returncode"] == receipt["child_returncode"] == receipt["wrapper_returncode"] == 0
    )
    assert receipt["phase"] == "completed" and not receipt["timed_out"]
    assert receipt["output_complete"]
    assert "1 passed" in (tmp_path / "output.txt").read_text(encoding="utf-8")


def test_undrained_stdout_cannot_disable_deadline_and_final_log_tail_is_retained(tmp_path):
    marker = tmp_path / "body-started"
    body = (
        "import time\nfrom pathlib import Path\n"
        "def test_backpressure():\n"
        f" Path({str(marker)!r}).touch()\n"
        " print('A' * 2000000, flush=True)\n"
        " print('FINAL_FLOOD_MARKER', flush=True)\n"
        " time.sleep(30)\n"
    )
    process = subprocess.Popen(
        command(tmp_path, body),
        cwd=ROOT,
        env=environment(tmp_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name != "nt",
    )
    started = time.monotonic()
    try:
        # Deliberately do not read either output pipe until the wrapper exits.
        assert process.wait(timeout=25) == 124
        assert time.monotonic() - started < 25
        assert marker.exists(), "fixture must reach its test body, not time out in collection"
        receipt = report(tmp_path)
        assert receipt["timed_out"] and receipt["phase"] == "test_execution"
        assert receipt["last_started"] == "test_runner_fixture.py::test_backpressure"
        assert receipt["output_bytes"] > 65536
        assert receipt["dropped_stdout_bytes"] > 0
        assert b"FINAL_FLOOD_MARKER" in (tmp_path / "output.txt").read_bytes()
        assert (tmp_path / "output.txt").stat().st_size <= 2 * 1024 * 1024
    finally:
        if process.poll() is None:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        process.communicate(timeout=10)


def test_timeout_retains_last_started_name_without_claiming_failed_assertion(tmp_path):
    result = subprocess.run(
        command(tmp_path, "import time\ndef test_slow():\n time.sleep(30)\n"),
        cwd=ROOT,
        env=environment(tmp_path),
        capture_output=True,
        timeout=30,
    )
    receipt = report(tmp_path)
    assert result.returncode == 124
    assert receipt["last_started"] == "test_runner_fixture.py::test_slow"
    assert receipt["timed_out"] and receipt["returncode"] == 124
    assert b"Last started check at timeout" in result.stdout


def test_missing_interpreter_has_a_safe_startup_receipt(tmp_path):
    result = subprocess.run(
        command(tmp_path, "def test_unused():\n pass\n", python=str(tmp_path / "missing-python")),
        cwd=ROOT,
        env=environment(tmp_path),
        capture_output=True,
        timeout=10,
    )
    receipt = report(tmp_path)
    assert result.returncode == 2
    assert receipt["phase"] == "process_startup"
    assert receipt["wrapper_returncode"] == 2
    assert receipt["startup_error"] in {"FileNotFoundError", "PermissionError"}
    assert receipt["child_returncode"] is None


def test_successful_pytest_exit_is_preserved_when_a_descendant_holds_stdout(tmp_path):
    pid_file = tmp_path / "owned-descendant.pid"
    body = (
        "import subprocess,sys\nfrom pathlib import Path\n"
        "def test_background_stdout():\n"
        " child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f" Path({str(pid_file)!r}).write_text(str(child.pid), encoding='utf-8')\n"
        " assert True\n"
    )
    # The test deadline expires before output draining does. An already-exited
    # successful pytest process must not be reclassified as a stalled test.
    cmd = command(tmp_path, body, timeout="1")
    cmd[-1:-1] = ["--drain-timeout", "1.5"]
    try:
        result = subprocess.run(
            cmd, cwd=ROOT, env=environment(tmp_path), capture_output=True, timeout=25
        )
        receipt = report(tmp_path)
        assert result.returncode == 0
        assert receipt["returncode"] == receipt["child_returncode"] == 0
        assert receipt["wrapper_returncode"] == 0
        assert receipt["phase"] == "output_not_closed"
        assert not receipt["timed_out"]
        assert receipt["output_drain_incomplete"]
        assert not receipt["remaining_child_shutdown_observed"]
        assert (tmp_path / "results.xml").is_file()
        assert b"complete passing JUnit" in result.stdout
        assert b"Windows test timeout" not in result.stdout
    finally:
        if pid_file.is_file():
            pid = int(pid_file.read_text(encoding="utf-8"))
            try:
                # This PID came directly from our synthetic child; no PID scans.
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_failing_assertion_retains_native_failure_and_fresh_junit(tmp_path):
    result = subprocess.run(
        command(tmp_path, "def test_failure():\n assert 1 == 2\n", timeout="10"),
        cwd=ROOT,
        env=environment(tmp_path),
        capture_output=True,
        timeout=30,
    )
    receipt = report(tmp_path)
    assert result.returncode == 1
    assert receipt["returncode"] == receipt["child_returncode"] == 1
    assert receipt["wrapper_returncode"] == 1
    assert not receipt["timed_out"]
    assert (tmp_path / "results.xml").is_file()
    assert b"1 failed" in (tmp_path / "output.txt").read_bytes()


def test_zero_test_collection_does_not_pass_release_gate(tmp_path):
    result = subprocess.run(
        command(tmp_path, "# Deliberately collect no tests.\n", timeout="10"),
        cwd=ROOT,
        env=environment(tmp_path),
        capture_output=True,
        timeout=30,
    )
    receipt = report(tmp_path)
    assert result.returncode != 0
    assert receipt["child_returncode"] == 5
    assert receipt["wrapper_returncode"] != 0


def test_breadcrumb_uses_structured_location_for_external_windows_collection(tmp_path, monkeypatch):
    from scripts.ci_test_progress import pytest_runtest_logstart
    from scripts.run_windows_tests import _progress

    path = tmp_path / "progress.txt"
    monkeypatch.setenv("AASS_CI_PROGRESS", str(path))
    pytest_runtest_logstart(
        "external-collection::not-a-source-node-id",
        (r"D:\temporary\test_runner_fixture.py", 3, "test_slow[private-parameter]"),
    )
    assert path.read_text(encoding="utf-8") == "test_runner_fixture.py::test_slow"
    assert _progress(path)[1] == "test_runner_fixture.py::test_slow"
