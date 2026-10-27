"""Cross-platform local launcher: create environment, install locked dependencies, discover services."""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
import tomllib
import venv
from pathlib import Path

from settings import is_link, subprocess_environment


def dependency_fingerprint(root, lockfile=None):
    """Describe verified wheels independently of application version or location."""
    root = Path(root).resolve()
    lockfile = Path(lockfile) if lockfile is not None else root / "requirements.lock"
    if not lockfile.is_absolute():
        lockfile = root / lockfile
    interpreter = "\0".join(
        (sys.version, sys.implementation.cache_tag or "", sys.platform, sysconfig.get_platform())
    ).encode()
    return hashlib.sha256(lockfile.read_bytes() + b"\0" + interpreter).hexdigest()


def application_fingerprint(root, dependencies):
    root = Path(root).resolve()
    return hashlib.sha256(
        (root / "pyproject.toml").read_bytes() + str(root).encode() + dependencies.encode()
    ).hexdigest()


def marker_matches(path, expected):
    if is_link(path):
        raise SystemExit("An installation marker is linked. Repair the application environment.")
    try:
        return (
            path.is_file()
            and path.stat().st_size <= 1024
            and path.read_text(encoding="utf-8").strip() == expected
        )
    except UnicodeError:
        return False


def save_marker(path, fingerprint):
    """An interrupted write must never look like a completed installation."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".aass-marker-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(fingerprint)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def browser_available(executable, root):
    """Probe the actual isolated browser, including the current Playwright cache."""
    probe = (
        "from tools.browser_session import BrowserSession; "
        "browser = BrowserSession([]); "
        "\ntry:\n assert browser.ask({'operation': 'probe'}) is True"
        "\nfinally:\n browser.close()\n"
    )
    try:
        result = subprocess.run(
            [str(executable), "-I", "-c", probe],
            cwd=root,
            env=subprocess_environment(),
            capture_output=True,
            timeout=75,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def setup_step(label, command, *, cwd=None, progress_interval=15):
    """Inherit console output and show liveness while an installer is quiet."""
    print(f"\n[AASS] {label}", flush=True)
    started = time.monotonic()
    environment = subprocess_environment()
    environment["PIP_CONFIG_FILE"] = os.devnull
    for name in (
        "PIP_TRUSTED_HOST",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_FIND_LINKS",
        "PIP_NO_INDEX",
    ):
        environment.pop(name, None)
    process = subprocess.Popen(command, cwd=cwd, env=environment)
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


def main(argv=None):
    root = Path(__file__).resolve().parent
    environment = root / ".venv"
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if sys.version_info < (3, 12):
        raise SystemExit("Install Python 3.12 or newer, then relaunch AASS.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument(
        "--dev", action="store_true", help="Install developer and PostgreSQL test dependencies"
    )
    parser.add_argument("--integration", action="store_true")
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Include the optional read-only PostgreSQL MCP driver",
    )
    args, remaining = parser.parse_known_args(argv)
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    print(f"[AASS] Python: {sys.executable}", flush=True)
    print(f"[AASS] Application version: {version}", flush=True)
    print(f"[AASS] Project: {root}", flush=True)
    if is_link(environment):
        raise SystemExit(
            "The application .venv must be a normal directory, not a link or junction."
        )
    if not executable.exists():
        print("[AASS] Creating virtual environment...", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    lockfile = root / (
        "requirements-dev.lock"
        if args.dev
        else "requirements-postgres.lock"
        if args.postgres
        else "requirements.lock"
    )
    dependencies = dependency_fingerprint(root, lockfile)
    application = application_fingerprint(root, dependencies)
    dependency_marker = environment / ".aass-dependencies"
    application_marker = environment / ".aass-application"
    browser_marker = environment / ".aass-browser"
    legacy_marker = environment / ".aass-installed"
    install_dependencies = not marker_matches(dependency_marker, dependencies)
    install_application = install_dependencies or not marker_matches(
        application_marker, application
    )
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
    if install_dependencies:
        # Invalidate before pip mutates anything. A partial failed upgrade must
        # not reuse an old success marker when source is rolled back.
        for marker in (dependency_marker, application_marker, browser_marker, legacy_marker):
            marker.unlink(missing_ok=True)
        setup_step(
            "Installing locked Python dependencies",
            [
                *pip,
                "install",
                "--force-reinstall",
                "--require-hashes",
                "--only-binary=:all:",
                "--index-url",
                "https://pypi.org/simple",
                "-r",
                str(lockfile),
            ],
            cwd=root,
        )
    else:
        print("[AASS] Reusing hash-locked Python dependencies.", flush=True)
    if install_application:
        application_marker.unlink(missing_ok=True)
        legacy_marker.unlink(missing_ok=True)
        setup_step(
            "Installing AASS application",
            [*pip, "install", "--no-deps", "--no-build-isolation", "-e", "."],
            cwd=root,
        )
    print("[AASS] Checking Chromium browser and installed cache...", flush=True)
    if not browser_available(executable, root):
        browser_marker.unlink(missing_ok=True)
        if os.environ.get("AASS_CHROMIUM_EXECUTABLE") or shutil.which("chromium"):
            raise SystemExit(
                "The configured/system Chromium did not pass its local check. Repair that browser or choose a valid AASS_CHROMIUM_EXECUTABLE."
            )
        setup_step(
            "Installing Chromium browser",
            [str(executable), "-u", "-m", "playwright", "install", "chromium"],
            cwd=root,
        )
        if not browser_available(executable, root):
            raise SystemExit(
                "Chromium was installed but could not start. Check browser permissions and required system libraries, then retry local preparation."
            )
    else:
        print("[AASS] Reusing verified Chromium browser.", flush=True)
    # Commit the phase markers together only after packages, application and
    # actual browser have passed. A browser-only repair does not reinstall wheels.
    save_marker(dependency_marker, dependencies)
    save_marker(application_marker, application)
    save_marker(browser_marker, dependencies)
    legacy_marker.unlink(missing_ok=True)
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
