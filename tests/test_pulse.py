"""Prove Pulse can fail, cancel, block, retain evidence and export safely."""

import json
import os
import sys
import zipfile
from pathlib import Path

import pytest
from filelock import FileLock

from pulse import engine
from pulse.benchmarks import manifest
from pulse.events import EventStream, read_events
from pulse.report import documents, export_zip, open_report
from telemetry import atomic_json


@pytest.fixture
def quiet_environment(monkeypatch):
    monkeypatch.setattr(
        engine,
        "environment",
        lambda root: dict(
            docker_command=True,
            worker_ready=False,
            system="Windows",
            python="3.12.10",
            architecture="AMD64",
        ),
    )


def test_events_incremental_torn_line_and_size_bound(tmp_path):
    stream = EventStream(tmp_path, "0" * 32, max_bytes=800)
    stream.emit(
        component="worker",
        event_type="model_returned",
        actual_input_tokens=10,
        actual_output_tokens=4,
        exception="API_KEY=FAKE_SECRET /Users/private",
        raw_response="FAKE_SECRET",
    )
    assert read_events(stream.path)[0]["actual_input_tokens"] == 10
    with stream.path.open("a") as f:
        f.write("{torn")
    assert len(read_events(stream.path)) == 1
    for _ in range(10):
        stream.emit(component="suite", event_type="suite_started")
    assert stream.truncated and (tmp_path / "events-truncated").exists()
    assert "FAKE_SECRET" not in stream.path.read_text()


def test_real_progress_failure_timeout_and_blocked_are_not_passes(tmp_path, quiet_environment):
    statuses = iter(
        ["passed", "failed", "blocked", "timed_out", "skipped", "passed", "passed", "passed"]
    )
    observed = []

    def execute(case, directory, live):
        assert directory.is_relative_to(tmp_path / ".aass/pulse")
        assert live is False
        return {"status": next(statuses), "error_category": "assertion_failed"}

    pulse = engine.PulseEngine(tmp_path, case_executor=execute, callback=observed.append)
    report = pulse.run()
    assert report["status"] == "failed"
    assert report["counts"]["failed"] == 1 and report["counts"]["timed_out"] == 1
    assert report["completed"] == 7 and report["total"] == 8
    finishes = [e for e in observed if e.get("event_type") == "test_finished"]
    assert len(finishes) == 8
    assert load_json(pulse.directory / "summary.json")["status"] == "failed"


def load_json(path):
    return json.loads(path.read_text())


def test_cancellation_retains_partial_results_and_skips_unstarted(tmp_path, quiet_environment):
    def execute(case, directory, live):
        pulse.cancel_file.touch()
        return {"status": "cancelled"}

    pulse = engine.PulseEngine(tmp_path, case_executor=execute)
    report = pulse.run()
    assert report["status"] == "cancelled"
    assert report["counts"]["cancelled"] == 1 and report["counts"]["skipped"] == 7
    assert report["completed"] == 1
    assert len(load_json(pulse.directory / "benchmark-results.json")) == 8


def test_missing_docker_is_blocked_not_mock_pass(tmp_path, quiet_environment):
    pulse = engine.PulseEngine(tmp_path, case_executor=lambda *a: {"status": "passed"})
    pulse.environment["docker_command"] = False
    report = pulse.run()
    assert report["status"] == "blocked"
    assert report["counts"]["blocked"] == 7


def test_simultaneous_runs_rejected_and_repeat_run_works(tmp_path, quiet_environment):
    pulse = engine.PulseEngine(tmp_path, case_executor=lambda *a: {"status": "passed"})
    with FileLock(str(pulse.home / "suite.lock")):
        assert pulse.run()["status"] == "blocked"
    again = engine.PulseEngine(tmp_path, case_executor=lambda *a: {"status": "passed"})
    assert again.directory != pulse.directory
    assert again.run()["status"] == "passed"


def test_budget_shared_across_live_cases_and_requires_consent(tmp_path, quiet_environment):
    with pytest.raises(ValueError):
        engine.PulseEngine(tmp_path, live_cloud=True)

    def execute(case, directory, live):
        return (
            {"status": "blocked", "reserved_tokens": 60000, "iterations": 19}
            if live
            else {"status": "passed"}
        )

    pulse = engine.PulseEngine(tmp_path, case_executor=execute, live_local=True)
    report = pulse.run()
    assert report["reserved_tokens"] == 60000 and report["remaining_tokens"] == 4000
    assert any(r.get("error_category") == "suite_budget_exhausted" for r in pulse.results)
    assert report["cloud_consent"] is False


def test_export_allowlists_seeded_secrets_paths_and_model_text(
    tmp_path, quiet_environment, monkeypatch
):
    secret = "sk-fake-seeded-private-value-12345"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    pulse = engine.PulseEngine(tmp_path, case_executor=lambda *a: {"status": "passed"})
    pulse.run()
    for filename in ["summary.json", "environment.json"]:
        data = load_json(pulse.directory / filename)
        data.update(
            exception=secret,
            model_response=secret,
            path="C:/Users/" + secret + "/Desktop/.env",
            raw_log="Authorization: Bearer " + secret,
        )
        if filename == "environment.json":
            data.update(system=secret, python=secret, configured_providers=[secret, "groq"])
        atomic_json(pulse.directory / filename, data)
    (pulse.directory / ".env").write_text(secret)
    (pulse.directory / "source.py").write_text(secret)
    pulse.stream.emit(component="worker", event_type="model_returned", raw_response=secret)
    output = tmp_path / "诊断 Δ.zip"
    included = export_zip(pulse.directory, output)
    with zipfile.ZipFile(output) as archive:
        combined = "\n".join(archive.read(name).decode() for name in archive.namelist())
        assert (
            secret not in combined
            and "C:/Users/" not in combined
            and "Authorization" not in combined
        )
        assert archive.testzip() is None
        inventory = json.loads(archive.read("artifacts-manifest.json"))
        assert inventory["source_or_model_text_included"] is False
        assert "generated source" in inventory["excluded"]
    assert len(included) == 14 and open_report(output)["summary"]["status"] == "passed"
    reduced = documents(
        pulse.directory, include_environment=False, include_events=False, include_metrics=False
    )
    assert json.loads(reduced["environment.json"]) == {"excluded": True}
    assert reduced["events.jsonl"] == ""


def test_unsafe_zip_and_materially_different_runs_not_comparable(tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("../summary.json", "{}")
    with pytest.raises(ValueError):
        open_report(path)
    first = {"summary": {"mode": "live", "counts": {}, "manifest_hash": "a"}, "environment": {}}
    second = {"summary": {"mode": "live", "counts": {}, "manifest_hash": "b"}, "environment": {}}
    result = engine.compare(first, second)
    assert not result["comparable"] and "manifest_hash" in result["differences"]


@pytest.mark.skipif(os.environ.get("AASS_INTEGRATION") != "1", reason="actual Docker suite")
def test_complete_default_suite_real_tools_no_model_calls_and_no_user_workspace_writes(
    tmp_path, quiet_environment
):
    user_project = tmp_path / "user-project"
    user_project.mkdir()
    (user_project / "unchanged.txt").write_text("unchanged")
    settings = tmp_path / ".aass/provider.json"
    settings.parent.mkdir()
    settings.write_text('{"service":"groq","model":"saved"}')
    pulse = engine.PulseEngine(tmp_path)
    report = pulse.run()
    assert report["status"] == "passed", pulse.results
    assert report["counts"]["passed"] == 8
    assert (user_project / "unchanged.txt").read_text() == "unchanged"
    assert settings.read_text() == '{"service":"groq","model":"saved"}'
    assert not any(e.get("event_type") == "model_requested" for e in read_events(pulse.stream.path))
    assert any(
        r["evidence"] == "negative_control_detected" and not r["acceptance_passed"]
        for r in pulse.results
    )
    events = read_events(pulse.stream.path)
    assert any(e.get("event_type") == "corrective_feedback" for e in events)
    assert any(
        e.get("test_id") == "rewrite-loop" and e.get("event_type") == "verification_checkpoint"
        for e in events
    )
    output = tmp_path / "report.zip"
    export_zip(pulse.directory, output)
    assert open_report(output)["summary"]["counts"]["passed"] == 8


@pytest.mark.skipif(
    os.environ.get("AASS_INTEGRATION") != "1", reason="original uploaded code in actual Docker"
)
def test_original_expense_tracker_is_a_failing_baseline(tmp_path):
    from sandboxes.container import ContainerSandbox

    fixtures = Path(__file__).parent / "fixtures/expense_1_3_2"
    for source, target in [
        ("implementation.txt", "expense_tracker.py"),
        ("tests.txt", "test_expense_tracker.py"),
        ("readme.txt", "README.md"),
    ]:
        (tmp_path / target).write_bytes((fixtures / source).read_bytes())
    result = ContainerSandbox(tmp_path).run(["python", "-m", "unittest", "discover", "-v"])
    assert result.returncode == 1
    assert "Ran 12 tests" in result.stderr
    assert "FAILED (failures=6, errors=3)" in result.stderr


def test_manifest_fixed_ids_and_explicit_scoring():
    spec = manifest()
    assert len(spec["cases"]) == 8 and len({r["id"] for r in spec["cases"]}) == 8
    assert "No composite score" in spec["rules"]
    assert all(row["timeout"] > 0 and row["expected"] for row in spec["cases"])


def test_benchmark_process_deadline_is_classified_and_partial_events_survive(
    tmp_path, quiet_environment, monkeypatch
):
    pulse = engine.PulseEngine(tmp_path)
    case = dict(manifest()["cases"][0])
    case["timeout"] = 0.1
    directory = pulse.directory / case["id"]
    directory.mkdir()
    EventStream(directory, directory.name).emit(
        component="supervisor", event_type="tool_started", action="test"
    )
    original = pulse.controller._execute

    def execute(command, **kwargs):
        return original([sys.executable, "-c", "import time; time.sleep(10)"], **kwargs)

    monkeypatch.setattr(pulse.controller, "_execute", execute)
    result = pulse._execute_case(case, directory, False)
    assert result["status"] == "timed_out"
    assert read_events(directory / "events.jsonl")[0]["event_type"] == "tool_started"


def test_sound_failure_is_nonfatal(monkeypatch):
    import sys
    from types import SimpleNamespace

    from pulse.view import notify_sound

    def unavailable(*args):
        raise RuntimeError("Audio unavailable")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winsound", SimpleNamespace(MessageBeep=unavailable, MB_OK=0))
    notify_sound()


@pytest.mark.skipif(
    os.environ.get("AASS_INTEGRATION") != "1", reason="owned Docker cleanup after killed benchmark"
)
def test_deadline_removes_only_owned_daemon_containers(tmp_path, quiet_environment, monkeypatch):
    import subprocess

    from pulse.events import digest
    from settings import subprocess_environment

    pulse = engine.PulseEngine(tmp_path)
    case = dict(manifest()["cases"][0])
    case["timeout"] = 2
    directory = pulse.directory / case["id"]
    directory.mkdir()
    workspace = directory / "workspace"
    workspace.mkdir()
    (workspace / "test_slow.py").write_text(
        "import unittest,time\nclass Slow(unittest.TestCase):\n def test_slow(self): time.sleep(20)\n"
    )
    label = digest(pulse.directory.resolve())[:32]
    original = pulse.controller._execute
    script = 'from sandboxes.container import ContainerSandbox; import sys; ContainerSandbox(sys.argv[1],owner_label=sys.argv[2]).run(["python","-m","unittest","discover"])'

    def execute(command, **kwargs):
        return original([sys.executable, "-c", script, str(workspace), label], **kwargs)

    monkeypatch.setattr(pulse.controller, "_execute", execute)
    assert pulse._execute_case(case, directory, False)["status"] == "timed_out"
    result = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "label=aass.pulse=" + label],
        capture_output=True,
        text=True,
        timeout=10,
        env=subprocess_environment(),
    )
    assert result.returncode == 0 and not result.stdout.strip()
