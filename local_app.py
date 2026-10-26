"""Simple terminal entry point for choosing a local engineering project and task."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def menu_action():
    runtime = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not runtime.is_file():
        print("First double-click Install-AASS.bat to set up this application.")
        return 2
    print("AASS - local engineering workspace\n")
    print(
        "1. Run a task\n2. Check readiness\n3. Show last installation status\n"
        "4. Choose cloud provider\n5. Check model connections (may incur API charges)\n6. Exit"
    )
    choice = input("Choose [1-6]: ").strip()
    if choice == "6":
        return None
    if choice == "4":
        from settings import save_provider_preferences

        print("Choose the provider whose API key you want to use. Keys stay in your private file.")
        service = input("Provider [auto/openai/gemini/anthropic]: ").strip().lower()
        model = input("Model name (Enter for provider default): ").strip()
        save_provider_preferences(service, model)
        print(
            "Provider preference saved. Select Check model connections next; no reinstall is needed."
        )
        return 0
    if choice == "5":
        return subprocess.run(
            [str(runtime), "-m", "orchestration_canvas", "verify-live"], cwd=ROOT, check=False
        ).returncode
    if choice == "3":
        path = ROOT / ".aass/setup-status.json"
        print(path.read_text() if path.exists() else "No installer status yet.")
        return 0
    if choice == "2":
        return subprocess.run(
            [str(runtime), "-m", "orchestration_canvas", "doctor"], cwd=ROOT, check=False
        ).returncode
    if choice != "1":
        print("Please launch again and select an option from 1 through 6.")
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


def main():
    runtime = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not runtime.is_file():
        print("First double-click Install-AASS.bat to set up this application.")
        return 2
    while True:
        result = menu_action()
        if result is None:
            return 0
        input("\nPress Enter to return to the menu...")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        raise SystemExit(130) from None
    except (OSError, ValueError) as error:
        print("Unable to open the selected project: " + type(error).__name__)
        raise SystemExit(2) from None
