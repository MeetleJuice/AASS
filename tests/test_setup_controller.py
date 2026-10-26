import os
import sys
import threading
import time

import pytest

import setup_controller
from setup_controller import MAX_OUTPUT, CommandResult, ControllerError, SetupController


def test_install_keeps_system_changes_and_paid_probes_opt_in(tmp_path, monkeypatch):
    controller = SetupController(tmp_path, base_python="python with spaces")
    calls = []

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        return CommandResult(0, "ready")

    monkeypatch.setattr(controller, "_execute", execute)
    assert controller.install().ok
    assert calls[0][0] == ["python with spaces", str(tmp_path / "install_aass.py"), "--skip-live"]
    assert not calls[0][1].get("credentials", False)
    controller.install(install_prerequisites=True)
    assert calls[1][0][-1] == "--install-prerequisites"
    assert "--verify-live" not in calls[1][0]


def test_missing_runtime_offers_preparation_without_starting_anything(tmp_path):
    with pytest.raises(ControllerError, match="Prepare the local tools") as caught:
        SetupController(tmp_path).json_operation(["credentials"])
    assert caught.value.code == "runtime_missing"


@pytest.mark.parametrize(
    ("returncode", "output", "expected"),
    [
        (0, '{"status":"ok","models":[]}', {"status": "ok", "models": []}),
        (2, '{"status":"error","code":"no_key"}', {"status": "error", "code": "no_key"}),
    ],
)
def test_json_operation_preserves_structured_results(
    tmp_path, monkeypatch, returncode, output, expected
):
    controller = SetupController(tmp_path)
    monkeypatch.setattr(controller, "_runtime", lambda: "runtime python")
    calls = []

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        return CommandResult(returncode, output)

    monkeypatch.setattr(controller, "_execute", execute)
    assert controller.json_operation(["models", "--service", "gemini"]) == expected
    assert calls[0][0] == [
        "runtime python",
        str(tmp_path / "setup_api.py"),
        "models",
        "--service",
        "gemini",
    ]
    assert calls[0][1]["credentials"] is True
    assert "callback" not in calls[0][1]


@pytest.mark.parametrize(
    "result",
    [
        CommandResult(2, "private provider response"),
        CommandResult(0, "[]"),
        CommandResult(2, '{"status":"ok"}'),
        CommandResult(0, '{"status":"unknown"}'),
        CommandResult(-9, "", cancelled=True),
        CommandResult(-9, "", timed_out=True),
    ],
)
def test_json_failure_does_not_echo_untrusted_output(tmp_path, monkeypatch, result):
    controller = SetupController(tmp_path)
    monkeypatch.setattr(controller, "_runtime", lambda: "runtime")
    monkeypatch.setattr(controller, "_execute", lambda *args, **kwargs: result)
    with pytest.raises(ControllerError) as caught:
        controller.json_operation(["credentials"])
    assert "private provider response" not in str(caught.value)


def test_task_rejects_runtime_and_parent_and_child_folders(tmp_path):
    root = tmp_path / "application"
    root.mkdir()
    controller = SetupController(root)
    for target in (root, root.parent, root / "inside"):
        with pytest.raises(ControllerError) as caught:
            controller.run_task(target, "hello")
        assert caught.value.code == "invalid_project"


def test_task_arguments_preserve_spaces_and_shell_punctuation(tmp_path, monkeypatch):
    controller = SetupController(tmp_path / "application")
    monkeypatch.setattr(controller, "_runtime", lambda: "runtime")
    calls = []

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        return CommandResult(0, "done")

    monkeypatch.setattr(controller, "_execute", execute)
    target = tmp_path / "engineering & project"
    assert controller.run_task(target, "  fix $(nothing); & words  ").ok
    assert target.is_dir()
    assert calls[0][0] == [
        "runtime",
        "-m",
        "orchestration_canvas",
        "run",
        "--workspace",
        str(target),
        "--task",
        "fix $(nothing); & words",
    ]
    assert calls[0][1]["credentials"] is True


def test_child_environment_redaction_bounded_output_and_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-fixture-key")
    controller = SetupController(tmp_path, heartbeat=0.02)
    lines = []
    result = controller._execute(
        [
            sys.executable,
            "-c",
            "import os,time; print(os.environ.get('GEMINI_API_KEY','removed')); "
            "print('secret-fixture-key'); print('API_KEY=some-file-secret'); "
            "print('x' * 300000); time.sleep(.1)",
        ],
        callback=lines.append,
        timeout=10,
    )
    assert result.ok
    assert len(result.output) <= MAX_OUTPUT
    assert "secret-fixture-key" not in "\n".join(lines)
    assert "some-file-secret" not in "\n".join(lines)
    assert "removed" in lines
    assert any("[REDACTED]" in line for line in lines)
    assert any("Working" in line for line in lines)


def test_timeout_kills_process_and_releases_controller_for_retry(tmp_path):
    controller = SetupController(tmp_path)
    result = controller._execute([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)
    assert result.timed_out
    assert not result.ok
    assert not controller.cancel()
    assert controller._execute([sys.executable, "-c", "print('retried')"], timeout=5).ok


def test_cancel_and_second_job_rejection(tmp_path):
    controller = SetupController(tmp_path)
    results = []
    ready = threading.Event()
    errors = []

    def run():
        try:
            results.append(
                controller._execute(
                    [sys.executable, "-u", "-c", "import time; print('ready'); time.sleep(30)"],
                    callback=lambda line: ready.set() if line == "ready" else None,
                    timeout=10,
                )
            )
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert ready.wait(timeout=5)
        with pytest.raises(ControllerError) as caught:
            controller._execute([sys.executable, "-c", "pass"], timeout=5)
        assert caught.value.code == "busy"
        assert controller.cancel()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert not errors
        assert results[0].cancelled
        assert not results[0].ok
    finally:
        controller.cancel()
        thread.join(timeout=5)


def test_cancel_during_process_startup_is_not_lost(tmp_path, monkeypatch):
    controller = SetupController(tmp_path)
    original_popen = setup_controller.subprocess.Popen
    entered, release = threading.Event(), threading.Event()
    results = []

    def delayed_popen(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(setup_controller.subprocess, "Popen", delayed_popen)
    thread = threading.Thread(
        target=lambda: results.append(
            controller._execute([sys.executable, "-c", "import time; time.sleep(30)"], timeout=10)
        )
    )
    thread.start()
    try:
        assert entered.wait(timeout=5)
        assert controller.cancel()
        release.set()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert results[0].cancelled
        assert not results[0].ok
    finally:
        release.set()
        controller.cancel()
        thread.join(timeout=5)


def test_timeout_also_stops_child_after_parent_exited(tmp_path):
    controller = SetupController(tmp_path)
    marker = tmp_path / "descendant-finished"
    started = tmp_path / "descendant-started"
    descendant = (
        "import time,pathlib; "
        f"pathlib.Path({str(started)!r}).touch(); time.sleep(2); "
        f"pathlib.Path({str(marker)!r}).touch()"
    )
    command = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable, '-c', {descendant!r}]); print('parent exited')"
    )
    parent_exited = []

    def check_parent(line):
        if line == "parent exited":
            deadline = time.monotonic() + 1
            while controller._process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            parent_exited.append(controller._process.poll() is not None)

    result = controller._execute([sys.executable, "-c", command], callback=check_parent, timeout=1)
    assert result.timed_out
    assert started.exists()
    assert parent_exited == [True]
    time.sleep(2.1)
    assert not marker.exists()


def test_normal_completion_keeps_intentionally_started_background_process(tmp_path):
    controller = SetupController(tmp_path)
    marker = tmp_path / "background-service-finished"
    descendant = f"import time,pathlib; time.sleep(.4); pathlib.Path({str(marker)!r}).touch()"
    command = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable, '-c', {descendant!r}], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); print('started')"
    )
    result = controller._execute([sys.executable, "-c", command], timeout=5)
    assert result.ok
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists(), "normal job-handle cleanup must preserve installed services"


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended process job assignment")
def test_failed_windows_job_assignment_never_executes_untracked_child(tmp_path, monkeypatch):
    original_job = setup_controller._WindowsJob

    class FailingJob(original_job):
        def assign_and_resume(self, _process):
            raise setup_controller.WindowsJobError("fixture assignment failure")

    controller = SetupController(tmp_path)
    marker = tmp_path / "untracked-child-executed"
    monkeypatch.setattr(setup_controller, "_WindowsJob", FailingJob)
    with pytest.raises(ControllerError) as caught:
        controller._execute(
            [sys.executable, "-c", f"import pathlib; pathlib.Path({str(marker)!r}).touch()"],
            timeout=5,
        )
    assert caught.value.code == "process_tracking_failed"
    assert not marker.exists()
    monkeypatch.setattr(setup_controller, "_WindowsJob", original_job)
    assert controller._execute([sys.executable, "-c", "print('retried')"], timeout=5).ok


@pytest.mark.skipif(os.name != "nt", reason="Windows tracking creation failure")
def test_unavailable_windows_job_cannot_start_an_untracked_operation(tmp_path, monkeypatch):
    def unavailable():
        raise setup_controller.WindowsJobError("fixture creation failure")

    controller = SetupController(tmp_path)
    monkeypatch.setattr(setup_controller, "_WindowsJob", unavailable)
    marker = tmp_path / "untracked-operation-started"
    with pytest.raises(ControllerError) as caught:
        controller._execute(
            [sys.executable, "-c", f"import pathlib; pathlib.Path({str(marker)!r}).touch()"],
            timeout=5,
        )
    assert caught.value.code == "process_tracking_failed"
    assert not marker.exists()


def test_launch_failure_has_actionable_sanitized_message(tmp_path):
    controller = SetupController(tmp_path)
    with pytest.raises(ControllerError) as caught:
        controller._execute([str(tmp_path / "missing-executable")], timeout=1)
    assert caught.value.code == "launch_failed"
    assert controller._execute([sys.executable, "-c", "pass"], timeout=5).ok
