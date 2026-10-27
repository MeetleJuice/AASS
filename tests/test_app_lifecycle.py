"""Install/update recovery tests use real manifests and filesystem transactions."""

import hashlib
import json
import os
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import app_lifecycle as lifecycle
import desktop_bootstrap as bootstrap
import desktop_launcher as launcher
import update_manager as updates
from settings import provider_preferences, selected_credentials_file
from verify_release import verify

SECRET = "private-fixture-value-must-not-be-copied"
OLD_REVISION = "a" * 40
NEW_REVISION = "b" * 40


def release(root, version="1.3.0", revision=OLD_REVISION, *, extra=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    files = {
        "app.py": f"APP_VERSION = {version!r}\n".encode(),
        "setup_wizard.py": b"# reviewed GUI fixture\n",
        "pyproject.toml": f'[project]\nversion="{version}"\n'.encode(),
        "requirements.lock": b"fixture==1\n",
    }
    files.update(extra or {})
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = {
        "format": 1,
        "version": version,
        "source_revision": revision,
        "dirty": False,
        "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
    }
    (root / "RELEASE-MANIFEST.json").write_text(json.dumps(manifest))
    verify(root)
    return root


def json_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def read_json(path):
    return json.loads(path.read_text())


@pytest.fixture
def managed(tmp_path):
    source = release(tmp_path / "original ZIP")
    target = tmp_path / "permanent application"
    lifecycle.install_source(source, target)
    return SimpleNamespace(source=source, root=target, directory=tmp_path)


def new_release(managed, *, version="1.3.1", revision=NEW_REVISION, extra=None):
    return release(managed.directory / ("release " + version), version, revision, extra=extra)


def runtime_fixture(root):
    runtime = root / ".venv"
    (runtime / "Lib/site-packages").mkdir(parents=True)
    (runtime / "Lib/site-packages/reviewed-library.pyd").write_bytes(b"original library bytes")
    (runtime / ".aass-dependencies").write_text("old verified marker")
    return runtime


def test_fresh_install_uses_permanent_root_and_binds_original_private_file_without_copy(tmp_path):
    source = release(tmp_path / "new Desktop ZIP")
    private = source / ".env.txt"
    private.write_text(f"GEMINI_API_KEY={SECRET}\n")
    target = tmp_path / "local application"
    assert lifecycle.install_source(source, target) == target
    assert verify(target)["source_revision"] == OLD_REVISION
    assert selected_credentials_file(target) == private
    assert not (target / ".env.txt").exists()
    assert SECRET not in (target / ".aass/credentials.json").read_text()
    marker = read_json(target / ".aass/managed-install.json")
    assert marker["root"] == str(target.resolve())
    assert marker["application"] == "AASS"


def test_existing_selected_file_and_provider_are_preserved_by_fresh_managed_install(tmp_path):
    source = release(tmp_path / "ZIP")
    private = tmp_path / "private original.env"
    private.write_text(f"GEMINI_API_KEY={SECRET}\n")
    json_write(source / ".aass/credentials.json", {"path": str(private)})
    json_write(source / ".aass/provider.json", {"service": "gemini", "model": "chosen-model"})
    target = tmp_path / "managed"
    lifecycle.install_source(source, target)
    assert selected_credentials_file(target) == private
    assert provider_preferences(target) == {"service": "gemini", "model": "chosen-model"}
    assert SECRET not in repr(list((target / ".aass").iterdir()))
    assert SECRET not in (target / ".aass/credentials.json").read_text()


def test_repeat_same_install_preserves_private_choices_and_runtime(managed):
    private = managed.directory / "private chosen.env"
    private.write_text(f"GEMINI_API_KEY={SECRET}\n")
    json_write(managed.root / ".aass/credentials.json", {"path": str(private)})
    json_write(
        managed.root / ".aass/provider.json", {"service": "gemini", "model": "operator-choice"}
    )
    runtime = runtime_fixture(managed.root)
    lifecycle.install_source(managed.source, managed.root)
    assert selected_credentials_file(managed.root) == private
    assert provider_preferences(managed.root)["model"] == "operator-choice"
    assert (
        runtime / "Lib/site-packages/reviewed-library.pyd"
    ).read_bytes() == b"original library bytes"


def test_install_rejects_an_unrelated_existing_folder_without_overwriting_it(tmp_path):
    source = release(tmp_path / "ZIP")
    target = tmp_path / "unrelated folder"
    target.mkdir()
    original = target / "notes.txt"
    original.write_text("keep my notes")
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.install_source(source, target)
    assert original.read_text() == "keep my notes"
    assert not (target / "app.py").exists()


def test_successful_update_changes_all_managed_source_and_preserves_private_state(managed):
    incoming = new_release(managed, extra={"tools/new_module.py": b"# new managed tool\n"})
    private = managed.directory / "private.env"
    private.write_text(f"GEMINI_API_KEY={SECRET}\n")
    json_write(managed.root / ".aass/credentials.json", {"path": str(private)})
    json_write(managed.root / ".aass/provider.json", {"service": "gemini", "model": "chosen"})
    (managed.root / "personal notes.txt").write_text("keep")
    seen = []
    result = lifecycle.apply_transaction(
        managed.root, incoming, checks=lambda root, callback: seen.append(verify(root)["version"])
    )
    assert result["version"] == "1.3.1"
    assert seen == ["1.3.1"]
    assert verify(managed.root)["source_revision"] == NEW_REVISION
    assert (managed.root / "personal notes.txt").read_text() == "keep"
    assert selected_credentials_file(managed.root) == private
    assert provider_preferences(managed.root)["model"] == "chosen"
    assert read_json(managed.root / ".aass/update-status.json")["status"] == "updated"
    assert read_json(managed.root / ".aass/managed-install.json")["version"] == "1.3.1"


def test_removed_managed_files_are_retired_but_unmanaged_files_survive(tmp_path):
    old = release(tmp_path / "old", extra={"obsolete.py": b"# retired\n"})
    target = tmp_path / "app"
    lifecycle.install_source(old, target)
    (target / "my data.txt").write_text("operator data")
    incoming = release(tmp_path / "new", "1.3.1", NEW_REVISION)
    lifecycle.apply_transaction(target, incoming, checks=lambda *_args: None)
    assert not (target / "obsolete.py").exists()
    assert (target / "my data.txt").read_text() == "operator data"
    verify(target)


def test_failed_update_restores_source_and_the_entire_previous_runtime(managed):
    incoming = new_release(managed, extra={"new_module.py": b"# remove on rollback\n"})
    runtime = runtime_fixture(managed.root)
    state = managed.root / ".aass/provider.json"
    json_write(state, {"service": "gemini", "model": "keep-choice"})

    def fail(root, callback):
        assert verify(root)["version"] == "1.3.1"
        (runtime / "Lib/site-packages/reviewed-library.pyd").write_bytes(b"partially replaced DLL")
        (runtime / "Lib/site-packages/uncommitted.pyd").write_bytes(b"partial new dependency")
        (runtime / ".aass-dependencies").unlink()
        raise RuntimeError("untrusted failure detail")

    with pytest.raises(lifecycle.LifecycleError) as error:
        lifecycle.apply_transaction(managed.root, incoming, checks=fail)
    assert error.value.code == "update_rolled_back"
    assert "untrusted failure detail" not in str(error.value)
    assert verify(managed.root)["version"] == "1.3.0"
    assert not (managed.root / "new_module.py").exists()
    assert (
        runtime / "Lib/site-packages/reviewed-library.pyd"
    ).read_bytes() == b"original library bytes"
    assert (runtime / ".aass-dependencies").read_text() == "old verified marker"
    assert not (runtime / "Lib/site-packages/uncommitted.pyd").exists()
    assert read_json(state)["model"] == "keep-choice"
    assert read_json(managed.root / ".aass/update-status.json")["status"] == "rolled_back"
    assert read_json(managed.root / ".aass/managed-install.json")["source_revision"] == OLD_REVISION


def test_failed_first_runtime_creation_restores_absent_runtime(managed):
    incoming = new_release(managed)

    def fail(root, callback):
        (root / ".venv").mkdir()
        (root / ".venv/partial wheel").write_text("incomplete")
        raise OSError("failed install")

    with pytest.raises(lifecycle.LifecycleError, match="previous app and runtime were restored"):
        lifecycle.apply_transaction(managed.root, incoming, checks=fail)
    assert not (managed.root / ".venv").exists()
    assert verify(managed.root)["version"] == "1.3.0"


def test_runtime_backup_preserves_internal_symlinks_without_relocating_them(managed):
    runtime = runtime_fixture(managed.root)
    target = runtime / "Lib/site-packages/reviewed-library.pyd"
    link = runtime / "library-link"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("This host does not permit symlink creation")
    incoming = new_release(managed)

    def fail(root, callback):
        link.unlink()
        target.write_bytes(b"new damaged file")
        raise RuntimeError("rollback fixture")

    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.apply_transaction(managed.root, incoming, checks=fail)
    assert link.is_symlink()
    assert link.resolve() == target
    assert link.read_bytes() == b"original library bytes"


def test_update_rejects_older_release_before_mutating_source_or_runtime(managed):
    old = new_release(managed, version="1.2.9")
    with pytest.raises(lifecycle.LifecycleError) as error:
        lifecycle.apply_transaction(
            managed.root, old, checks=lambda *_args: pytest.fail("old release reached checks")
        )
    assert error.value.code == "older_release"
    assert verify(managed.root)["source_revision"] == OLD_REVISION
    assert not (managed.root / ".aass/update-transaction.json").exists()


def test_crash_journal_restores_partial_source_and_runtime_on_next_launch(managed):
    runtime = runtime_fixture(managed.root)
    backup = managed.root / ".aass/update-backups" / ("c" * 32)
    shutil.copytree(managed.source, backup / "source")
    shutil.copytree(runtime, backup / "runtime", symlinks=True)
    json_write(
        managed.root / ".aass/update-transaction.json",
        {
            "format": 1,
            "phase": "verifying",
            "backup": str(backup),
            "new_files": ["new_module.py"],
            "runtime_existed": True,
        },
    )
    (managed.root / "app.py").write_text("partial unverified source")
    (managed.root / "new_module.py").write_text("partial extra module")
    (runtime / "Lib/site-packages/reviewed-library.pyd").write_bytes(b"partial failed wheel")
    assert lifecycle.recover_pending(managed.root)
    assert verify(managed.root)["version"] == "1.3.0"
    assert not (managed.root / "new_module.py").exists()
    assert (
        runtime / "Lib/site-packages/reviewed-library.pyd"
    ).read_bytes() == b"original library bytes"
    assert not lifecycle.recover_pending(managed.root)


def test_committed_journal_does_not_revert_a_successful_update(managed):
    incoming = new_release(managed)
    lifecycle.apply_transaction(managed.root, incoming, checks=lambda *_args: None)
    assert not lifecycle.recover_pending(managed.root)
    assert verify(managed.root)["version"] == "1.3.1"


def release_metadata(version="1.3.1", revision=NEW_REVISION):
    return updates.Release(f"v{version}-{revision[:7]}", version, f"AASS-{version}.zip", {})


def test_prepare_current_release_never_downloads_or_touches_source(managed, monkeypatch):
    monkeypatch.setattr(
        updates, "discover_release", lambda: release_metadata("1.3.0", OLD_REVISION)
    )
    monkeypatch.setattr(
        updates,
        "download_release",
        lambda *_args, **_kwargs: pytest.fail("already current downloaded"),
    )
    result = lifecycle.prepare_update(managed.root)
    assert result == {"status": "ok", "changed": False, "version": "1.3.0"}
    assert verify(managed.root)["source_revision"] == OLD_REVISION


def test_prepare_offline_failure_preserves_installed_source_and_private_file(managed, monkeypatch):
    private = managed.root / ".env"
    private.write_text(f"GEMINI_API_KEY={SECRET}\n")

    def offline():
        raise updates.UpdateError(
            "connection_failed", "GitHub could not be reached. Retry Update later."
        )

    monkeypatch.setattr(updates, "discover_release", offline)
    with pytest.raises(lifecycle.LifecycleError) as error:
        lifecycle.prepare_update(managed.root)
    assert error.value.code == "connection_failed"
    assert verify(managed.root)["source_revision"] == OLD_REVISION
    assert private.read_text() == f"GEMINI_API_KEY={SECRET}\n"
    assert not (managed.root / ".aass/update-transaction.json").exists()


def test_prepare_rejects_older_release_without_downloading(managed, monkeypatch):
    monkeypatch.setattr(updates, "discover_release", lambda: release_metadata("1.2.9"))
    monkeypatch.setattr(
        updates,
        "download_release",
        lambda *_args, **_kwargs: pytest.fail("older release downloaded"),
    )
    with pytest.raises(lifecycle.LifecycleError) as error:
        lifecycle.prepare_update(managed.root)
    assert error.value.code == "older_release"


def test_prepare_verified_release_writes_bound_plan_without_changing_live_files(
    managed, monkeypatch
):
    incoming = release(
        managed.root / ".aass/update-downloads/reviewed/source/AASS-1.3.1", "1.3.1", NEW_REVISION
    )
    metadata = release_metadata()
    monkeypatch.setattr(updates, "discover_release", lambda: metadata)
    monkeypatch.setattr(
        updates,
        "download_release",
        lambda *_args, **_kwargs: updates.VerifiedRelease(
            incoming, verify(incoming), metadata, "d" * 64
        ),
    )
    result = lifecycle.prepare_update(managed.root)
    assert result["changed"]
    assert result["version"] == "1.3.1"
    assert read_json(Path(result["plan_file"])) == result
    assert verify(managed.root)["version"] == "1.3.0"
    stage, manifest = lifecycle._validated_plan(managed.root, result)
    assert stage == incoming
    assert manifest["source_revision"] == NEW_REVISION


def test_cancel_before_download_preserves_existing_installation(managed, monkeypatch):
    event = threading.Event()
    event.set()
    monkeypatch.setattr(
        updates, "discover_release", lambda: pytest.fail("cancelled operation reached network")
    )
    with pytest.raises(lifecycle.LifecycleError) as error:
        lifecycle.prepare_update(managed.root, cancel_event=event)
    assert error.value.code == "cancelled"
    assert verify(managed.root)["version"] == "1.3.0"


def test_running_gui_prevents_a_second_window_and_source_update(managed):
    incoming = new_release(managed)
    with lifecycle.application_lock(managed.root):
        with pytest.raises(lifecycle.LifecycleError) as error:
            with lifecycle.application_lock(managed.root):
                pytest.fail("second GUI acquired installation")
        assert error.value.code == "already_running"
        with pytest.raises(lifecycle.LifecycleError) as error:
            lifecycle.apply_transaction(managed.root, incoming, checks=lambda *_args: None)
        assert error.value.code == "already_running"
    assert verify(managed.root)["version"] == "1.3.0"
    assert not (managed.root / ".aass/update-transaction.json").exists()


def test_existing_installation_lock_prevents_source_mutation(managed):
    incoming = new_release(managed)
    with lifecycle._update_lock(managed.root):
        with pytest.raises(lifecycle.LifecycleError) as error:
            lifecycle.apply_transaction(managed.root, incoming, checks=lambda *_args: None)
    assert error.value.code == "setup_running"
    assert verify(managed.root)["version"] == "1.3.0"


def test_github_code_zip_downloads_verified_release_before_managed_install(tmp_path, monkeypatch):
    source = tmp_path / "AASS-main"
    source.mkdir()
    (source / "pyproject.toml").write_text('[project]\nversion="1.3.0"\n')
    private = source / ".env.txt"
    private.write_text(f"GEMINI_API_KEY={SECRET}\n")
    incoming = release(tmp_path / "verified downloaded release")
    metadata = release_metadata("1.3.0", OLD_REVISION)
    monkeypatch.setattr(bootstrap, "discover_release", lambda: metadata)
    monkeypatch.setattr(
        bootstrap,
        "download_release",
        lambda *_args, **_kwargs: updates.VerifiedRelease(
            incoming, verify(incoming), metadata, "d" * 64
        ),
    )
    target = tmp_path / "managed"
    result = bootstrap.bootstrap(source, target, launch=False, callback=lambda *_args: None)
    assert result == target
    assert verify(target)["source_revision"] == OLD_REVISION
    assert selected_credentials_file(target) == private
    assert not (target / ".env.txt").exists()
    assert SECRET not in (target / ".aass/credentials.json").read_text()


def test_code_zip_refuses_offline_install_instead_of_certifying_raw_main(tmp_path):
    source = tmp_path / "AASS-main"
    source.mkdir()
    (source / "pyproject.toml").write_text('[project]\nversion="1.3.0"\n')
    target = tmp_path / "managed"
    with pytest.raises(lifecycle.LifecycleError) as error:
        bootstrap.bootstrap(
            source, target, offline=True, launch=False, callback=lambda *_args: None
        )
    assert error.value.code == "offline_source"
    assert not target.exists()


def test_unpublished_newer_code_zip_does_not_install_an_older_release(tmp_path, monkeypatch):
    source = tmp_path / "AASS-main"
    source.mkdir()
    (source / "pyproject.toml").write_text('[project]\nversion="1.3.1"\n')
    monkeypatch.setattr(
        bootstrap, "discover_release", lambda: release_metadata("1.3.0", OLD_REVISION)
    )
    monkeypatch.setattr(
        bootstrap,
        "download_release",
        lambda *_args, **_kwargs: pytest.fail("older bootstrap downloaded"),
    )
    target = tmp_path / "managed"
    with pytest.raises(lifecycle.LifecycleError) as error:
        bootstrap.bootstrap(source, target, launch=False, callback=lambda *_args: None)
    assert error.value.code == "release_pending"
    assert not target.exists()


def test_verified_local_zip_can_install_offline_and_preserve_selected_model(tmp_path, monkeypatch):
    source = release(tmp_path / "downloaded ZIP")
    json_write(source / ".aass/provider.json", {"service": "gemini", "model": "chosen"})
    monkeypatch.setattr(
        bootstrap, "discover_release", lambda: pytest.fail("offline bootstrap reached network")
    )
    target = tmp_path / "managed"
    bootstrap.bootstrap(source, target, offline=True, launch=False, callback=lambda *_args: None)
    assert provider_preferences(target)["model"] == "chosen"
    verify(target)


def test_desktop_launcher_uses_stable_runtime_and_current_source(managed, monkeypatch):
    runtime = managed.root / ".venv" / ("Scripts/pythonw.exe" if os.name == "nt" else "bin/python")
    runtime.parent.mkdir(parents=True)
    runtime.touch()
    (managed.root / ".venv/.aass-application").touch()
    calls = []
    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda command, **kwargs: calls.append((command, kwargs))
    )
    assert launcher.main(["--root", str(managed.root)]) == 0
    command, options = calls[0]
    assert command == [str(runtime), str(managed.root / "setup_wizard.py")]
    assert options["cwd"] == managed.root


def test_desktop_launcher_without_runtime_starts_local_preparation(managed, monkeypatch):
    calls = []
    monkeypatch.setattr(launcher, "base_python", lambda: "/reviewed/base/python")
    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda command, **kwargs: calls.append(command)
    )
    assert launcher.main(["--root", str(managed.root)]) == 0
    assert calls == [["/reviewed/base/python", str(managed.root / "setup_wizard.py"), "--install"]]


def test_recovery_launches_verified_old_engine_before_importing_broken_new_modules(
    tmp_path, monkeypatch
):
    repository = Path(__file__).resolve().parents[1]
    names = [
        "app_lifecycle.py",
        "install_aass.py",
        "initialize_aass.py",
        "settings.py",
        "telemetry.py",
        "verify_release.py",
        "circuit_breaker.py",
        "sandboxes/__init__.py",
        "sandboxes/container.py",
    ]
    old = release(
        tmp_path / "old", extra={name: (repository / name).read_bytes() for name in names}
    )
    root = lifecycle.install_source(old, tmp_path / "app")
    runtime_fixture(root)
    incoming = release(
        tmp_path / "new",
        "1.3.1",
        NEW_REVISION,
        extra={
            **{name: (repository / name).read_bytes() for name in names},
            "app_lifecycle.py": b"import incomplete_update_dependency\n",
        },
    )
    original_restore = lifecycle._restore
    monkeypatch.setattr(
        lifecycle, "_restore", lambda *_args: (_ for _ in ()).throw(OSError("interrupted"))
    )
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.apply_transaction(
            root, incoming, checks=lambda *_args: (_ for _ in ()).throw(RuntimeError("power loss"))
        )
    monkeypatch.setattr(lifecycle, "_restore", original_restore)
    launcher.recover_before_imports(root)
    assert verify(root)["source_revision"] == OLD_REVISION
    assert read_json(root / ".aass/update-status.json")["status"] == "rolled_back"


def test_predictable_copy_temporary_link_cannot_overwrite_external_file(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "destination"
    source.mkdir()
    target.mkdir()
    (source / "app.py").write_text("new source")
    sentinel = tmp_path / "private"
    sentinel.write_text("keep me")
    try:
        (target / "app.py.aass-new").symlink_to(sentinel)
    except OSError:
        pytest.skip("symlinks unavailable")
    lifecycle._copy_files(source, target, ["app.py"])
    assert sentinel.read_text() == "keep me"
    assert (target / "app.py").read_text() == "new source"


def test_fresh_installer_recovers_interrupted_source_before_verification(managed, monkeypatch):
    runtime = runtime_fixture(managed.root)
    backup = managed.root / ".aass/update-backups" / ("d" * 32)
    shutil.copytree(managed.source, backup / "source")
    shutil.copytree(runtime, backup / "runtime", symlinks=True)
    private = managed.directory / "chosen private.env"
    private.write_text(f"GEMINI_API_KEY={SECRET}\n")
    json_write(managed.root / ".aass/credentials.json", {"path": str(private)})
    json_write(managed.root / ".aass/provider.json", {"service": "gemini", "model": "keep-model"})
    json_write(
        managed.root / ".aass/update-transaction.json",
        {
            "format": 1,
            "phase": "applying",
            "backup": str(backup),
            "new_files": ["unfinished.py"],
            "runtime_existed": True,
        },
    )
    (managed.root / "app.py").write_text("interrupted source replacement")
    (managed.root / "unfinished.py").write_text("partial new file")
    library = runtime / "Lib/site-packages/reviewed-library.pyd"
    library.write_bytes(b"interrupted wheel replacement")
    incoming = new_release(managed)
    checked = []

    def checks(root, _callback):
        checked.append(verify(root)["version"])
        assert library.read_bytes() == b"original library bytes"

    monkeypatch.setattr(lifecycle, "_runtime_checks", checks)
    assert lifecycle.install_source(incoming, managed.root) == managed.root
    assert checked == ["1.3.1"]
    assert verify(managed.root)["source_revision"] == NEW_REVISION
    assert not (managed.root / "unfinished.py").exists()
    assert selected_credentials_file(managed.root) == private
    assert provider_preferences(managed.root)["model"] == "keep-model"
