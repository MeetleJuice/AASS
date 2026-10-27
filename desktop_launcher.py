"""Stable desktop entry point: recover, verify, then launch the installed GUI."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def base_python():
    return str(Path(getattr(sys, "_base_executable", sys.executable)).resolve())


def recover_before_imports(root):
    """Use the complete old engine if the new source copy was interrupted."""
    journal = root / ".aass/update-transaction.json"
    if not journal.exists():
        return

    def regular(path):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Linked recovery path")

    regular(root / ".aass")
    regular(journal)
    if journal.stat().st_size > 1024 * 1024:
        raise ValueError("Recovery record too large")
    data = json.loads(journal.read_text(encoding="utf-8"))
    if data.get("phase") in {"committed", "rolled_back"}:
        return
    backup = Path(data["backup"])
    if not backup.is_absolute() or backup.parent != root / ".aass/update-backups":
        raise ValueError("Invalid recovery location")
    for path in (backup.parent, backup, backup / "source"):
        regular(path)
    source = backup / "source"
    manifest_path = source / "RELEASE-MANIFEST.json"
    regular(manifest_path)
    if manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError("Recovery manifest too large")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest.get("files"), dict) or not 0 < len(manifest["files"]) <= 500:
        raise ValueError("Invalid recovery manifest")
    for name, digest in manifest["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
            raise ValueError("Unsafe recovery file")
        path = source / relative
        for parent in [path, *path.parents]:
            regular(parent)
            if parent == source:
                break
        if (
            path.stat().st_size > 5 * 1024 * 1024
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("Recovery file changed")
    code = "import sys; sys.path.insert(0, sys.argv[1]); from app_lifecycle import recover_pending; recover_pending(sys.argv[2])"
    subprocess.run(
        [
            getattr(sys, "_base_executable", sys.executable),
            "-I",
            "-S",
            "-c",
            code,
            str(source),
            str(root),
        ],
        check=True,
        timeout=600,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        recover_before_imports(root)
        from settings import subprocess_environment
        from verify_release import verify

        verify(root)
        runtime = root / ".venv" / ("Scripts/pythonw.exe" if os.name == "nt" else "bin/python")
        python = str(runtime) if runtime.is_file() else base_python()
        command = [python, str(root / "setup_wizard.py")]
        if (
            args.install
            or not runtime.is_file()
            or not (root / ".venv/.aass-application").is_file()
        ):
            command.append("--install")
        subprocess.Popen(
            command,
            cwd=root,
            env=subprocess_environment(credentials=True),
            start_new_session=os.name != "nt",
        )
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        message = (
            str(error)
            if getattr(error, "code", None)
            else "AASS could not verify or open this installation. Run Install-AASS.bat from a complete release ZIP."
        )
        print(message, file=sys.stderr)
        if os.name == "nt":
            try:
                import tkinter.messagebox

                tkinter.messagebox.showinfo("AASS", message)
            except (ImportError, RuntimeError):
                pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
