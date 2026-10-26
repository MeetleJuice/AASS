import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from circuit_breaker import SafetyStop
from crdal_supervisor import CRDALSupervisor
from initialize_aass import configure_provider, discover_api_keys, load_credentials
from install_aass import Installer, SetupProblem
from judge_evaluator import JudgeEvaluator
from sandboxes.container import ContainerSandbox, snapshot
from settings import ollama_url, save_provider_preferences, subprocess_environment
from verify_release import prepare_update, verify


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://remote.example:11434",
        "http://user:pass@127.0.0.1:11434",
        "http://127.0.0.1/path",
    ],
)
def test_worker_endpoint_cannot_read_files_or_use_insecure_remote_host(url):
    with pytest.raises(ValueError):
        ollama_url(url)


def test_arbitrary_judge_host_is_rejected_before_key_is_sent(monkeypatch):
    monkeypatch.delenv("AASS_ALLOWED_JUDGE_HOSTS", raising=False)
    with pytest.raises(ValueError, match="not approved"):
        JudgeEvaluator("private-fixture", "model", "https://untrusted.example/v1")
    monkeypatch.setenv("AASS_ALLOWED_JUDGE_HOSTS", "trusted.example")
    assert (
        JudgeEvaluator("fixture", "model", "https://trusted.example/v1").base_url
        == "https://trusted.example/v1"
    )


def test_provider_adapter_must_match_official_api():
    with pytest.raises(ValueError, match="different providers"):
        JudgeEvaluator("fixture", "model", "https://api.openai.com/v1", provider="anthropic")


def test_credentials_file_cannot_enable_executables_or_add_api_destinations(tmp_path, monkeypatch):
    monkeypatch.delenv("AASS_CHROMIUM_EXECUTABLE", raising=False)
    old = os.environ.get("AASS_ALLOWED_JUDGE_HOSTS")
    file = tmp_path / "config.env"
    file.write_text("AASS_CHROMIUM_EXECUTABLE=bad.exe\nAASS_ALLOWED_JUDGE_HOSTS=evil.example\n")
    load_credentials(file)
    assert not os.environ.get("AASS_CHROMIUM_EXECUTABLE")
    assert os.environ.get("AASS_ALLOWED_JUDGE_HOSTS") == old


def test_unrelated_desktop_project_is_not_searched_for_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("AASS_POSTGRES_DSN", raising=False)
    project = tmp_path / "Desktop/UnrelatedProject"
    project.mkdir(parents=True)
    (project / ".env").write_text("AASS_POSTGRES_DSN=unrelated-private-value\n")
    discover_api_keys()
    assert "AASS_POSTGRES_DSN" not in os.environ


def clear_providers(monkeypatch):
    for name in [
        "AASS_JUDGE_API_KEY",
        "AASS_JUDGE_MODEL",
        "AASS_JUDGE_BASE_URL",
        "AASS_JUDGE_PROVIDER",
        "AASS_JUDGE_SERVICE",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_auto_discovery_rejects_conflicting_provider_and_endpoint(monkeypatch):
    clear_providers(monkeypatch)
    monkeypatch.setattr("initialize_aass.provider_preferences", lambda: {})
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-fixture")
    monkeypatch.setenv("AASS_JUDGE_BASE_URL", "https://api.openai.com/v1")
    with pytest.raises(ValueError, match="conflict"):
        configure_provider()
    assert "AASS_JUDGE_API_KEY" not in os.environ


def test_explicit_provider_selection_is_not_overridden_by_key_order(monkeypatch):
    clear_providers(monkeypatch)
    monkeypatch.setattr(
        "initialize_aass.provider_preferences",
        lambda: {"service": "gemini", "model": "chosen-model"},
    )
    monkeypatch.setenv("OPENAI_API_KEY", "openai-fixture")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-fixture")
    configure_provider()
    assert os.environ["AASS_JUDGE_API_KEY"] == "gemini-fixture"
    assert os.environ["AASS_JUDGE_MODEL"] == "chosen-model"
    assert "googleapis.com" in os.environ["AASS_JUDGE_BASE_URL"]


def test_provider_preferences_store_no_credentials(tmp_path):
    save_provider_preferences("gemini", "test-model", root=tmp_path)
    assert json.loads((tmp_path / ".aass/provider.json").read_text()) == {
        "service": "gemini",
        "model": "test-model",
    }


def test_installer_children_receive_no_model_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("AASS_JUDGE_API_KEY", "private-fixture")
    assert "AASS_JUDGE_API_KEY" not in subprocess_environment()
    installer = Installer(tmp_path)
    try:
        _, output = installer.run(
            "env check",
            [sys.executable, "-c", 'import os; print("AASS_JUDGE_API_KEY" in os.environ)'],
        )
        assert output.strip() == "False"
        _, output = installer.run(
            "authorized model client",
            [sys.executable, "-c", 'import os; print("AASS_JUDGE_API_KEY" in os.environ)'],
            credentials=True,
        )
        assert output.strip() == "True"
        with pytest.raises(SetupProblem, match="explicitly rerun"):
            installer.winget("Docker.DockerDesktop")
    finally:
        installer.log.close()


def test_atomic_worker_write_does_not_change_an_external_hardlink(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("original")
    (target / "inside.py").hardlink_to(outside)
    supervisor = CRDALSupervisor(target, None, None)
    supervisor.execute({"action": "write", "path": "inside.py", "content": "replacement"})
    assert outside.read_text() == "original"
    assert (target / "inside.py").read_text() == "replacement"


def test_worker_reads_and_snapshots_reject_hardlinks(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("private outside data")
    (target / "inside.py").hardlink_to(outside)
    with pytest.raises(SafetyStop, match="hard links"):
        CRDALSupervisor(target, None, None).execute({"action": "read", "path": "inside.py"})
    destination = tmp_path / "snapshot"
    snapshot(target, destination)
    assert not (destination / "inside.py").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO file type")
def test_worker_rejects_fifo_before_reading(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(SafetyStop, match="regular file"):
        CRDALSupervisor(tmp_path, None, None).execute({"action": "read", "path": "pipe"})


def test_image_option_injection_is_rejected(tmp_path):
    with pytest.raises(SafetyStop, match="image reference"):
        ContainerSandbox(tmp_path, image="--privileged")


def release_fixture(root):
    (root / "app.py").write_text('print("fixture")\n')
    manifest = {
        "format": 1,
        "version": "test",
        "files": {"app.py": hashlib.sha256((root / "app.py").read_bytes()).hexdigest()},
    }
    (root / "RELEASE-MANIFEST.json").write_text(json.dumps(manifest))


def test_release_tampering_and_unexpected_code_are_detected(tmp_path):
    release_fixture(tmp_path)
    assert verify(tmp_path)["version"] == "test"
    (tmp_path / "injected.py").write_text("unexpected")
    with pytest.raises(ValueError, match="Unexpected executable"):
        verify(tmp_path)
    (tmp_path / "injected.py").unlink()
    (tmp_path / "app.py").write_text("modified")
    with pytest.raises(ValueError, match="modified"):
        verify(tmp_path)


def test_unknown_legacy_helper_is_preserved_and_rejected(tmp_path):
    path = tmp_path / "Check-Connections.bat"
    path.write_text("user-modified helper")
    with pytest.raises(ValueError, match="unknown"):
        prepare_update(tmp_path)
    assert path.read_text() == "user-modified helper"


def test_packaged_release_is_deterministic_and_contains_no_nested_payloads(tmp_path):
    import zipfile

    from scripts.package import build

    first = build(allow_dirty=True)
    before = first.read_bytes()
    assert build(allow_dirty=True).read_bytes() == before
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert not any("/tests/" in n or "/.venv/" in n or "/downloads/" in n for n in names)
        assert not any(n.lower().endswith((".exe", ".dll", ".zip")) for n in names)
        assert any(n.endswith("/RELEASE-MANIFEST.json") for n in names)
        archive.extractall(tmp_path)
    release = next(tmp_path.iterdir())
    assert verify(release)["version"] == "1.1.0"


def test_directory_junction_policy_uses_windows_detection_when_available():
    from settings import is_link

    class Junction:
        def is_symlink(self):
            return False

        def is_junction(self):
            return True

    assert is_link(Junction())


def test_embedding_only_model_list_selects_a_generation_workhorse(monkeypatch):
    from initialize_aass import select_worker

    monkeypatch.delenv("AASS_WORKER_MODEL", raising=False)
    assert select_worker(["qwen3-embedding:0.6b"]) == "qwen3.5:9b"


def test_lock_closure_catches_windows_only_missing_dependencies():
    from scripts.lock_dependencies import validate_closure

    with pytest.raises(ValueError, match="Windows"):
        validate_closure({"parent": "1.0"}, {"parent": ['missing>=1; sys_platform == "win32"']})
    validate_closure(
        {"parent": "1.0", "child": "2.0"},
        {"parent": ['child>=2; sys_platform == "win32"'], "child": []},
    )


def test_auditor_does_not_skip_windows_marked_pins(tmp_path):
    from scripts.audit_dependencies import neutral_pins

    path = tmp_path / "requirements.lock"
    path.write_text('pywin32==312; sys_platform == "win32" \\\n --hash=sha256:fixture\n')
    assert neutral_pins(path) == ["pywin32==312"]
