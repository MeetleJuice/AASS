"""Actual native Tk responsiveness/notification/cancellation on Windows CI."""

import sys
import time
from pathlib import Path

import pytest

from setup_controller import CommandResult
from telemetry import atomic_json


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows Tk view")
def test_native_pulse_view_remains_responsive_and_retains_cancelled_results(tmp_path, monkeypatch):
    import tkinter as tk

    from pulse.view import PulseView
    from setup_controller import SetupController
    from setup_wizard import SetupWizard

    notifications = []
    monkeypatch.setattr("pulse.view.notify_sound", lambda: notifications.append("sound"))

    class Controller(SetupController):
        def _runtime(self):
            return sys.executable

        def _execute(self, command, **kwargs):
            directory = Path(command[command.index("--directory") + 1])
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not (directory / "cancel").exists():
                time.sleep(0.01)
            atomic_json(
                directory / "summary.json",
                {
                    "status": "cancelled",
                    "counts": {"passed": 0, "failed": 0, "skipped": 8, "blocked": 0},
                },
            )
            atomic_json(directory / "benchmark-results.json", [])
            return CommandResult(0, "")

    window = tk.Tk()
    window.withdraw()
    owner = SetupWizard(window, root=tmp_path, controller=Controller(tmp_path), smoke=True)
    pulse = PulseView(owner, auto_start=False)
    owner.pulse_view = pulse
    pulse.start()
    pulses = []
    window.after(20, lambda: pulses.append("responsive"))
    window.after(80, pulse.cancel)
    deadline = time.monotonic() + 8
    while pulse.running and time.monotonic() < deadline:
        window.update()
        time.sleep(0.01)
    assert pulses == ["responsive"]
    assert not pulse.running and notifications == ["sound"]
    assert "cancelled" in pulse.status.get()
    assert (pulse.directory / "summary.json").is_file()
    pulse.close()
    window.after_cancel(owner.poll_id)
    window.destroy()
