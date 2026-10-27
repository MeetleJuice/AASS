"""Double-click installer coordinator. Python standard library only until setup completes."""

import argparse
import contextlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from initialize_aass import discover_api_keys, select_worker
from sandboxes.container import DEFAULT_SANDBOX_IMAGE
from settings import ollama_url, subprocess_environment

ROOT = Path(__file__).resolve().parent


class SetupProblem(RuntimeError):
    pass


@contextlib.contextmanager
def installation_lock(path):
    with Path(path).open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise SetupProblem(
                    "Another AASS installer is already running. Use that window."
                ) from None
        else:
            import fcntl

            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SetupProblem(
                    "Another AASS installer is already running. Use that window."
                ) from None
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class Installer:
    def __init__(self, root=ROOT, *, heartbeat=15, install_prerequisites=False):
        self.root = Path(root)
        self.state = self.root / ".aass"
        self.state.mkdir(exist_ok=True)
        self.log_path = self.state / (
            "setup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".log"
        )
        self.log = self.log_path.open("w", encoding="utf-8", buffering=1)
        self.logged_bytes = 0
        self.heartbeat = heartbeat
        self.install_prerequisites = install_prerequisites
        self.secret_values = [
            os.environ[name]
            for name in (
                "AASS_JUDGE_API_KEY",
                "OPENAI_API_KEY",
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
                "ANTHROPIC_API_KEY",
                "AASS_POSTGRES_DSN",
            )
            if os.environ.get(name)
        ]

    def redact(self, text):
        for value in sorted(self.secret_values, key=len, reverse=True):
            text = text.replace(value, "[REDACTED]")
        text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)
        text = re.sub(
            r"(?i)([?&](?:token|key|api_key|access_token|password)=)[^&\s]+", r"\1[REDACTED]", text
        )
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)

    def write_log(self, text):
        remaining = max(0, 10 * 1024 * 1024 - self.logged_bytes)
        data = text.encode("utf-8")[:remaining]
        self.log.write(data.decode("utf-8", errors="ignore"))
        self.logged_bytes += len(data)

    def say(self, message):
        text = self.redact(str(message))
        print(text, flush=True)
        self.write_log(text + "\n")

    def status(self, state, **fields):
        report = {"status": state, "log": str(self.log_path), **fields}
        temporary = self.state / "setup-status.tmp"
        temporary.write_text(self.redact(json.dumps(report, indent=2)), encoding="utf-8")
        temporary.replace(self.state / "setup-status.json")

    @staticmethod
    def stop_process(process):
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
                check=False,
            )
        else:
            import signal

            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)

    def run(self, label, command, *, timeout=1200, check=True, visible=True, credentials=False):
        if visible:
            self.say("\n[AASS] " + label)
        started = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=os.name != "nt",
            env=subprocess_environment(credentials=credentials),
        )
        lines = queue.Queue(maxsize=256)

        def read():
            try:
                for line in process.stdout:
                    lines.put(line[:16384])
            finally:
                process.stdout.close()
                lines.put(None)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        output, last_tick, ended = "", started, False
        try:
            while not ended or process.poll() is None:
                now = time.monotonic()
                if now - started > timeout:
                    raise SetupProblem(
                        f"{label} exceeded {timeout}s. Rerun Install-AASS.bat to retry this step; see the log."
                    )
                try:
                    line = lines.get(timeout=min(0.25, self.heartbeat))
                    if line is None:
                        ended = True
                    else:
                        safe = self.redact(line.rstrip())
                        output = (output + safe + "\n")[-262144:]
                        if visible:
                            self.say(safe)
                        else:
                            self.write_log(safe + "\n")
                except queue.Empty:
                    pass
                if visible and now - last_tick >= self.heartbeat:
                    self.say(f"[AASS] Still working: {label} ({int(now - started)}s).")
                    last_tick = now
            code = process.wait()
        except BaseException:
            self.stop_process(process)
            raise
        if code and check:
            raise SetupProblem(
                f"{label} failed (exit {code}). The error is above and in {self.log_path}"
            )
        return code, output

    def locate(self, name, candidates=()):
        return shutil.which(name) or next((str(p) for p in candidates if p.is_file()), None)

    def winget(self, package):
        if not self.install_prerequisites:
            raise SetupProblem(
                f"{package} is missing. Install it from its official publisher, or explicitly rerun with --install-prerequisites. Existing applications are never reinstalled automatically."
            )
        manager = shutil.which("winget")
        if not manager:
            raise SetupProblem(
                f"{package} is missing. Install it, or install Microsoft App Installer to enable automatic installation."
            )
        self.run(
            "Installing " + package,
            [
                manager,
                "install",
                "--id",
                package,
                "--exact",
                "--source",
                "winget",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ],
            timeout=1200,
        )

    def docker(self):
        base = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker"
        binary = self.locate("docker", [base / "resources/bin/docker.exe"])
        if not binary and os.name == "nt":
            self.winget("Docker.DockerDesktop")
            binary = self.locate("docker", [base / "resources/bin/docker.exe"])
        if not binary:
            raise SetupProblem(
                "Docker is not installed. Install Docker Desktop (Linux containers) and rerun."
            )
        os.environ["PATH"] = str(Path(binary).parent) + os.pathsep + os.environ.get("PATH", "")

        def probe():
            code, output = self.run(
                "Checking Docker engine",
                [binary, "info", "--format", "{{.OSType}}"],
                timeout=15,
                check=False,
                visible=False,
            )
            return output.strip() if code == 0 else None

        kind = probe()
        if kind is None and os.name == "nt" and (base / "Docker Desktop.exe").is_file():
            self.say(
                "[AASS] Starting Docker Desktop. Complete any first-run prompts in its window."
            )
            subprocess.Popen(
                [str(base / "Docker Desktop.exe")],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=subprocess_environment(),
            )
            deadline = time.monotonic() + 180
            while kind is None and time.monotonic() < deadline:
                self.say("[AASS] Waiting for the Docker engine...")
                time.sleep(3)
                kind = probe()
        if kind is None:
            raise SetupProblem(
                "Docker engine is unavailable. Finish Docker Desktop setup. If it requests WSL, Virtual Machine Platform or a Windows restart, complete that and rerun Install-AASS.bat. No reboot is triggered automatically."
            )
        if kind != "linux":
            raise SetupProblem(
                "Switch Docker Desktop to Linux containers, then rerun Install-AASS.bat."
            )
        self.say("[AASS] Docker engine is running.")
        image = os.environ.get("AASS_SANDBOX_IMAGE", DEFAULT_SANDBOX_IMAGE)
        code, _ = self.run(
            "Checking sandbox image",
            [binary, "image", "inspect", "--format", "{{.Id}}", image],
            timeout=20,
            check=False,
            visible=False,
        )
        if code:
            self.run("Downloading verified sandbox image", [binary, "pull", image], timeout=1800)

    def ollama(self):
        host = ollama_url()
        os.environ["OLLAMA_HOST"] = host

        def tags():
            try:
                with urllib.request.urlopen(host + "/api/tags", timeout=3) as response:  # nosec B310 # validated by ollama_url
                    data = json.loads(response.read(262144))
                    return [item["name"] for item in data.get("models", [])]
            except (OSError, ValueError, KeyError):
                return None

        models = tags()
        candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"]
        binary = self.locate("ollama", candidates)
        if models is None:
            if urllib.parse.urlsplit(host).hostname not in ("localhost", "127.0.0.1", "::1"):
                raise SetupProblem(
                    "The configured remote OLLAMA_HOST is unreachable. Check that service."
                )
            if not binary and os.name == "nt":
                self.winget("Ollama.Ollama")
                binary = self.locate("ollama", candidates)
            if not binary:
                raise SetupProblem("Install and start Ollama, then rerun the installer.")
            self.say("[AASS] Starting the installed Ollama service...")
            subprocess.Popen(
                [binary, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=subprocess_environment(),
            )
            deadline = time.monotonic() + 45
            while models is None and time.monotonic() < deadline:
                time.sleep(2)
                models = tags()
            if models is None:
                raise SetupProblem(
                    "Ollama did not become ready. Open the Ollama application and rerun."
                )
        model = select_worker(models)
        if model not in models:
            if not binary:
                raise SetupProblem(
                    "No usable local model. Install qwen3.5:9b using your Ollama service."
                )
            self.run("Downloading worker model " + model, [binary, "pull", model], timeout=3600)
        self.say("[AASS] Selected local worker: " + model)

    def install(self, *, skip_live=True):
        self.status("installing")
        self.say("AASS automatic setup. Existing installations and models will be reused.")
        self.say("Setup log: " + str(self.log_path))
        self.docker()
        self.ollama()
        self.run(
            "Installing AASS dependencies and browser",
            [sys.executable, "-u", "launch_aass.py", "--install-only"],
            timeout=1800,
        )
        runtime = self.root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.run(
            "Checking installed package consistency",
            [str(runtime), "-m", "pip", "check"],
            timeout=60,
        )
        self.run(
            "Testing real sandbox execution and isolation",
            [str(runtime), "-u", "install_aass.py", "--sandbox-smoke"],
            timeout=150,
        )
        code, text = self.run(
            "Checking browser, local model and credential discovery",
            [str(runtime), "-m", "orchestration_canvas", "doctor"],
            timeout=90,
            check=False,
            visible=False,
            credentials=True,
        )
        try:
            report = json.loads(text)
        except ValueError:
            raise SetupProblem(
                "Readiness command did not produce a valid report. See the setup log."
            ) from None
        checks = report.get("checks", {})
        for name, result in checks.items():
            self.say(f"  {name}: {'OK' if result.get('ready') else 'NEEDS ATTENTION'}")
        local_checks = ("ollama_worker", "docker", "sandbox_image", "chromium")
        if any(not checks.get(name, {}).get("ready") for name in local_checks):
            self.status("installed_local_check_failed", checks=checks)
            self.say(
                "Local installation needs attention. Fix the named local check above; cloud configuration is separate."
            )
            return 2
        if code or not report.get("ready"):
            self.status("installed_needs_configuration", checks=checks)
            if not checks.get("judge_configuration", {}).get("ready"):
                self.say(
                    "LOCAL INSTALLATION COMPLETE. No usable independent judge configuration was found."
                )
                self.say(
                    "Your private .env needs OPENAI_API_KEY, GEMINI_API_KEY or ANTHROPIC_API_KEY; or AASS_JUDGE_API_KEY with AASS_JUDGE_MODEL. Keep values private. Choose your private file and provider in the setup window, then Test connections; no reinstall is required."
                )
            else:
                self.say(
                    "AASS is installed, but a readiness check failed. See the named check above and setup log."
                )
            return 0
        if skip_live:
            self.status("installed_live_unverified", checks=checks)
            self.say(
                "Installation checks passed. Live model verification is separate from installation."
            )
            self.say(
                "Local prerequisites verified. Use Test connections in the setup window to verify generation and cloud access."
            )
            return 0
        self.say(
            "Running real local worker and independent cloud review checks (provider charges may apply)."
        )
        live_code, live_text = self.run(
            "Verifying live model connections",
            [str(runtime), "-m", "orchestration_canvas", "verify-live"],
            timeout=300,
            check=False,
            credentials=True,
        )
        if live_code:
            self.status("installed_cloud_unverified", checks=checks)
            self.say(
                "AASS is installed. A model connection was rejected or unavailable; see the service/status above. Fix that account/service in the setup window, then retry the connection check. Do not reinstall packages."
            )
            return 0
        self.status("ready", checks=checks)
        self.say("SETUP COMPLETE. Double-click Start-AASS.bat to choose a project and task.")
        return 0


def sandbox_smoke():
    from sandboxes.container import ContainerSandbox

    with tempfile.TemporaryDirectory(prefix="aass-ready-") as directory:
        root = Path(directory)
        (root / ".env").write_text("AASS_SENTINEL=must-not-reach-container\n")
        (root / "test_ready.py").write_text(
            "import pathlib, socket, unittest\n"
            "class Ready(unittest.TestCase):\n"
            " def test_isolation(self):\n"
            '  self.assertFalse(pathlib.Path("/workspace/.env").exists())\n'
            '  self.assertFalse(pathlib.Path("/var/run/docker.sock").exists())\n'
            '  with self.assertRaises(OSError): pathlib.Path("/workspace/blocked").write_text("no")\n'
            '  with self.assertRaises(OSError): socket.create_connection(("1.1.1.1",443),timeout=1)\n'
        )
        result = ContainerSandbox(
            root, image=os.environ.get("AASS_SANDBOX_IMAGE", DEFAULT_SANDBOX_IMAGE)
        ).run(["python", "-m", "unittest", "discover", "-v"])
        print(result.stdout + result.stderr, flush=True)
        return 0 if result.returncode == 0 and "Ran 1 test" in result.stderr else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    live = parser.add_mutually_exclusive_group()
    live.add_argument(
        "--verify-live", action="store_true", help="Also make paid model verification requests"
    )
    live.add_argument("--skip-live", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sandbox-smoke", action="store_true")
    parser.add_argument(
        "--install-prerequisites",
        action="store_true",
        help="Explicitly allow official winget prerequisite installations",
    )
    args = parser.parse_args()
    if args.sandbox_smoke:
        return sandbox_smoke()
    try:
        discover_api_keys(configure=False)
    except (OSError, ValueError):
        print(
            "Private credential-file selection needs attention. Local installation will continue; choose your file again in the setup window.",
            flush=True,
        )
    installer = Installer(install_prerequisites=args.install_prerequisites)
    acquired = False
    try:
        with installation_lock(installer.state / "setup.lock"):
            acquired = True
            result = installer.install(skip_live=not args.verify_live)
            if (
                result == 0
                and os.name == "nt"
                and (installer.state / "managed-install.json").is_file()
            ):
                from desktop_integration import create_shortcut

                installer.say("[AASS] Creating your custom AASS desktop icon...")
                shortcut = create_shortcut(installer.root)
                installer.say("[AASS] Desktop icon ready: " + str(shortcut))
                atomic = {"path": str(shortcut), "ready": True}
                from telemetry import atomic_json

                atomic_json(installer.state / "shortcut.json", atomic)
            return result
    except KeyboardInterrupt:
        installer.say("Setup cancelled. Double-click Install-AASS.bat to retry.")
        installer.status("cancelled")
        return 130
    except (SetupProblem, OSError, subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, SetupProblem) else type(error).__name__
        installer.say("SETUP STOPPED: " + reason)
        if acquired:
            installer.status("blocked", reason=reason)
        return 2
    finally:
        installer.log.close()


if __name__ == "__main__":
    raise SystemExit(main())
