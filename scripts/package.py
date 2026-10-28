"""Build one deterministic, manifest-verified source release. Never build patch executables."""

import argparse
import hashlib
import json
import subprocess
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "README.md",
    "pulse/manifest.json",
    "docs/PULSE-PLAN.md",
    "docs/PULSE.md",
    "LICENSE",
    "pyproject.toml",
    "requirements.lock",
    "requirements-postgres.lock",
    "examples/postgres-mcp.json",
    "examples/http-mcp.json",
    ".env.example",
    "initialize_aass.py",
    "settings.py",
    "launch_aass.py",
    "Launch-AASS.cmd",
    "Install-AASS.bat",
    "Start-AASS.bat",
    "INSTALL-FIRST.txt",
    "install_aass.py",
    "local_app.py",
    "setup_api.py",
    "setup_automation.py",
    "provider_registry.py",
    "setup_controller.py",
    "setup_wizard.py",
    "update_manager.py",
    "app_lifecycle.py",
    "desktop_bootstrap.py",
    "desktop_launcher.py",
    "desktop_integration.py",
    "assets/aass.ico",
    "assets/aass.svg",
    "launch-aass.sh",
    "circuit_breaker.py",
    "worker_agent.py",
    "stall_detector.py",
    "judge_evaluator.py",
    "orchestration_canvas.py",
    "crdal_supervisor.py",
    "telemetry.py",
    "verify_release.py",
    "docs/WINDOWS-INSTALL.md",
    "docs/FIRST-TASK.md",
    "docs/AUTOMATIC-SETUP.md",
    "docs/RELEASE-READINESS.md",
    "docs/SECURITY-REVIEW.md",
    "docs/RELEASE-NOTES.md",
    "docs/OPERATIONS.md",
    "docs/REMEDIATION-PLAN.md",
    "docs/VALIDATION.md",
    "docs/ARCHITECTURE.md",
    "docs/SETUP-SIMPLIFICATION-PLAN.md",
    "docs/INSTALL-UPDATE-PLAN.md",
]


def build(root=ROOT, *, allow_dirty=False):
    root = Path(root)
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    )
    revision = result.stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    if dirty and not allow_dirty:
        raise ValueError("Commit the reviewed source before producing a release artifact")
    paths = set(FILES)
    paths.update(
        p.relative_to(root).as_posix()
        for folder in ("tools", "sandboxes", "pulse")
        for p in (root / folder).glob("*.py")
    )
    content = {}
    for name in sorted(paths):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing or symlinked release source: " + name)
        data = path.read_bytes()
        if path.suffix.lower() != ".ico":
            data = data.replace(b"\r\n", b"\n")
        if name.endswith((".bat", ".cmd")):
            data = data.replace(b"\n", b"\r\n")
        content[name] = data
    manifest = {
        "format": 1,
        "version": version,
        "source_revision": revision,
        "dirty": dirty,
        "publisher_signature": "unsigned-source",
        "antivirus": "See the separate release scan report for this archive SHA-256",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in content.items()},
    }
    content["RELEASE-MANIFEST.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode()
    destination = root / f"dist/AASS-{version}.zip"
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(content.items()):
            info = zipfile.ZipInfo(f"AASS-{version}/" + name, date_time=(2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
            archive.writestr(info, data)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    (destination.parent / "SHA256SUMS").write_text(digest + "  " + destination.name + "\n")
    print(destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-dirty", action="store_true", help="Local candidate only; cannot be published"
    )
    build(allow_dirty=parser.parse_args().allow_dirty)
