import subprocess
import sys

import pytest

from launch_aass import setup_step


def test_installer_inherits_output_and_reports_liveness(capfd):
    setup_step(
        "installer fixture",
        [
            sys.executable,
            "-u",
            "-c",
            'import time; print("child output", flush=True); time.sleep(0.1)',
        ],
        progress_interval=0.02,
    )
    output = capfd.readouterr().out
    assert "child output" in output
    assert "Still running: installer fixture" in output
    assert "Finished: installer fixture" in output


def test_failed_installer_preserves_exit_status_and_never_reports_finished(capfd):
    with pytest.raises(subprocess.CalledProcessError) as error:
        setup_step("failure fixture", [sys.executable, "-c", "raise SystemExit(7)"])
    assert error.value.returncode == 7
    assert "Finished:" not in capfd.readouterr().out


def test_setup_child_does_not_inherit_pip_tls_bypass_or_private_index(monkeypatch, capfd):
    monkeypatch.setenv("PIP_TRUSTED_HOST", "untrusted.example")
    monkeypatch.setenv("PIP_INDEX_URL", "https://private:credential@untrusted.example/simple")
    setup_step(
        "pip config boundary",
        [
            sys.executable,
            "-c",
            'import os; print("PIP_TRUSTED_HOST" in os.environ); print("PIP_INDEX_URL" in os.environ); print(os.environ["PIP_CONFIG_FILE"] == os.devnull)',
        ],
    )
    output = capfd.readouterr().out
    assert "False\nFalse\nTrue" in output.replace("\r\n", "\n")
    assert "credential" not in output
