"""Cross-platform local launcher: create environment, install locked dependencies, discover services."""

import argparse
import os
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path


def setup_step(label, command, *, cwd=None, progress_interval=15):
    """Inherit console output and show liveness while an installer is quiet."""
    print(f"\n[AASS] {label}", flush=True)
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=cwd)
    try:
        while True:
            try:
                code = process.wait(timeout=progress_interval)
                break
            except subprocess.TimeoutExpired:
                elapsed = int(time.monotonic() - started)
                print(f"[AASS] Still running: {label} ({elapsed}s elapsed)", flush=True)
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise
    if code:
        raise subprocess.CalledProcessError(code, command)
    print(f"[AASS] Finished: {label}", flush=True)


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
    print(f"[AASS] Python: {sys.executable}", flush=True)
    print(f"[AASS] Project: {root}", flush=True)
    if not executable.exists():
        print("[AASS] Creating virtual environment...", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    marker = environment / ".aass-installed"
    import hashlib

    fingerprint = hashlib.sha256(
        (root / "requirements.lock").read_bytes() + (root / "pyproject.toml").read_bytes()
    ).hexdigest()
    pip = [
        str(executable),
        "-u",
        "-m",
        "pip",
        "--disable-pip-version-check",
        "--no-input",
        "--timeout",
        "20",
        "--retries",
        "1",
        "--verbose",
    ]
    if not marker.exists() or marker.read_text() != fingerprint:
        setup_step(
            "Installing locked Python dependencies",
            [*pip, "install", "--prefer-binary", "-r", str(root / "requirements.lock")],
            cwd=root,
        )
        setup_step(
            "Installing AASS application", [*pip, "install", "--no-deps", "-e", "."], cwd=root
        )
        # Prefer an already installed verified system Chromium over a second download.
        if not (os.environ.get("AASS_CHROMIUM_EXECUTABLE") or shutil.which("chromium")):
            setup_step(
                "Installing Chromium browser",
                [str(executable), "-u", "-m", "playwright", "install", "chromium"],
                cwd=root,
            )
        marker.write_text(fingerprint)
    if not (root / "generated/architecture_spec.json").exists():
        setup_step(
            "Initializing architecture and local model discovery",
            [str(executable), "-u", str(root / "initialize_aass.py"), "--root", str(root)],
            cwd=root,
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
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[AASS] Setup cancelled. Run the launcher again to resume.", flush=True)
        raise SystemExit(130) from None
    except subprocess.CalledProcessError as error:
        print(
            f"\n[AASS] A setup step failed (exit {error.returncode}). See the output above.",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(error.returncode) from None
