"""Build a source distribution ZIP with an explicit manifest; never package local state."""

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "requirements.lock",
    ".env.example",
    ".gitignore",
    "initialize_aass.py",
    "launch_aass.py",
    "Launch-AASS.cmd",
    "Install-AASS.bat",
    "Start-AASS.bat",
    "Check-Connections.bat",
    "INSTALL-FIRST.txt",
    "install_aass.py",
    "local_app.py",
    "launch-aass.sh",
    "circuit_breaker.py",
    "worker_agent.py",
    "stall_detector.py",
    "judge_evaluator.py",
    "orchestration_canvas.py",
    "crdal_supervisor.py",
    "telemetry.py",
    ".github/workflows/verify.yml",
]
DIRECTORIES = ["tools", "sandboxes", "tests", "scripts", "docs", "examples"]


def build():
    destination = ROOT / "dist/AASS-1.0.0.zip"
    destination.parent.mkdir(exist_ok=True)
    files = [ROOT / name for name in FILES]
    files += [
        p
        for directory in DIRECTORIES
        for p in (ROOT / directory).rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix in (".py", ".sh", ".md", ".json")
    ]
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            if path.is_symlink():
                raise ValueError("Refusing to package a symlink")
            archive.write(path, "AASS-1.0.0/" + path.relative_to(ROOT).as_posix())
    print(destination)
    return destination


if __name__ == "__main__":
    build()
