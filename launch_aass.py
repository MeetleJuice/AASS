"""Cross-platform local launcher: create environment, install locked dependencies, discover services."""

import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    environment = root / ".venv"
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if sys.version_info < (3, 12):
        raise SystemExit("Install Python 3.12 or newer, then relaunch AASS.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--integration", action="store_true")
    args, remaining = parser.parse_known_args()
    if not executable.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    marker = environment / ".aass-installed"
    import hashlib

    fingerprint = hashlib.sha256(
        (root / "requirements.lock").read_bytes() + (root / "pyproject.toml").read_bytes()
    ).hexdigest()
    if not marker.exists() or marker.read_text() != fingerprint:
        subprocess.run(
            [str(executable), "-m", "pip", "install", "-r", str(root / "requirements.lock")],
            cwd=root,
            check=True,
        )
        subprocess.run(
            [str(executable), "-m", "pip", "install", "--no-deps", "-e", "."], cwd=root, check=True
        )
        # Prefer an already installed verified system Chromium over a second download.
        if not (os.environ.get("AASS_CHROMIUM_EXECUTABLE") or shutil.which("chromium")):
            subprocess.run([str(executable), "-m", "playwright", "install", "chromium"], check=True)
        marker.write_text(fingerprint)
    if not (root / "generated/architecture_spec.json").exists():
        subprocess.run(
            [str(executable), str(root / "initialize_aass.py"), "--root", str(root)],
            cwd=root,
            check=True,
        )
    if args.install_only:
        return 0
    if args.integration:
        child_env = os.environ.copy()
        child_env["AASS_INTEGRATION"] = "1"
        return subprocess.run(
            [str(executable), "-m", "pytest", "-q"], cwd=root, env=child_env, check=False
        ).returncode
    return subprocess.run(
        [str(executable), "-m", "orchestration_canvas", *(remaining or ["doctor"])],
        cwd=root,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
