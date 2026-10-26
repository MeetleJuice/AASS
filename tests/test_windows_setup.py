import io
import json
import os
import sys

import pytest

from install_aass import Installer, SetupProblem, installation_lock, sandbox_smoke


@pytest.fixture
def installer(tmp_path):
    instance = Installer(tmp_path, heartbeat=0.02)
    yield instance
    instance.log.close()


def test_installer_streams_child_output_and_redacts_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AASS_JUDGE_API_KEY", "private-fixture-key")
    instance = Installer(tmp_path, heartbeat=0.02)
    try:
        code, output = instance.run(
            "test child",
            [
                sys.executable,
                "-u",
                "-c",
                'import time; print("private-fixture-key"); time.sleep(.1)',
            ],
        )
        assert code == 0
        assert "[REDACTED]" in output
        assert "Still working:" in capsys.readouterr().out
        log = instance.log_path.read_text()
        assert "private-fixture-key" not in log
        assert "[REDACTED]" in log
    finally:
        instance.log.close()


def test_command_arguments_and_paths_with_spaces_are_preserved(installer):
    code, output = installer.run(
        "argv test",
        [
            sys.executable,
            "-c",
            "import sys; print(sys.argv[1])",
            "project with spaces & punctuation",
        ],
    )
    assert code == 0
    assert output.strip() == "project with spaces & punctuation"


def test_failure_cannot_be_reported_as_success(installer):
    with pytest.raises(SetupProblem, match="exit 7"):
        installer.run("failed stage", [sys.executable, "-c", "raise SystemExit(7)"])


def test_timeout_terminates_the_child_and_reports_stage(installer):
    with pytest.raises(SetupProblem, match="slow stage exceeded"):
        installer.run(
            "slow stage", [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.15
        )


def test_second_installation_cannot_own_workspace(tmp_path):
    lock = tmp_path / "setup.lock"
    with installation_lock(lock):
        with pytest.raises(SetupProblem, match="already running"):
            with installation_lock(lock):
                pytest.fail("second installer acquired the lock")
    with installation_lock(lock):
        pass


def prepare_flow(installer, monkeypatch, *, ready=True, live_fails=False, malformed=False):
    calls = []
    monkeypatch.setattr(installer, "docker", lambda: calls.append("docker"))
    monkeypatch.setattr(installer, "ollama", lambda: calls.append("ollama"))

    def run(label, command, **kwargs):
        calls.append(command)
        if command[-1] == "doctor":
            if malformed:
                return 2, "not json"
            return (0 if ready else 2), json.dumps(
                {
                    "ready": ready,
                    "checks": {
                        "judge_configuration": {"ready": ready},
                        "chromium": {"ready": True},
                        "ollama_worker": {"ready": True},
                        "docker": {"ready": True},
                        "sandbox_image": {"ready": True},
                    },
                }
            )
        if command[-1] == "verify-live" and live_fails:
            return 2, '{"stage":"cloud_judge","http_status":429}'
        return 0, ""

    monkeypatch.setattr(installer, "run", run)
    return calls


def test_installer_runs_all_gates_before_recording_ready(installer, monkeypatch):
    calls = prepare_flow(installer, monkeypatch)
    assert installer.install(skip_live=False) == 0
    assert calls[:2] == ["docker", "ollama"]
    assert any("--sandbox-smoke" in call for call in calls[2:])
    assert calls[-1][-1] == "verify-live"
    assert json.loads((installer.state / "setup-status.json").read_text())["status"] == "ready"


def test_missing_credentials_preserves_install_and_reports_configuration_needed(
    installer, monkeypatch
):
    calls = prepare_flow(installer, monkeypatch, ready=False)
    assert installer.install() == 0
    assert not any("verify-live" in call for call in calls[2:])
    report = json.loads((installer.state / "setup-status.json").read_text())
    assert report["status"] == "installed_needs_configuration"


def test_live_failure_and_skip_never_record_ready(installer, monkeypatch):
    prepare_flow(installer, monkeypatch, live_fails=True)
    assert installer.install(skip_live=False) == 0
    assert (
        json.loads((installer.state / "setup-status.json").read_text())["status"]
        == "installed_cloud_unverified"
    )
    assert json.loads((installer.state / "setup-status.json").read_text())["status"] != "ready"
    calls = prepare_flow(installer, monkeypatch)
    assert installer.install(skip_live=True) == 0
    assert not any("verify-live" in call for call in calls[2:])
    assert (
        json.loads((installer.state / "setup-status.json").read_text())["status"]
        == "installed_live_unverified"
    )


def test_malformed_readiness_does_not_approve(installer, monkeypatch):
    prepare_flow(installer, monkeypatch, malformed=True)
    with pytest.raises(SetupProblem, match="valid report"):
        installer.install()


def test_running_docker_and_cached_image_are_reused(installer, monkeypatch):
    commands = []
    monkeypatch.setattr(installer, "locate", lambda *args: "/trusted/docker")

    def run(label, command, **kwargs):
        commands.append(command)
        return (0, "linux\n") if "info" in command else (0, "{}")

    monkeypatch.setattr(installer, "run", run)
    installer.docker()
    assert not any("pull" in c for c in commands)
    assert not any("winget" in c for c in commands)


def test_existing_preferred_ollama_model_is_reused(installer, monkeypatch, capsys):
    monkeypatch.delenv("AASS_WORKER_MODEL", raising=False)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: io.BytesIO(
            b'{"models":[{"name":"qwen3:8b"},{"name":"qwen3.5:9b"}]}'
        ),
    )
    monkeypatch.setattr(installer, "locate", lambda *args: None)
    installer.ollama()
    assert "Selected local worker: qwen3.5:9b" in capsys.readouterr().out


@pytest.mark.skipif(os.environ.get("AASS_INTEGRATION") != "1", reason="set AASS_INTEGRATION=1")
def test_installer_sandbox_gate_runs_real_nonzero_test():
    assert sandbox_smoke() == 0
