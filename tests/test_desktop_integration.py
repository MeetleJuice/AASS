import contextlib
import json
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import desktop_integration as desktop


def write_icon(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    bitmap = struct.pack("<IIIHHIIIIII", 40, 1, 2, 1, 32, 0, 4, 0, 0, 0, 0)
    bitmap += b"\x88\x44\x22\xff" + b"\x00" * 4
    entry = struct.pack("<BBBBHHII", 1, 1, 0, 0, 1, 32, len(bitmap), 22)
    path.write_bytes(struct.pack("<HHH", 0, 1, 1) + entry + bitmap)


class FakeLink:
    def __init__(self, path, shell):
        self.path, self.shell = path, shell
        self.TargetPath = self.Arguments = self.IconLocation = self.WorkingDirectory = ""
        self.Description, self.WindowStyle = "", 1
        if path.is_file():
            for key, value in json.loads(path.read_text(encoding="utf-8")).items():
                setattr(self, key, value)

    def Save(self):
        if self.shell.fail_save:
            raise RuntimeError("PRIVATE_FIXTURE_MUST_NOT_APPEAR")
        self.path.write_text(
            json.dumps(
                {
                    key: getattr(self, key)
                    for key in (
                        "TargetPath",
                        "Arguments",
                        "IconLocation",
                        "WorkingDirectory",
                        "Description",
                        "WindowStyle",
                    )
                }
            ),
            encoding="utf-8",
        )


class FakeShell:
    fail_save = False

    def CreateShortcut(self, path):
        return FakeLink(Path(path), self)


@pytest.fixture
def application(tmp_path, monkeypatch):
    root = tmp_path / "AASS O'Brien & Δ (release)"
    root.mkdir()
    (root / "Start-AASS.bat").write_text("@echo off\n")
    write_icon(root / "assets/aass.ico")
    target_desktop = tmp_path / "OneDrive/Desktop"
    shell = FakeShell()
    monkeypatch.setattr(desktop, "_windows", lambda: True)
    monkeypatch.setattr(desktop, "desktop_directory", lambda: target_desktop)

    @contextlib.contextmanager
    def fake_shell():
        yield shell

    monkeypatch.setattr(desktop, "_shortcut_shell", fake_shell)
    return root, target_desktop, shell


def test_creates_custom_icon_shortcut_with_literal_unicode_paths(application):
    root, target_desktop, _ = application
    link_path = desktop.create_shortcut(root)
    assert link_path == target_desktop / "AASS.lnk"
    link = json.loads(link_path.read_text(encoding="utf-8"))
    assert link == {
        "TargetPath": str(root / "Start-AASS.bat"),
        "Arguments": "",
        "WorkingDirectory": str(root),
        "IconLocation": str(root / "assets/aass.ico") + ",0",
        "Description": desktop.SHORTCUT_DESCRIPTION,
        "WindowStyle": 1,
    }
    assert not list(target_desktop.glob(".aass-shortcut-*"))


def test_managed_python_launcher_uses_base_pythonw_and_quoted_arguments(application, monkeypatch):
    root, target_desktop, _ = application
    launcher = root / "desktop_launcher.py"
    launcher.write_text("pass\n")
    pythonw = root.parent / "Python with spaces/pythonw.exe"
    pythonw.parent.mkdir()
    pythonw.touch()
    monkeypatch.setattr(desktop, "_pythonw", lambda: pythonw)
    link = desktop.create_shortcut(root)
    metadata = json.loads(link.read_text(encoding="utf-8"))
    assert metadata["TargetPath"] == str(pythonw)
    assert metadata["Arguments"] == subprocess.list2cmdline([str(launcher), "--root", str(root)])
    assert metadata["WorkingDirectory"] == str(root)
    assert link == target_desktop / "AASS.lnk"


def test_repeat_creation_repairs_only_its_own_shortcut(application):
    root, target_desktop, _ = application
    first = desktop.create_shortcut(root)
    metadata = json.loads(first.read_text(encoding="utf-8"))
    metadata["IconLocation"] = "old icon"
    first.write_text(json.dumps(metadata), encoding="utf-8")
    second = desktop.create_shortcut(root)
    assert second == first == target_desktop / "AASS.lnk"
    assert (
        json.loads(second.read_text(encoding="utf-8"))["IconLocation"]
        == str(root / "assets/aass.ico") + ",0"
    )
    assert not list(target_desktop.glob(".aass-shortcut-*"))


def test_unrelated_existing_shortcut_is_preserved(application):
    root, target_desktop, shell = application
    target_desktop.mkdir(parents=True)
    link = shell.CreateShortcut(str(target_desktop / "AASS.lnk"))
    link.TargetPath = str(root.parent / "Other application.exe")
    link.Save()
    before = link.path.read_bytes()
    with pytest.raises(desktop.ShortcutError, match="another location"):
        desktop.create_shortcut(root)
    assert before == link.path.read_bytes()


def test_linked_destination_is_never_followed_or_replaced(application, tmp_path):
    root, target_desktop, _ = application
    target_desktop.mkdir(parents=True)
    unrelated = tmp_path / "unrelated file"
    unrelated.write_text("keep this private document")
    destination = target_desktop / "AASS.lnk"
    try:
        destination.symlink_to(unrelated)
    except (OSError, NotImplementedError):
        pytest.skip("This Windows account does not permit symlink creation")
    with pytest.raises(desktop.ShortcutError, match="existing AASS desktop link"):
        desktop.create_shortcut(root)
    assert destination.is_symlink()
    assert unrelated.read_text() == "keep this private document"


def test_shared_pythonw_target_does_not_allow_replacing_another_apps_shortcut(
    application, monkeypatch
):
    root, target_desktop, shell = application
    launcher = root / "desktop_launcher.py"
    launcher.touch()
    pythonw = root / "pythonw.exe"
    pythonw.touch()
    monkeypatch.setattr(desktop, "_pythonw", lambda: pythonw)
    target_desktop.mkdir(parents=True)
    link = shell.CreateShortcut(str(target_desktop / "AASS.lnk"))
    link.TargetPath = str(pythonw)
    link.Arguments = str(root / "unrelated.py")
    link.Save()
    before = link.path.read_bytes()
    with pytest.raises(desktop.ShortcutError, match="another location"):
        desktop.create_shortcut(root)
    assert before == link.path.read_bytes()


def test_failed_creation_preserves_previous_link_and_cleans_temporary_file(application):
    root, target_desktop, shell = application
    link = desktop.create_shortcut(root)
    before = link.read_bytes()
    shell.fail_save = True
    with pytest.raises(desktop.ShortcutError) as caught:
        desktop.create_shortcut(root)
    assert "PRIVATE_FIXTURE" not in str(caught.value)
    assert link.read_bytes() == before
    assert not list(target_desktop.glob(".aass-shortcut-*"))


@pytest.mark.parametrize("missing", ["launcher", "icon"])
def test_incomplete_release_never_creates_shortcut(application, missing):
    root, target_desktop, _ = application
    (root / ("Start-AASS.bat" if missing == "launcher" else "assets/aass.ico")).unlink()
    with pytest.raises(desktop.ShortcutError, match="missing"):
        desktop.create_shortcut(root)
    assert not (target_desktop / "AASS.lnk").exists()


@pytest.mark.parametrize(
    "content", [b"", b"not an icon", b"\x00\x00\x01\x00\x00\x00", b"X" * (1024 * 1024 + 1)]
)
def test_invalid_icon_is_reported_before_desktop_is_modified(application, content):
    root, target_desktop, _ = application
    (root / "assets/aass.ico").write_bytes(content)
    with pytest.raises(desktop.ShortcutError, match="icon"):
        desktop.create_shortcut(root)
    assert not target_desktop.exists()


def test_known_folder_redirection_is_preferred_to_home_desktop(tmp_path, monkeypatch):
    actual = tmp_path / "OneDrive business/Desktop"
    monkeypatch.setattr(desktop, "_windows", lambda: True)
    monkeypatch.setattr(desktop, "_known_desktop", lambda: actual)
    monkeypatch.setattr(desktop, "_registry_desktop", lambda: pytest.fail("unexpected fallback"))
    assert desktop.desktop_directory() == actual


def test_known_folder_failure_uses_registry_redirection_without_guessing(tmp_path, monkeypatch):
    actual = tmp_path / "Custom redirected desktop"
    monkeypatch.setattr(desktop, "_windows", lambda: True)
    monkeypatch.setattr(
        desktop, "_known_desktop", lambda: (_ for _ in ()).throw(OSError("private"))
    )
    monkeypatch.setattr(desktop, "_registry_desktop", lambda: actual)
    assert desktop.desktop_directory() == actual


def test_unresolvable_desktop_has_safe_recoverable_error(monkeypatch):
    monkeypatch.setattr(desktop, "_windows", lambda: True)
    for function in ("_known_desktop", "_registry_desktop"):
        monkeypatch.setattr(desktop, function, lambda: (_ for _ in ()).throw(OSError("private")))
    with pytest.raises(desktop.ShortcutError) as caught:
        desktop.desktop_directory()
    assert "Start-AASS.bat" in str(caught.value)
    assert "private" not in str(caught.value)


def test_stdlib_installer_delegates_to_hash_installed_runtime_without_credentials(
    application, monkeypatch
):
    root, target_desktop, _ = application
    runtime = root / ".venv/Scripts/python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.touch()
    calls = []

    @contextlib.contextmanager
    def missing_com():
        raise ImportError("no win32com")
        yield

    def run(command, **kwargs):
        calls.append((command, kwargs))
        target_desktop.mkdir(parents=True, exist_ok=True)
        shortcut = target_desktop / "AASS.lnk"
        shortcut.write_bytes(b"fixture created link")
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({"status": "ok", "shortcut": str(shortcut)})
        )

    monkeypatch.setenv("AASS_JUDGE_API_KEY", "PRIVATE_TEST_KEY")
    monkeypatch.setattr(desktop, "_shortcut_shell", missing_com)
    monkeypatch.setattr(desktop.subprocess, "run", run)
    result = desktop.create_shortcut(root)
    command, kwargs = calls[0]
    assert result == target_desktop / "AASS.lnk"
    assert command[0] == str(runtime)
    assert command[command.index("--root") + 1] == str(root)
    assert command[command.index("--desktop") + 1] == str(target_desktop)
    assert "--no-delegate" in command
    assert "AASS_JUDGE_API_KEY" not in kwargs["env"]
    assert "PRIVATE_TEST_KEY" not in json.dumps(command)
    assert kwargs["timeout"] == 30
    assert not kwargs.get("shell")


def test_cli_prints_only_safe_failure_and_preserves_unrelated_shortcut(application, capsys):
    root, target_desktop, shell = application
    target_desktop.mkdir(parents=True)
    link = shell.CreateShortcut(str(target_desktop / "AASS.lnk"))
    link.TargetPath = "another application.exe"
    link.Save()
    before = link.path.read_bytes()
    assert desktop.main(["--root", str(root), "--desktop", str(target_desktop)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["code"] == "desktop_shortcut_failed"
    assert link.path.read_bytes() == before


@pytest.mark.skipif(sys.platform != "win32", reason="Actual Windows COM shortcut integration")
def test_real_windows_custom_shortcut_is_valid_and_repeatable(tmp_path):
    root = tmp_path / "AASS O'Brien & Δ (release)"
    root.mkdir()
    launcher = root / "desktop_launcher.py"
    launcher.write_text("# Test launcher, never executed\n", encoding="utf-8")
    write_icon(root / "assets/aass.ico")
    fake_desktop = tmp_path / "test-only-desktop"
    link = desktop.create_shortcut(root, desktop=fake_desktop)
    with desktop._shortcut_shell() as shell:
        metadata = shell.CreateShortcut(str(link))
        assert desktop._matching_target(metadata.TargetPath, str(desktop._pythonw()))
        assert metadata.Arguments == subprocess.list2cmdline([str(launcher), "--root", str(root)])
        assert desktop._matching_target(metadata.WorkingDirectory, str(root))
        assert metadata.IconLocation == str(root / "assets/aass.ico") + ",0"
    assert desktop.create_shortcut(root, desktop=fake_desktop) == link
    assert link.parent == fake_desktop
    assert not list(fake_desktop.glob(".aass-shortcut-*"))
