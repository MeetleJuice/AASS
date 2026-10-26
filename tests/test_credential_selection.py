import json
import os
from pathlib import Path

import pytest

import initialize_aass as bootstrap
import orchestration_canvas as cli
import settings
import setup_api

SECRET = "fixture-private-value-never-saved"


@pytest.fixture
def application(tmp_path, monkeypatch):
    root = tmp_path / "application"
    root.mkdir()
    monkeypatch.setattr(bootstrap, "__file__", str(root / "initialize_aass.py"))
    monkeypatch.setattr(settings, "__file__", str(root / "settings.py"))
    monkeypatch.setattr(setup_api, "__file__", str(root / "setup_api.py"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for name in settings.CREDENTIAL_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("AASS_JUDGE_SERVICE", raising=False)
    return root


def test_selection_persists_only_path_and_can_be_replaced(application, tmp_path):
    first, second = tmp_path / "private.env", tmp_path / "new.env.txt"
    first.write_text(f"GEMINI_API_KEY={SECRET}\n")
    second.write_text("GOOGLE_API_KEY=another-private-fixture\n")
    settings.save_credentials_file(first, application)
    binding = application / ".aass/credentials.json"
    assert json.loads(binding.read_text()) == {"path": str(first)}
    assert SECRET not in binding.read_text()
    assert settings.selected_credentials_file(application) == first
    settings.save_credentials_file(second, application)
    assert settings.selected_credentials_file(application) == second
    assert first.read_text() == f"GEMINI_API_KEY={SECRET}\n"


def test_explicit_selection_precedes_app_and_desktop_files(application, tmp_path):
    chosen = tmp_path / "chosen credentials.txt"
    chosen.write_text(f"GEMINI_API_KEY={SECRET}\n")
    (application / ".env").write_text("GEMINI_API_KEY=app-fallback\n")
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True)
    (desktop / ".env").write_text("GEMINI_API_KEY=desktop-fallback\n")
    settings.save_credentials_file(chosen, application)
    bootstrap.discover_api_keys(configure=False)
    assert os.environ["GEMINI_API_KEY"] == SECRET
    assert "AASS_JUDGE_API_KEY" not in os.environ


def test_existing_process_binding_precedes_selected_file(application, tmp_path, monkeypatch):
    chosen = tmp_path / "private.env"
    chosen.write_text(f"GEMINI_API_KEY={SECRET}\n")
    settings.save_credentials_file(chosen, application)
    monkeypatch.setenv("GEMINI_API_KEY", "explicit-process-binding")
    bootstrap.discover_api_keys(configure=False)
    assert os.environ["GEMINI_API_KEY"] == "explicit-process-binding"


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-16-be"])
def test_notepad_bom_encodings_are_supported(application, tmp_path, encoding):
    chosen = tmp_path / "notepad.env.txt"
    body = f"# private file\nGEMINI_API_KEY='{SECRET}'\nPATH=must-not-load\n"
    encoded = body.encode(encoding)
    if encoding == "utf-16-be":
        encoded = b"\xfe\xff" + encoded
    chosen.write_bytes(encoded)
    original_path = os.environ.get("PATH")
    settings.save_credentials_file(chosen, application)
    bootstrap.discover_api_keys(configure=False)
    assert os.environ["GEMINI_API_KEY"] == SECRET
    assert os.environ.get("PATH") == original_path


def test_deleted_explicit_file_is_visible_and_never_loads_fallback(application, tmp_path, capsys):
    chosen = tmp_path / "private.env"
    chosen.write_text(f"GEMINI_API_KEY={SECRET}\n")
    settings.save_credentials_file(chosen, application)
    chosen.unlink()
    (application / ".env").write_text("GEMINI_API_KEY=wrong-provider-fallback\n")
    with pytest.raises(ValueError, match="regular file"):
        bootstrap.discover_api_keys(configure=False)
    assert "GEMINI_API_KEY" not in os.environ
    assert setup_api.main(["credentials"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["code"] == "credentials_configuration"
    assert "Choose your credentials file again" in report["hint"]
    assert "GEMINI_API_KEY" not in os.environ
    assert SECRET not in json.dumps(report)


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "{}",
        '{"path":1}',
        '{"path":"relative.env"}',
        '{"path":"/absolute","key":"private"}',
    ],
)
def test_malformed_selection_requires_reselection(application, payload):
    folder = application / ".aass"
    folder.mkdir()
    (folder / "credentials.json").write_text(payload)
    with pytest.raises(ValueError):
        settings.selected_credentials_file(application)


def test_oversized_selection_and_credentials_are_rejected(application, tmp_path):
    folder = application / ".aass"
    folder.mkdir()
    (folder / "credentials.json").write_text(" " * 8193)
    with pytest.raises(ValueError, match="selection"):
        settings.selected_credentials_file(application)
    private = tmp_path / "too-large.env"
    private.write_bytes(b"#" * (64 * 1024 + 1))
    with pytest.raises(ValueError, match="64 KiB"):
        settings.save_credentials_file(private, application)
    with pytest.raises(ValueError, match="64 KiB"):
        bootstrap.load_credentials(private)


def _symlink(link, target):
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("This host does not permit symlink creation")


def test_symlink_selected_source_and_selection_binding_are_rejected(application, tmp_path):
    source = tmp_path / "private.env"
    source.write_text(f"GEMINI_API_KEY={SECRET}\n")
    link = tmp_path / "linked.env"
    _symlink(link, source)
    with pytest.raises(ValueError, match="regular"):
        settings.save_credentials_file(link, application)
    with pytest.raises(ValueError, match="regular"):
        bootstrap.load_credentials(link)
    folder = application / ".aass"
    folder.mkdir()
    source_binding = tmp_path / "selection.json"
    source_binding.write_text(json.dumps({"path": str(source)}))
    _symlink(folder / "credentials.json", source_binding)
    with pytest.raises(ValueError, match="selection"):
        settings.selected_credentials_file(application)


def test_bad_notepad_encoding_is_visible_for_selected_file(application, tmp_path, capsys):
    source = tmp_path / "private.env"
    source.write_bytes(b"GEMINI_API_KEY=\xff\xff")
    settings.save_credentials_file(source, application)
    assert setup_api.main(["credentials"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["code"] == "credentials_configuration"
    assert "GEMINI_API_KEY" not in os.environ


def test_corrupt_provider_preferences_leave_file_picker_and_model_repair_available(
    application, tmp_path, capsys
):
    source = tmp_path / "private.env"
    source.write_text(f"GEMINI_API_KEY={SECRET}\n")
    settings.save_credentials_file(source, application)
    (application / ".aass/provider.json").write_text("corrupt-secret-do-not-echo")
    assert setup_api.main(["credentials"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["preferences"] == {}
    assert report["settings_warning"]
    assert report["providers"][0]["key_present"] is True
    assert SECRET not in json.dumps(report)
    assert "corrupt-secret" not in json.dumps(report)
    settings.save_provider_preferences("gemini", "gemini-test", application)
    assert settings.provider_preferences(application) == {
        "service": "gemini",
        "model": "gemini-test",
    }


def test_doctor_runs_local_checks_when_credential_selection_is_stale(
    application, tmp_path, monkeypatch, capsys
):
    chosen = tmp_path / "missing.env"
    folder = application / ".aass"
    folder.mkdir()
    (folder / "credentials.json").write_text(json.dumps({"path": str(chosen)}))
    seen = []
    monkeypatch.setattr(cli, "configure_provider", lambda: None)

    def doctor(config_error):
        seen.append(config_error)
        return {
            "ready": False,
            "checks": {"docker": {"ready": True}, "judge_configuration": {"ready": False}},
        }

    monkeypatch.setattr(cli, "doctor", doctor)
    assert cli.main(["doctor"]) == 2
    assert seen == [True]
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["docker"]["ready"]


def test_fresh_bootstrap_still_generates_spec_with_stale_selection(
    application, monkeypatch, capsys
):
    folder = application / ".aass"
    folder.mkdir()
    (folder / "credentials.json").write_text(json.dumps({"path": str(application / "moved.env")}))
    monkeypatch.setattr("sys.argv", ["initialize_aass.py", "--root", str(application)])
    monkeypatch.setattr(bootstrap, "verify_ollama", lambda: ["qwen3.5:9b"])
    bootstrap.main()
    output = capsys.readouterr()
    assert (application / "generated/architecture_spec.json").is_file()
    assert json.loads(output.out)["ollama_reachable"]
    assert "Local bootstrap will continue" in output.err


def test_dangling_selection_link_is_not_silently_ignored(application, tmp_path):
    folder = application / ".aass"
    folder.mkdir()
    _symlink(folder / "credentials.json", tmp_path / "nonexistent.json")
    with pytest.raises(ValueError, match="selection"):
        settings.selected_credentials_file(application)


def test_bad_automatic_file_cannot_block_a_valid_explicit_selection(application, tmp_path):
    chosen = tmp_path / "chosen.env"
    chosen.write_text(f"GEMINI_API_KEY={SECRET}\n")
    settings.save_credentials_file(chosen, application)
    (application / ".env").write_bytes(b"GEMINI_API_KEY=\xff\xff")
    bootstrap.discover_api_keys(configure=False)
    assert os.environ["GEMINI_API_KEY"] == SECRET
