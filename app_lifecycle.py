"""Managed installs and recoverable full-release updates. No cloud generation calls."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath

from install_aass import Installer, SetupProblem, installation_lock
from settings import is_link, subprocess_environment
from telemetry import atomic_json
from verify_release import verify

STATE = ".aass"
MARKER = "managed-install.json"
JOURNAL = "update-transaction.json"


class LifecycleError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def base_python():
    path = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    if (
        os.name == "nt"
        and path.name.lower() == "pythonw.exe"
        and path.with_name("python.exe").is_file()
    ):
        path = path.with_name("python.exe")
    return str(path)


def managed_root():
    if os.name != "nt":
        return Path.home() / ".local/share/AASS"
    base = os.environ.get("LOCALAPPDATA")
    if not base or not Path(base).is_absolute():
        raise LifecycleError(
            "profile_missing", "Windows could not locate your local application folder."
        )
    return Path(base) / "Programs/AASS"


def _state(root):
    root = Path(root).absolute()
    if is_link(root) or is_link(root / STATE):
        raise LifecycleError(
            "linked_install", "The application and its state must be normal folders, not links."
        )
    (root / STATE).mkdir(parents=True, exist_ok=True)
    return root / STATE


def _owned_path(root, path):
    root, path = Path(root).absolute(), Path(path).absolute()
    if not path.is_relative_to(root):
        raise LifecycleError("unsafe_path", "An update path is outside the application.")
    for item in [path, *path.parents]:
        if is_link(item):
            raise LifecycleError(
                "linked_source", "An update path is a link. The app was not changed."
            )
        if item == root:
            break
    return path


def _read(path, limit=1024 * 1024):
    path = Path(path)
    if is_link(path) or not path.is_file() or path.stat().st_size > limit:
        raise LifecycleError(
            "invalid_state",
            "Application update state is unreadable. Keep the folder intact for recovery.",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise LifecycleError(
            "invalid_state",
            "Application update state is unreadable. Keep the folder intact for recovery.",
        ) from None
    if not isinstance(data, dict):
        raise LifecycleError("invalid_state", "Application update state has an invalid format.")
    return data


@contextlib.contextmanager
def application_lock(root):
    try:
        with installation_lock(_state(root) / "application.lock"):
            yield
    except SetupProblem:
        raise LifecycleError(
            "already_running",
            "AASS is already open or an update is running. Use the existing window.",
        ) from None


@contextlib.contextmanager
def _update_lock(root):
    try:
        with installation_lock(_state(root) / "setup.lock"):
            yield
    except SetupProblem:
        raise LifecycleError(
            "setup_running",
            "Another installation or update is running. Wait for that window to finish.",
        ) from None


def _status(root, status, message, version=""):
    atomic_json(
        _state(root) / "update-status.json",
        {"status": status, "version": version, "message": message},
    )


def _version(value):
    import re

    if not isinstance(value, str) or not re.fullmatch(r"\d{1,4}\.\d{1,4}\.\d{1,4}", value):
        raise LifecycleError("invalid_version", "This release has an invalid version number.")
    return tuple(int(part) for part in value.split("."))


def _managed(root):
    data = _read(Path(root) / STATE / MARKER, 8192)
    if (
        data.get("format") != 1
        or data.get("application") != "AASS"
        or data.get("root") != str(Path(root).resolve())
    ):
        raise LifecycleError(
            "unmanaged_install",
            "Run Install-AASS.bat from the new ZIP to install the desktop application first.",
        )
    return data


def prepare_update(root, callback=None, cancel_event=None):
    """Download and validate completely before asking the running GUI to close."""
    from update_manager import UpdateError, discover_release, download_release

    root = Path(root).resolve()
    _managed(root)
    current = verify(root)

    def say(message):
        if cancel_event is not None and cancel_event.is_set():
            raise LifecycleError(
                "cancelled", "Update cancelled. Your installed app has not changed."
            )
        if callback:
            callback(message)

    say("Checking the latest verified GitHub release...")
    try:
        release = discover_release()
        if current.get("source_revision", "").startswith(release.source_prefix):
            return {"status": "ok", "changed": False, "version": current["version"]}
        if _version(release.version) < _version(current["version"]):
            raise LifecycleError(
                "older_release",
                "Your installed version is newer than the latest published release.",
            )
        verified = download_release(_state(root) / "update-downloads", say, release=release)
    except UpdateError as error:
        raise LifecycleError(error.code, str(error)) from None
    say("Full release and matching security evidence verified. Preparing the restart...")
    plan = {
        "format": 1,
        "status": "ok",
        "changed": True,
        "root": str(root),
        "stage": str(verified.root.resolve()),
        "version": verified.manifest["version"],
        "source_revision": verified.manifest["source_revision"],
        "tag": verified.release.tag,
        "manifest_sha256": hashlib.sha256(
            (verified.root / "RELEASE-MANIFEST.json").read_bytes()
        ).hexdigest(),
    }
    folder = _state(root) / "update-plans"
    _owned_path(root, folder)
    folder.mkdir(exist_ok=True)
    path = folder / (uuid.uuid4().hex + ".json")
    plan["plan_file"] = str(path)
    atomic_json(path, plan)
    return plan


def _validated_plan(root, plan):
    root = Path(root).resolve()
    if not isinstance(plan, dict) or plan.get("format") != 1 or plan.get("root") != str(root):
        raise LifecycleError(
            "invalid_plan", "The prepared update does not belong to this installation."
        )
    stage = Path(plan.get("stage", ""))
    if not stage.is_absolute() or not stage.resolve().is_relative_to(
        root / STATE / "update-downloads"
    ):
        raise LifecycleError(
            "invalid_plan", "The prepared update is outside the application's update folder."
        )
    for parent in [stage, *stage.parents]:
        if parent == root:
            break
        if is_link(parent):
            raise LifecycleError("invalid_plan", "A prepared update folder is a link.")
    manifest = verify(stage)
    if (
        hashlib.sha256((stage / "RELEASE-MANIFEST.json").read_bytes()).hexdigest()
        != plan.get("manifest_sha256")
        or manifest.get("dirty")
        or manifest.get("source_revision") != plan.get("source_revision")
        or manifest.get("version") != plan.get("version")
    ):
        raise LifecycleError(
            "changed_stage",
            "The prepared release changed after verification. Check for updates again.",
        )
    return stage, manifest


def launch_update(root, plan, parent_pid):
    root = Path(root).resolve()
    _managed(root)
    _validated_plan(root, plan)
    path = Path(plan.get("plan_file", ""))
    if (
        not path.is_absolute()
        or path.parent != root / STATE / "update-plans"
        or _read(path) != plan
    ):
        raise LifecycleError(
            "invalid_plan", "The update handoff is invalid. Check for updates again."
        )
    command = [
        base_python(),
        str(root / "app_lifecycle.py"),
        "--apply-plan",
        str(path),
        "--root",
        str(root),
        "--wait-pid",
        str(parent_pid),
    ]
    try:
        # Preserve explicit user bindings for the restarted app. Installer children
        # strip credentials; the downloader never reads bindings or sends keys.
        process = subprocess.Popen(
            command,
            cwd=root,
            env=subprocess_environment(credentials=True),
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )
    except OSError:
        raise LifecycleError(
            "handoff_failed", "The updater could not start. Your app is unchanged; retry Update."
        ) from None
    time.sleep(0.15)
    if process.poll() is not None:
        raise LifecycleError(
            "handoff_failed",
            "The updater stopped before handoff. Your app is unchanged; retry Update.",
        )


def _wait_parent(pid, timeout=120):
    if not pid or pid <= 0 or pid == os.getpid():
        raise LifecycleError(
            "invalid_parent", "The updater could not identify its application window."
        )
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes, api.OpenProcess.restype = (
            [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
            wintypes.HANDLE,
        )
        api.WaitForSingleObject.argtypes, api.WaitForSingleObject.restype = (
            [wintypes.HANDLE, wintypes.DWORD],
            wintypes.DWORD,
        )
        api.CloseHandle.argtypes, api.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
        handle = api.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # already exited
                return
            raise LifecycleError(
                "parent_wait_failed", "Windows could not wait for the current app to close."
            )
        try:
            if api.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise LifecycleError(
                    "app_still_open", "The current app did not close. Close AASS and retry Update."
                )
        finally:
            api.CloseHandle(handle)
    else:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        raise LifecycleError(
            "app_still_open", "The current app did not close. Close AASS and retry Update."
        )


def _copy_files(source, destination, names):
    for name in names:
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
            raise LifecycleError("unsafe_path", "A release contains an unsafe source path.")
        target = Path(destination).joinpath(*relative.parts)
        if any(
            is_link(parent)
            for parent in [target, *target.parents]
            if parent.is_relative_to(destination)
        ):
            raise LifecycleError(
                "linked_source", "An application source path is a link. No update was applied."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".aass-copy-", dir=target.parent)
        try:
            with (
                os.fdopen(fd, "wb") as output,
                Path(source).joinpath(*relative.parts).open("rb") as incoming,
            ):
                shutil.copyfileobj(incoming, output)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _journal(root):
    data = _read(_state(root) / JOURNAL)
    backup = Path(data.get("backup", ""))
    _owned_path(root, backup)
    if (
        data.get("format") != 1
        or not backup.is_absolute()
        or backup.parent != _state(root) / "update-backups"
        or is_link(backup)
    ):
        raise LifecycleError(
            "invalid_recovery",
            "The recovery record is invalid. Keep the installation folder intact.",
        )
    return data, backup


def _restore(root):
    data, backup = _journal(root)
    old = verify(backup / "source")
    for name in data.get("new_files", []):
        if name not in old["files"]:
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
                raise LifecycleError(
                    "invalid_recovery", "The recovery record contains an unsafe source path."
                )
            path = root.joinpath(*relative.parts)
            _owned_path(root, path)
            if (
                relative.parts[0].startswith(".") and relative.parts[0] != ".env.example"
            ) or relative.parts[0] in {
                "generated",
                "__pycache__",
            }:
                raise LifecycleError(
                    "invalid_recovery", "Recovery cannot remove private application state."
                )
            if path.is_file() and not is_link(path):
                path.unlink()
    _copy_files(backup / "source", root, [*old["files"], "RELEASE-MANIFEST.json"])
    runtime = root / ".venv"
    if data.get("runtime_existed"):
        if not (backup / "runtime").is_dir() or is_link(backup / "runtime"):
            raise LifecycleError(
                "runtime_recovery_missing",
                "The saved runtime is missing. Keep the backup and rerun the installer.",
            )
        if runtime.exists():
            if is_link(runtime):
                raise LifecycleError(
                    "linked_runtime", "The runtime is a link and cannot be restored automatically."
                )
            shutil.rmtree(runtime)
        shutil.copytree(backup / "runtime", runtime, symlinks=True)
    elif runtime.exists():
        if is_link(runtime):
            raise LifecycleError(
                "linked_runtime", "The runtime is a link and cannot be removed automatically."
            )
        shutil.rmtree(runtime)
    verify(root)
    data["phase"] = "rolled_back"
    atomic_json(_state(root) / JOURNAL, data)
    _status(
        root,
        "rolled_back",
        "The update did not finish. Your previous version was restored; you can retry Update.",
        old["version"],
    )


def recover_pending(root):
    root = Path(root).resolve()
    path = root / STATE / JOURNAL
    if not path.exists():
        return False
    with _update_lock(root), application_lock(root):
        data, _ = _journal(root)
        if data.get("phase") in {"committed", "rolled_back"}:
            return False
        _restore(root)
        return True


def _runtime_checks(root, callback):
    installer = Installer(root)
    try:
        original_say = installer.say
        if callback:

            def say(message):
                original_say(message)
                callback(installer.redact(str(message)))

            installer.say = say
        installer.run(
            "Updating only required runtime components",
            [base_python(), str(root / "launch_aass.py"), "--install-only"],
            timeout=1800,
        )
        runtime = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        installer.run(
            "Checking updated dependencies", [str(runtime), "-m", "pip", "check"], timeout=60
        )
        if os.name == "nt":
            installer.run(
                "Opening and checking the updated app window",
                [str(runtime), str(root / "setup_wizard.py"), "--smoke-test"],
                timeout=60,
            )
            installer.run(
                "Refreshing your AASS desktop icon",
                [str(runtime), str(root / "desktop_integration.py"), "--root", str(root)],
                timeout=60,
            )
    finally:
        installer.log.close()


def apply_transaction(root, source, callback=None, *, checks=None):
    """Update all managed files and runtime, restoring both on failure or next launch."""
    root, source = Path(root).resolve(), Path(source).resolve()
    incoming = verify(source)
    if incoming.get("dirty") or not incoming.get("source_revision"):
        raise LifecycleError("unverified_source", "Updates require an identified clean release.")
    with _update_lock(root), application_lock(root):
        if (root / STATE / JOURNAL).exists():
            pending, _ = _journal(root)
            if pending.get("phase") not in {"committed", "rolled_back"}:
                _restore(root)
        old = verify(root)
        if _version(incoming["version"]) < _version(old["version"]):
            raise LifecycleError(
                "older_release", "An older release cannot replace your current app."
            )
        backup = _state(root) / "update-backups" / uuid.uuid4().hex
        _owned_path(root, backup)
        backup.mkdir(parents=True)
        _copy_files(root, backup / "source", [*old["files"], "RELEASE-MANIFEST.json"])
        runtime = root / ".venv"
        runtime_existed = runtime.is_dir()
        if is_link(runtime) or (runtime.exists() and not runtime_existed):
            raise LifecycleError(
                "linked_runtime", "The application runtime must be a normal folder."
            )
        if callback:
            callback("Saving your current app and runtime for automatic rollback...")
        if runtime_existed:
            shutil.copytree(runtime, backup / "runtime", symlinks=True)
        journal = {
            "format": 1,
            "phase": "prepared",
            "backup": str(backup),
            "new_files": list(incoming["files"]),
            "runtime_existed": runtime_existed,
        }
        atomic_json(_state(root) / JOURNAL, journal)
        _status(
            root, "updating", "Installing and checking the verified release...", incoming["version"]
        )
        try:
            journal["phase"] = "applying"
            atomic_json(_state(root) / JOURNAL, journal)
            # Remove only retired managed files whose old hashes were verified.
            for name in old["files"]:
                if name not in incoming["files"]:
                    (root / name).unlink()
            _copy_files(source, root, [*incoming["files"], "RELEASE-MANIFEST.json"])
            verify(root)
            journal["phase"] = "verifying"
            atomic_json(_state(root) / JOURNAL, journal)
            (checks or _runtime_checks)(root, callback)
            verify(root)
            journal["phase"] = "committed"
            atomic_json(_state(root) / JOURNAL, journal)
            _status(
                root,
                "updated",
                "AASS updated successfully. Your projects and private settings were preserved.",
                incoming["version"],
            )
            atomic_json(
                _state(root) / MARKER,
                {
                    "format": 1,
                    "application": "AASS",
                    "root": str(root),
                    "source_revision": incoming["source_revision"],
                    "version": incoming["version"],
                },
            )
        except BaseException:
            try:
                _restore(root)
            except (OSError, ValueError, LifecycleError):
                _status(
                    root,
                    "failed",
                    "Update recovery needs attention. Keep this installation and its rollback backup; rerun Install-AASS.bat.",
                )
                raise LifecycleError(
                    "recovery_failed",
                    "The update stopped and automatic recovery could not finish. Keep the rollback backup and rerun Install-AASS.bat.",
                ) from None
            raise LifecycleError(
                "update_rolled_back",
                "The update did not pass its checks. Your previous app and runtime were restored; retry Update when ready.",
            ) from None
        # Keep the newest recovery copy, discard only older owned backup folders.
        for other in backup.parent.iterdir():
            if other != backup and other.is_dir() and not is_link(other) and len(other.name) == 32:
                shutil.rmtree(other, ignore_errors=True)
    return incoming


def install_source(source, target, callback=None):
    """Copy verified source before creating a venv; never relocate a built runtime."""
    source, target = Path(source).resolve(), Path(target).absolute()
    manifest = verify(source)
    if manifest.get("dirty") or not manifest.get("source_revision"):
        raise LifecycleError("unverified_source", "Install a complete clean verified release.")
    if target.exists() and any(target.iterdir()):
        _managed(target)
        current = verify(target)
        if current["source_revision"] != manifest["source_revision"]:
            apply_transaction(target, source, callback)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.parent / (".AASS-install-" + uuid.uuid4().hex)
    try:
        with installation_lock(target.parent / ".AASS-install.lock"):
            if target.exists() and any(target.iterdir()):
                raise LifecycleError(
                    "install_race",
                    "Another installation finished first. Reopen the AASS desktop icon.",
                )
            stage.mkdir()
            _copy_files(source, stage, [*manifest["files"], "RELEASE-MANIFEST.json"])
            verify(stage)
            state = _state(stage)
            atomic_json(
                state / MARKER,
                {
                    "format": 1,
                    "application": "AASS",
                    "root": str(target.resolve()),
                    "source_revision": manifest["source_revision"],
                    "version": manifest["version"],
                },
            )
            from settings import provider_preferences, selected_credentials_file

            try:
                preferences = provider_preferences(source)
                if preferences:
                    atomic_json(state / "provider.json", preferences)
            except (ValueError, OSError):
                pass
            try:
                selection = selected_credentials_file(source)
                if selection:
                    atomic_json(state / "credentials.json", {"path": str(selection)})
            except (ValueError, OSError):
                pass
            if not (state / "credentials.json").exists():
                for name in (".env", ".env.txt"):
                    private = source / name
                    if (
                        private.is_file()
                        and not is_link(private)
                        and private.stat().st_size <= 65536
                    ):
                        atomic_json(state / "credentials.json", {"path": str(private)})
                        break
            if target.exists():
                target.rmdir()  # Only an empty explicitly chosen target is replaced.
            os.replace(stage, target)
    finally:
        if stage.exists() and not is_link(stage):
            shutil.rmtree(stage, ignore_errors=True)
    return target


def start_app(root, *, install=False):
    root = Path(root).resolve()
    python = Path(base_python())
    if os.name == "nt" and python.with_name("pythonw.exe").is_file():
        python = python.with_name("pythonw.exe")
    command = [str(python), str(root / "desktop_launcher.py"), "--root", str(root)]
    if install:
        command.append("--install")
    return subprocess.Popen(
        command,
        cwd=root,
        env=subprocess_environment(credentials=True),
        start_new_session=os.name != "nt",
        creationflags=subprocess.DETACHED_PROCESS if os.name == "nt" else 0,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-plan", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--wait-pid", type=int, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    succeeded = False
    try:
        plan = _read(args.apply_plan)
        stage, _ = _validated_plan(root, plan)
        print(
            "AASS update - keep this window open. Your previous version is backed up before changes.",
            flush=True,
        )
        _wait_parent(args.wait_pid)
        apply_transaction(root, stage, lambda message: print(message, flush=True))
        succeeded = True
    except (LifecycleError, OSError, ValueError) as error:
        message = (
            str(error)
            if isinstance(error, LifecycleError)
            else "The update could not finish. Your previous app remains available; check Update status."
        )
        print(message, flush=True)
        if not (root / STATE / "update-status.json").exists():
            _status(root, "failed", message)
    finally:
        try:
            start_app(root)
        except OSError:
            print("Reopen AASS using its desktop icon.", flush=True)
    return 0 if succeeded else 2


if __name__ == "__main__":
    raise SystemExit(main())
