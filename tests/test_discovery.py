import os
from pathlib import Path

from initialize_aass import discover_api_keys, select_worker


def clear_provider(monkeypatch):
    for name in (
        "ANTHROPIC_API_KEY",
        "AASS_JUDGE_PROVIDER",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "AASS_JUDGE_API_KEY",
        "AASS_JUDGE_BASE_URL",
        "AASS_JUDGE_MODEL",
        "AASS_WORKER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_automatic_desktop_dotenv_and_provider_mapping(tmp_path, monkeypatch):
    clear_provider(monkeypatch)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (desktop / ".env").write_text("GEMINI_API_KEY=fixture-not-a-real-key\nPATH=/bad\n")
    names = discover_api_keys()
    assert "AASS_JUDGE_API_KEY" in names
    assert os.environ["AASS_JUDGE_API_KEY"] == "fixture-not-a-real-key"
    assert (
        os.environ["AASS_JUDGE_BASE_URL"]
        == "https://generativelanguage.googleapis.com/v1beta/openai"
    )
    assert os.environ["PATH"] != "/bad"
    assert not (desktop / "generated").exists()


def test_onedrive_credentials_text_and_existing_binding_precedence(tmp_path, monkeypatch):
    clear_provider(monkeypatch)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("AASS_JUDGE_API_KEY", "existing-binding")
    folder = tmp_path / "OneDrive/Desktop/API Credentials"
    folder.mkdir(parents=True)
    (folder / "notepad.txt").write_text(
        "AASS_JUDGE_API_KEY=do-not-override\nAASS_JUDGE_MODEL=chosen\n"
    )
    discover_api_keys()
    assert os.environ["AASS_JUDGE_API_KEY"] == "existing-binding"
    assert os.environ["AASS_JUDGE_MODEL"] == "chosen"


def test_discovery_does_not_follow_desktop_symlinks(tmp_path, monkeypatch):
    clear_provider(monkeypatch)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "Desktop").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ".env").write_text("AASS_JUDGE_API_KEY=not-authorized")
    (tmp_path / "Desktop/link").symlink_to(outside, target_is_directory=True)
    discover_api_keys()
    assert not os.environ.get("AASS_JUDGE_API_KEY")


def test_worker_model_selection_honors_preference_and_explicit_override(monkeypatch):
    monkeypatch.delenv("AASS_WORKER_MODEL", raising=False)
    assert select_worker(["other", "qwen3.5:9b"]) == "qwen3.5:9b"
    assert select_worker(["other", "qwen3:8b"]) == "qwen3:8b"
    assert select_worker(["local-model"]) == "local-model"
    monkeypatch.setenv("AASS_WORKER_MODEL", "operator-choice")
    assert select_worker(["qwen3.5:9b"]) == "operator-choice"


def test_anthropic_desktop_key_is_mapped_to_independent_judge(tmp_path, monkeypatch):
    clear_provider(monkeypatch)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    folder = tmp_path / "Desktop/credentials"
    folder.mkdir(parents=True)
    (folder / "models.env").write_text("ANTHROPIC_API_KEY=fixture-anthropic\n")
    discover_api_keys()
    assert os.environ["AASS_JUDGE_API_KEY"] == "fixture-anthropic"
    assert os.environ["AASS_JUDGE_PROVIDER"] == "anthropic"
