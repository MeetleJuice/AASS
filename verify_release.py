"""Verify release file hashes and reject unexpected executable content. Not an antivirus scanner."""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath

IGNORED = {
    ".venv",
    ".aass",
    "generated",
    "__pycache__",
    ".git",
    ".pytest_cache",
    "tests",
    "scripts",
    "docs",
    "examples",
    ".github",
}


def is_link(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


EXECUTABLE_SUFFIXES = {".py", ".pyw", ".bat", ".cmd", ".ps1", ".exe", ".dll", ".zip", ".sh"}


def verify(root):
    root = Path(root).resolve()
    manifest = root / "RELEASE-MANIFEST.json"
    if not manifest.is_file() or is_link(manifest):
        raise ValueError(
            "No release manifest. Use the verified release ZIP, not an old patch or GitHub source archive."
        )
    if manifest.stat().st_size > 1024 * 1024:
        raise ValueError("Release manifest exceeds size limit")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("format") != 1
        or not isinstance(data.get("files"), dict)
        or not 0 < len(data["files"]) <= 500
        or not isinstance(data.get("version"), str)
    ):
        raise ValueError("Invalid release manifest")
    for name, digest in data["files"].items():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid release hash")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
            raise ValueError("Unsafe manifest path")
        path = root.joinpath(*relative.parts)
        if any(
            is_link(root.joinpath(*relative.parts[:i])) for i in range(1, len(relative.parts) + 1)
        ):
            raise ValueError("Release file is a symlink: " + name)
        if (
            not path.is_file()
            or path.stat().st_size > 5 * 1024 * 1024
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("Release file missing or modified: " + name)
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        kept = []
        for name in dirs:
            if name in IGNORED or name.endswith(".egg-info"):
                continue
            if is_link(base / name):
                raise ValueError("Unexpected runtime directory link")
            kept.append(name)
        dirs[:] = kept
        for name in files:
            path = base / name
            relative = path.relative_to(root).as_posix()
            if path.suffix.lower() in EXECUTABLE_SUFFIXES and relative not in data["files"]:
                raise ValueError("Unexpected executable source: " + relative)
    return data


def prepare_update(root):
    """Retire only an exact, known obsolete helper; never remove user-modified code."""
    path = Path(root) / "Check-Connections.bat"
    if not path.exists():
        return
    expected = "fa82cb03f0f2005e8d912f11c099f0f9e8a148808ceab93d262d6e0e96e02c5e"
    if (
        is_link(path)
        or not path.is_file()
        or hashlib.sha256(path.read_bytes()).hexdigest() != expected
    ):
        raise ValueError(
            "An unknown Check-Connections.bat is present. Review/remove that obsolete helper before updating"
        )
    path.unlink()
    print("Removed the exact obsolete connection-check helper. Use the Start menu instead.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--source-checkout", action="store_true")
    parser.add_argument("--prepare-update", action="store_true")
    args = parser.parse_args()
    if args.source_checkout and (args.root / ".git").is_dir():
        print("Developer Git checkout: no release/antivirus certification is implied.")
        return 0
    try:
        if args.prepare_update:
            prepare_update(args.root)
        data = verify(args.root)
        print("Release file hashes verified. Version: " + data["version"])
        print("Hash verification is not an antivirus clearance or a publisher signature.")
        return 0
    except (ValueError, OSError) as error:
        print("RELEASE VERIFICATION FAILED: " + str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
