"""Create the current user's AASS desktop shortcut without elevation or shell code."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from settings import is_link, subprocess_environment

SHORTCUT_NAME = "AASS.lnk"
SHORTCUT_DESCRIPTION = "AASS managed desktop shortcut"


class ShortcutError(RuntimeError):
    """A safe, user-facing desktop integration failure."""


def _windows():
    return sys.platform == "win32"


def _known_desktop():
    """SHGetKnownFolderPath follows Windows Desktop redirection and OneDrive."""
    import ctypes
    from ctypes import wintypes

    class Guid(ctypes.Structure):
        _fields_ = [
            ("data1", wintypes.DWORD),
            ("data2", wintypes.WORD),
            ("data3", wintypes.WORD),
            ("data4", ctypes.c_ubyte * 8),
        ]

    folder_id = Guid.from_buffer_copy(uuid.UUID("B4BFCC3A-DB2C-424C-B029-7FE99A87C641").bytes_le)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    function = shell.SHGetKnownFolderPath
    function.argtypes = [
        ctypes.POINTER(Guid),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    function.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    value = ctypes.c_wchar_p()
    code = function(ctypes.byref(folder_id), 0, None, ctypes.byref(value))
    try:
        if code != 0 or not value.value:
            raise ShortcutError("Windows could not locate your Desktop folder.")
        return Path(value.value)
    finally:
        if value:
            ole.CoTaskMemFree(value)


def _registry_desktop():
    """Registry fallback preserves custom Desktop redirection, never guesses it."""
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
    ) as key:
        value, kind = winreg.QueryValueEx(key, "Desktop")
    if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(value, str):
        raise ShortcutError("Windows Desktop settings need attention.")
    path = Path(os.path.expandvars(value))
    if not path.is_absolute():
        raise ShortcutError("Windows Desktop settings need attention.")
    return path


def desktop_directory():
    if not _windows():
        raise ShortcutError("Desktop shortcuts are supported by the Windows installer.")
    try:
        path = _known_desktop()
    except (OSError, ShortcutError):
        try:
            path = _registry_desktop()
        except (OSError, ShortcutError):
            raise ShortcutError(
                "Windows could not locate your Desktop. AASS remains available through Start-AASS.bat."
            ) from None
    if not path.is_absolute():
        raise ShortcutError("Windows returned an invalid Desktop location.")
    return path


@contextlib.contextmanager
def _shortcut_shell():
    # pywin32 is already hash-pinned in the Windows runtime lock. Imports remain
    # lazy so the installer itself still starts with the Python standard library.
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        yield win32com.client.Dispatch("WScript.Shell")
    finally:
        pythoncom.CoUninitialize()


def _matching_target(actual, expected):
    return os.path.normcase(os.path.abspath(actual)) == os.path.normcase(os.path.abspath(expected))


def _check_existing(shell, shortcut, target, arguments):
    if is_link(shortcut):
        raise ShortcutError(
            "The existing AASS desktop link needs attention; rename it before retrying."
        )
    if not shortcut.exists():
        return
    if not shortcut.is_file():
        raise ShortcutError(
            "The Desktop already contains another item named AASS.lnk. Rename it before retrying."
        )
    try:
        existing = shell.CreateShortcut(str(shortcut))
        actual_target, actual_arguments = existing.TargetPath, existing.Arguments
    except Exception:
        raise ShortcutError(
            "The existing AASS shortcut could not be inspected. Rename it before retrying."
        ) from None
    if (
        not actual_target
        or not _matching_target(str(actual_target), str(target))
        or actual_arguments != arguments
    ):
        raise ShortcutError(
            "The existing AASS shortcut belongs to another location. Rename it before retrying; it has not been replaced."
        )


def _pythonw():
    base = Path(getattr(sys, "_base_executable", sys.executable))
    executable = base.with_name("pythonw.exe")
    if not executable.is_file() or is_link(executable):
        raise ShortcutError(
            "Python's window launcher is missing. Repair your Python installation, then retry creating the Desktop shortcut."
        )
    return executable


def _delegate(root, icon, desktop, launcher, runtime):
    if not runtime.is_file() or is_link(runtime):
        raise ShortcutError("Finish local installation before creating the Desktop shortcut.")
    command = [
        str(runtime),
        str(Path(__file__).resolve()),
        "--root",
        str(root),
        "--icon",
        str(icon),
        "--desktop",
        str(desktop),
        "--launcher",
        str(launcher),
        "--no-delegate",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            env=subprocess_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        report = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ShortcutError(
            "The Desktop shortcut could not be created. Local installation is retained; retry setup or open Start-AASS.bat."
        ) from None
    if result.returncode != 0 or not isinstance(report, dict) or report.get("status") != "ok":
        raise ShortcutError(
            "The Desktop shortcut needs attention. Open Start-AASS.bat, or check for an existing shortcut pointing to another folder."
        )
    shortcut = desktop / SHORTCUT_NAME
    if report.get("shortcut") != str(shortcut) or not shortcut.is_file() or is_link(shortcut):
        raise ShortcutError("Windows did not finish creating the Desktop shortcut.")
    return shortcut


def create_shortcut(
    application_root,
    icon_path=None,
    *,
    desktop=None,
    launcher=None,
    runtime=None,
    _allow_delegate=True,
):
    """Atomically create/update only the shortcut for this exact AASS launcher.

    ``desktop`` supports installation tests; normal calls resolve Windows' actual
    current-user Desktop. ``launcher`` can name a stable managed-install launcher.
    No credentials, PowerShell script, execution-policy change or admin action is
    involved. Only the link path is returned; existing unrelated links are kept.
    """
    if not _windows():
        raise ShortcutError("Desktop shortcuts are supported by the Windows installer.")
    root = Path(application_root).absolute()
    launcher = (
        Path(launcher).absolute()
        if launcher is not None
        else root / "desktop_launcher.py"
        if (root / "desktop_launcher.py").is_file()
        else root / "Start-AASS.bat"
    )
    icon = Path(icon_path).absolute() if icon_path is not None else root / "assets/aass.ico"
    desktop = Path(desktop).absolute() if desktop is not None else desktop_directory()
    for path, label in ((launcher, "launcher"), (icon, "icon")):
        if is_link(path) or not path.is_file():
            raise ShortcutError(f"The AASS {label} is missing. Use a complete verified release.")
    if icon.stat().st_size > 1024 * 1024:
        raise ShortcutError("The AASS icon exceeds the supported size.")
    with icon.open("rb") as handle:
        header = handle.read(6)
    if (
        len(header) != 6
        or header[:4] != b"\x00\x00\x01\x00"
        or not 1 <= int.from_bytes(header[4:], "little") <= 256
    ):
        raise ShortcutError("The AASS icon is not a valid Windows icon file.")
    desktop.mkdir(parents=True, exist_ok=True)
    target = _pythonw() if launcher.suffix.lower() in {".py", ".pyw"} else launcher
    arguments = (
        subprocess.list2cmdline([str(launcher), "--root", str(root)]) if target != launcher else ""
    )
    destination = desktop / SHORTCUT_NAME
    temporary = None
    try:
        with _shortcut_shell() as shell:
            _check_existing(shell, destination, target, arguments)
            descriptor, name = tempfile.mkstemp(
                prefix=".aass-shortcut-", suffix=".lnk", dir=desktop
            )
            os.close(descriptor)
            temporary = Path(name)
            temporary.unlink()  # WScript.Shell creates the new link itself.
            link = shell.CreateShortcut(str(temporary))
            link.TargetPath = str(target)
            link.WorkingDirectory = str(root)
            link.IconLocation = str(icon) + ",0"
            link.Description = SHORTCUT_DESCRIPTION
            link.Arguments = arguments
            link.WindowStyle = 1
            link.Save()
            if not temporary.is_file() or is_link(temporary):
                raise ShortcutError("Windows did not write the Desktop shortcut.")
            _check_existing(shell, destination, target, arguments)
            os.replace(temporary, destination)
            return destination
    except ImportError:
        if not _allow_delegate:
            raise ShortcutError(
                "The installed Windows shortcut component is missing. Run local setup to repair the application packages."
            ) from None
        runtime = Path(runtime) if runtime is not None else root / ".venv/Scripts/python.exe"
        return _delegate(root, icon, desktop, launcher, runtime)
    except ShortcutError:
        raise
    except Exception:
        raise ShortcutError(
            "Windows could not finish creating the Desktop shortcut. Local setup is retained; close any shortcut editor and retry."
        ) from None
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--icon", type=Path)
    parser.add_argument("--desktop", type=Path)
    parser.add_argument("--launcher", type=Path)
    parser.add_argument("--no-delegate", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        path = create_shortcut(
            args.root,
            args.icon,
            desktop=args.desktop,
            launcher=args.launcher,
            _allow_delegate=not args.no_delegate,
        )
        report = {"status": "ok", "shortcut": str(path)}
    except (ShortcutError, OSError):
        report = {
            "status": "error",
            "code": "desktop_shortcut_failed",
            "hint": "Open Start-AASS.bat to use the installed app. Check for an existing AASS shortcut pointing elsewhere, then retry setup.",
        }
    print(json.dumps(report))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
