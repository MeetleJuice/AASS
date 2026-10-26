"""Ephemeral Docker execution over a secret-filtered read-only source snapshot."""

import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from circuit_breaker import SafetyStop
from settings import is_link

COMMAND_BLACKLIST = frozenset(
    {
        "rm",
        "sudo",
        "su",
        "curl",
        "wget",
        "ssh",
        "scp",
        "nc",
        "bash",
        "sh",
        "zsh",
        "eval",
        "exec",
        "mount",
        "docker",
    }
)
ALLOWED_PREFIXES = (
    ("python", "-m", "pytest"),
    ("python", "-m", "unittest"),
    ("python", "-m", "compileall"),
)
DEFAULT_SANDBOX_IMAGE = (
    "python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704"
)
MAX_OUTPUT_BYTES = 64 * 1024
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
EXCLUDED_DIRS = {"__pycache__", "node_modules", "generated", "build", "dist"}


@dataclass(frozen=True)
class ExecutionResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    output_limited: bool = False


def validate_command(command):
    if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
        raise SafetyStop("Command must be an argument array")
    if len(command) > 64 or sum(map(len, command)) > 8192:
        raise SafetyStop("Command exceeds size limit")
    if any(
        Path(arg).name in COMMAND_BLACKLIST
        or any(s in arg for s in (";", "&&", "||", "`", "$(", "\n", "\x00"))
        for arg in command
    ):
        raise SafetyStop("Blacklisted command or shell syntax")
    if not any(tuple(command[: len(prefix)]) == prefix for prefix in ALLOWED_PREFIXES):
        raise SafetyStop("Command is outside the test/compile allowlist")
    if any(arg in ("-c", "--override-ini", "-o", "-p") for arg in command[3:]):
        raise SafetyStop("Interpreter/plugin override forbidden")


def snapshot(source, destination):
    total, count = 0, 0
    for directory, dirs, files in os.walk(source, followlinks=False):
        base = Path(directory)
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".")
            and d not in EXCLUDED_DIRS
            and not is_link(base / d)
            and not any(x in d.lower() for x in ("secret", "credential"))
        ]
        relative = base.relative_to(source)
        target = destination / relative
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            path = base / name
            if (
                is_link(path)
                or not path.is_file()
                or path.stat().st_nlink > 1
                or name.startswith(".")
                or path.suffix.lower() in (".env", ".pem", ".key")
                or name == "trajectory.json"
                or any(x in name.lower() for x in ("secret", "credential", "token"))
            ):
                continue
            count += 1
            total += path.stat().st_size
            if total > MAX_SNAPSHOT_BYTES or count > 5000:
                raise SafetyStop("Sandbox source snapshot exceeds hard limit")
            shutil.copyfile(path, target / name)


class ContainerSandbox:
    def __init__(self, workspace, image=DEFAULT_SANDBOX_IMAGE, timeout=60):
        self.workspace = Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("Workspace must be a directory")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}", image):
            raise SafetyStop("Invalid sandbox image reference")
        self.image = image
        self.timeout = min(max(timeout, 1), 120)

    def run(self, command):
        validate_command(command)
        name = "aass-" + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="aass-sandbox-") as scratch:
            source = Path(scratch) / "source"
            source.mkdir()
            snapshot(self.workspace, source)
            args = [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=64",
                "--memory=512m",
                "--cpus=1",
                "--ulimit",
                "fsize=65536:65536",
                "--user",
                f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "1000:1000",
                "--tmpfs",
                "/tmp:rw,nosuid,size=64m",  # nosec B108 # private container tmpfs, not a host temp path
                "--mount",
                f"type=bind,src={source},dst=/workspace,readonly",
                "--workdir",
                "/workspace",
                "--env",
                "PYTHONDONTWRITEBYTECODE=1",
                "--env",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                self.image,
                *command,
            ]
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            exceeded = threading.Event()
            buffers = [bytearray(), bytearray()]

            def drain(pipe, buffer):
                while chunk := pipe.read(4096):
                    room = max(0, MAX_OUTPUT_BYTES - len(buffer))
                    buffer.extend(chunk[:room])
                    if len(chunk) > room:
                        exceeded.set()
                        proc.kill()
                        break
                pipe.close()

            readers = [
                threading.Thread(target=drain, args=(stream, buffer), daemon=True)
                for stream, buffer in zip((proc.stdout, proc.stderr), buffers, strict=True)
            ]
            for reader in readers:
                reader.start()
            timed_out = False
            try:
                proc.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()
                proc.wait()
            finally:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
                for reader in readers:
                    reader.join(timeout=5)
            return ExecutionResult(
                124 if timed_out else (125 if exceeded.is_set() else proc.returncode),
                buffers[0].decode(errors="replace"),
                buffers[1].decode(errors="replace"),
                timed_out,
                exceeded.is_set(),
            )
