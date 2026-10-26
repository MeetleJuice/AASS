from types import SimpleNamespace

import local_app


def runtime_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(local_app, "ROOT", tmp_path)
    runtime = (
        tmp_path
        / ".venv"
        / ("Scripts/python.exe" if local_app.sys.platform == "win32" else "bin/python")
    )
    runtime.parent.mkdir(parents=True)
    runtime.write_text("fixture")


def test_model_connection_failure_returns_to_menu_instead_of_exiting(tmp_path, monkeypatch):
    runtime_fixture(tmp_path, monkeypatch)
    answers = iter(["5", "", "6"])
    monkeypatch.setattr("builtins.input", lambda *args: next(answers))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(local_app.subprocess, "run", run)
    assert local_app.main() == 0
    assert calls[0][-1] == "verify-live"


def test_provider_choice_is_saved_without_requesting_a_key(tmp_path, monkeypatch):
    runtime_fixture(tmp_path, monkeypatch)
    answers = iter(["4", "gemini", "selected-model", "", "6"])
    monkeypatch.setattr("builtins.input", lambda *args: next(answers))
    saved = []
    monkeypatch.setattr("settings.save_provider_preferences", lambda *args: saved.append(args))
    assert local_app.main() == 0
    assert saved == [("gemini", "selected-model")]
