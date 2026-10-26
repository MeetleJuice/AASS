"""Simple terminal entry point for choosing a local engineering project and task."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    runtime = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not runtime.is_file():
        print("First double-click Install-AASS.bat to set up this application.")
        return 2
    print("AASS - local engineering workspace\n")
    print("1. Run a task\n2. Check readiness\n3. Show last installation status\n4. Exit")
    choice = input("Choose [1-4]: ").strip()
    if choice == "4":
        return 0
    if choice == "3":
        path = ROOT / ".aass/setup-status.json"
        print(path.read_text() if path.exists() else "No installer status yet.")
        return 0
    if choice == "2":
        return subprocess.run(
            [str(runtime), "-m", "orchestration_canvas", "doctor"], cwd=ROOT, check=False
        ).returncode
    if choice != "1":
        print("Please launch again and select 1, 2, 3 or 4.")
        return 2
    project = (
        Path(input("Full path to your project folder: ").strip().strip('"')).expanduser().resolve()
    )
    if project == ROOT or ROOT.is_relative_to(project):
        print("Choose a separate project folder, outside the AASS runtime.")
        return 2
    task = input("What should AASS build or fix? ").strip()
    if not task:
        print("A task is required.")
        return 2
    project.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [
            str(runtime),
            "-m",
            "orchestration_canvas",
            "run",
            "--workspace",
            str(project),
            "--task",
            task,
        ],
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        raise SystemExit(130) from None
    except OSError as error:
        print("Unable to open the selected project: " + type(error).__name__)
        raise SystemExit(2) from None
