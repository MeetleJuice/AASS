"""One-window setup and task launcher. No generation requests run at startup."""

import argparse
import json
import queue
import re
import threading
import webbrowser
from pathlib import Path

from settings import (
    provider_preferences,
    save_credentials_file,
    save_provider_preferences,
)
from setup_controller import ControllerError, SetupController

ROOT = Path(__file__).resolve().parent
SERVICES = {"Gemini": "gemini", "OpenAI": "openai", "Anthropic": "anthropic"}


def preferred_model(models, saved=""):
    """Choose only from returned IDs; preserve an available operator preference."""
    ids = [entry["id"] for entry in models]
    for candidate in (saved, "gemini-flash-latest", "gpt-4.1", "claude-sonnet-4-5"):
        if candidate in ids:
            return candidate
    stable_flash = [model for model in ids if re.fullmatch(r"gemini-\d+(?:\.\d+)?-flash", model)]
    if stable_flash:
        return max(
            stable_flash, key=lambda model: tuple(int(n) for n in model.split("-")[1].split("."))
        )
    return ids[0] if ids else ""


class SetupWizard:
    def __init__(self, window, *, root=ROOT, controller=None, auto_install=False, smoke=False):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk, self.window = tk, ttk, window
        self.root = Path(root)
        self.controller = controller or SetupController(self.root)
        self.events = queue.Queue()
        self.busy = False
        self.closing = False
        self.worker_passed = False
        self.cloud_passed = False
        self.models = []
        self.available = set()
        self.buttons = []
        self.local_ready = False
        self.preferences = {}
        try:
            self.preferences = provider_preferences(self.root)
        except (OSError, ValueError):
            pass
        window.title("AASS - setup and workspace")
        width = min(900, max(560, window.winfo_screenwidth() - 60))
        height = min(800, max(450, window.winfo_screenheight() - 100))
        self.wrap_width = width - 85
        window.geometry(f"{width}x{height}")
        window.minsize(min(680, width), min(500, height))
        window.protocol("WM_DELETE_WINDOW", self.close)
        main = ttk.Frame(window, padding=18)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="AASS", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        ttk.Label(
            main, text="Prepare this PC, connect your models, then choose what to build."
        ).pack(anchor="w", pady=(0, 12))
        self.notice = tk.StringVar(value="Ready. Your existing tools and models will be reused.")
        ttk.Label(main, textvariable=self.notice, wraplength=self.wrap_width).pack(
            fill="x", pady=(0, 8)
        )
        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.pack(fill="x")
        tabs = ttk.Notebook(main)
        tabs.pack(fill="both", expand=True, pady=12)
        setup_tab, setup = self.scrollable_tab(tabs)
        task_tab, task = self.scrollable_tab(tabs)
        tabs.add(setup_tab, text="1. Setup")
        tabs.add(task_tab, text="2. Run a task")
        self.tabs, self.task_tab = tabs, task_tab

        self.local_status = tk.StringVar(
            value="Prepare local tools first. No paid API calls are made during this step."
        )
        try:
            status_file = self.root / ".aass/setup-status.json"
            if status_file.is_file() and status_file.stat().st_size <= 65536:
                last_status = json.loads(status_file.read_text(encoding="utf-8")).get("status")
                if last_status in {
                    "ready",
                    "installed_needs_configuration",
                    "installed_live_unverified",
                    "installed_cloud_unverified",
                }:
                    self.local_ready = True
                    self.local_status.set(
                        "Previous local installation checks passed. Prepare / check can refresh them without replacing your tools."
                    )
        except (OSError, ValueError, AttributeError):
            pass
        self.section(setup, "Local tools", self.local_status)
        row = ttk.Frame(setup)
        row.pack(fill="x", pady=(4, 12))
        self.button(row, "Prepare / check this PC", self.install).pack(side="left")
        self.button(row, "Docker / Windows help", self.docker_help).pack(side="left", padx=8)

        self.credential_status = tk.StringVar(
            value="Looks for .env or .env.txt beside this app and your Desktop credential files."
        )
        self.section(setup, "Your private credential file", self.credential_status)
        row = ttk.Frame(setup)
        row.pack(fill="x", pady=(4, 12))
        self.button(row, "Choose existing .env / text file...", self.choose_file).pack(side="left")
        self.button(row, "Refresh detection", self.refresh).pack(side="left", padx=8)

        self.provider = tk.StringVar()
        self.model = tk.StringVar()
        row = ttk.Frame(setup)
        row.pack(fill="x")
        ttk.Label(row, text="Cloud provider").grid(row=0, column=0, sticky="w")
        ttk.Label(row, text="Available text model").grid(row=0, column=1, sticky="w", padx=12)
        self.provider_box = ttk.Combobox(
            row, textvariable=self.provider, values=list(SERVICES), state="readonly", width=16
        )
        self.provider_box.grid(row=1, column=0, sticky="ew", pady=4)
        self.provider_box.bind("<<ComboboxSelected>>", self.provider_changed)
        self.model_box = ttk.Combobox(row, textvariable=self.model, state="readonly", width=45)
        self.model_box.grid(row=1, column=1, sticky="ew", padx=12, pady=4)
        self.model_box.bind("<<ComboboxSelected>>", self.model_changed)
        row.columnconfigure(1, weight=1)
        self.button(row, "Load models", self.load_models).grid(row=1, column=2)
        ttk.Label(
            setup,
            text="The list comes from the provider. A listed model still needs usable API access and quota.",
            wraplength=800,
        ).pack(anchor="w", pady=(2, 10))
        self.connection_status = tk.StringVar(
            value="Connection checks are optional and may incur API charges. Tasks also use your API account."
        )
        self.section(setup, "Model connections", self.connection_status)
        row = ttk.Frame(setup)
        row.pack(fill="x", pady=6)
        self.button(row, "Test connections (uses API)", self.check_connections).pack(side="left")
        self.button(row, "Continue to task >", lambda: tabs.select(task_tab)).pack(
            side="left", padx=8
        )

        ttk.Label(task, text="Choose a project folder outside this AASS application.").pack(
            anchor="w"
        )
        row = ttk.Frame(task)
        row.pack(fill="x", pady=8)
        self.target = tk.StringVar()
        ttk.Entry(row, textvariable=self.target).pack(side="left", fill="x", expand=True)
        self.button(row, "Browse...", self.choose_target).pack(side="left", padx=(8, 0))
        ttk.Label(task, text="What should AASS build or fix?").pack(anchor="w")
        self.task_text = tk.Text(task, height=9, wrap="word")
        self.task_text.pack(fill="both", expand=True, pady=8)
        self.button(task, "Run task (uses API)", self.run_task).pack(anchor="w")
        ttk.Label(
            task,
            text="Progress appears below. Completion still requires tests and the independent cloud review.",
            wraplength=800,
        ).pack(anchor="w", pady=8)

        bottom = ttk.Frame(main)
        bottom.pack(fill="x")
        ttk.Label(bottom, text="Progress and next actions").pack(side="left")
        self.cancel_button = ttk.Button(
            bottom, text="Cancel current operation", command=self.cancel, state="disabled"
        )
        self.cancel_button.pack(side="right")
        logs = ttk.Frame(main)
        logs.pack(fill="both", pady=(6, 0))
        self.log = tk.Text(logs, height=7, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(logs, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.poll_id = window.after(100, self.poll)
        if not smoke:
            if auto_install:
                window.after(150, self.install)
            elif self.controller.runtime.is_file():
                window.after(150, self.refresh)
            else:
                self.notice.set("Click Prepare / check this PC to start. Keep Docker Desktop open.")

    def scrollable_tab(self, parent):
        outer = self.ttk.Frame(parent)
        canvas = self.tk.Canvas(outer, highlightthickness=0)
        scrollbar = self.ttk.Scrollbar(outer, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = self.ttk.Frame(canvas, padding=12)
        item = canvas.create_window(0, 0, anchor="nw", window=content)
        content.bind(
            "<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
        return outer, content

    def section(self, parent, title, variable):
        self.ttk.Label(parent, text=title, font=("Segoe UI", 11, "bold")).pack(
            anchor="w", pady=(3, 2)
        )
        self.ttk.Label(parent, textvariable=variable, wraplength=self.wrap_width).pack(anchor="w")

    def button(self, parent, text, command):
        button = self.ttk.Button(parent, text=text, command=command)
        self.buttons.append(button)
        return button

    def append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", str(text).rstrip() + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 1200:
            self.log.delete("1.0", "300.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def start(self, label, operation, done):
        if self.busy:
            return
        self.busy = True
        self.notice.set(label)
        self.progress.start(12)
        for button in self.buttons:
            button.configure(state="disabled")
        self.provider_box.configure(state="disabled")
        self.model_box.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.append(label)

        def work():
            try:
                result = operation()
            except ControllerError as error:
                result = {
                    "status": "error",
                    "code": error.code,
                    "message": str(error),
                    "hint": "Correct this issue, then retry the step. Local packages can be reused.",
                }
            except Exception as error:
                # Never render raw exception text: it can contain a URL or credential.
                result = {
                    "status": "error",
                    "code": type(error).__name__,
                    "message": "This step could not finish.",
                    "hint": "Check the progress above. Retry this step after correcting the reported prerequisite.",
                }
            self.events.put(("done", (done, result)))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        if self.closing and self.busy:
            self.controller.cancel()
        try:
            for _ in range(100):
                kind, payload = self.events.get_nowait()
                if kind == "line":
                    self.append(payload)
                else:
                    self.busy = False
                    self.progress.stop()
                    for button in self.buttons:
                        button.configure(state="normal")
                    self.provider_box.configure(state="readonly")
                    self.model_box.configure(state="readonly")
                    self.cancel_button.configure(state="disabled")
                    if self.closing:
                        self.window.destroy()
                        return
                    done, result = payload
                    try:
                        done(result)
                    except (OSError, ValueError, KeyError, TypeError):
                        self.notice.set(
                            "Settings could not be saved. Check that the extracted application folder is writable."
                        )
        except queue.Empty:
            pass
        self.poll_id = self.window.after(100, self.poll)

    def stream(self, line):
        self.events.put(("line", line))

    def error(self, report):
        message = report.get("message", "The connection did not pass.")
        hint = report.get("hint", "Check this provider's configuration, then retry.")
        status = report.get("http_status")
        text = message + (f" (HTTP {status})" if status else "") + " " + hint
        if report.get("model"):
            context = (
                "Provider: "
                + report.get("service", self.provider.get())
                + "; model: "
                + report["model"]
            )
            if report.get("api_route"):
                context += "; API: " + report["api_route"]
            if report.get("provider_code"):
                context += "; code: " + report["provider_code"]
            self.append(context)
        self.notice.set(text)
        self.connection_status.set(text)
        self.append(text)

    def install(self):
        self.worker_passed = self.cloud_passed = False
        self.start(
            "Preparing local tools. Downloads may take several minutes; progress appears below.",
            lambda: self.controller.install(self.stream),
            self.installed,
        )

    def installed(self, result):
        if isinstance(result, dict):
            self.local_ready = False
            self.error(result)
            return
        if not result.ok:
            self.local_ready = False
            self.local_status.set(
                "Local setup needs attention. The final stage in the progress below explains what to fix. Then click Prepare / check again."
            )
            self.notice.set(
                "Local setup stopped. For Docker virtualization / WSL issues, use Docker / Windows help."
            )
            return
        self.local_ready = True
        self.local_status.set(
            "Local installation and sandbox/browser checks passed. Existing tools are ready."
        )
        self.notice.set("Local tools are ready. Finding your provider key...")
        self.refresh()

    def choose_file(self):
        from tkinter import filedialog, messagebox

        path = filedialog.askopenfilename(
            title="Choose your existing private credential file",
            initialdir=self.root,
            filetypes=[
                ("Credential or text files", "*.env *.txt"),
                ("All files (including .env)", "*"),
            ],
        )
        if not path:
            return
        try:
            save_credentials_file(path, self.root)
        except (OSError, ValueError):
            messagebox.showerror(
                "Choose another file",
                "Choose a readable, regular .env or text file no larger than 64 KiB.",
                parent=self.window,
            )
            return
        self.worker_passed = self.cloud_passed = False
        self.model.set("")
        self.models = []
        self.credential_status.set("Selected: " + str(path) + ". Key contents stay in that file.")
        if self.controller.runtime.is_file():
            self.refresh()
        else:
            self.notice.set("File selected. Click Prepare / check this PC next.")

    def refresh(self):
        if not self.controller.runtime.is_file():
            self.notice.set(
                "Prepare local tools first. You can choose your credential file before installing."
            )
            return
        self.worker_passed = self.cloud_passed = False
        self.models = []
        self.model.set("")
        self.model_box.configure(values=[])
        self.start(
            "Checking private key names (values are never displayed)...",
            lambda: self.controller.json_operation(["credentials"]),
            self.credentials_loaded,
        )

    def credentials_loaded(self, report):
        if report.get("status") != "ok":
            self.error(report)
            return
        if report.get("settings_warning"):
            self.append(report["settings_warning"])
        self.available = {p["id"] for p in report.get("providers", []) if p.get("key_present")}
        selected = report.get("selected_file")
        names = [label for label, service in SERVICES.items() if service in self.available]
        self.credential_status.set(
            (
                "Selected file: " + selected + ". "
                if selected
                else "Automatic file / environment detection. "
            )
            + (
                "Key found for: " + ", ".join(names)
                if names
                else "No supported provider key found. Choose your .env or .env.txt file."
            )
        )
        saved_service = self.preferences.get("service")
        if (
            self.provider.get() not in SERVICES
            or SERVICES[self.provider.get()] not in self.available
        ):
            chosen = next(
                (
                    label
                    for label, service in SERVICES.items()
                    if service == saved_service and service in self.available
                ),
                names[0] if len(names) == 1 else "",
            )
            self.provider.set(chosen)
        if self.provider.get():
            self.load_models()
        else:
            self.notice.set(
                "Choose your provider above."
                if names
                else "Choose your private credential file. It needs a line such as GEMINI_API_KEY=your_key."
            )

    def provider_changed(self, _event=None):
        self.cloud_passed = False
        self.models = []
        self.model.set("")
        self.model_box.configure(values=[])
        self.load_models()

    def load_models(self):
        service = SERVICES.get(self.provider.get())
        if not service:
            self.notice.set("Choose a cloud provider first.")
            return
        self.cloud_passed = False
        self.start(
            "Loading available text models from "
            + self.provider.get()
            + " (no generation request)...",
            lambda: self.controller.json_operation(["models", "--service", service]),
            self.models_loaded,
        )

    def models_loaded(self, report):
        if report.get("status") != "ok":
            self.models = []
            self.model.set("")
            self.model_box.configure(values=[])
            self.error(report)
            return
        self.models = report.get("models", [])
        ids = [entry["id"] for entry in self.models]
        self.model_box.configure(values=ids)
        service = SERVICES[self.provider.get()]
        saved = (
            self.preferences.get("model", "") if self.preferences.get("service") == service else ""
        )
        self.model.set(preferred_model(self.models, saved))
        self.model_changed()
        self.notice.set(
            "Model selected from the provider's list. Test connections, or continue to your task."
        )

    def model_changed(self, _event=None):
        self.cloud_passed = False
        if self.model.get() not in [entry["id"] for entry in self.models]:
            return
        service = SERVICES[self.provider.get()]
        save_provider_preferences(service, self.model.get(), self.root)
        self.preferences = {"service": service, "model": self.model.get()}
        self.connection_status.set(
            "Selection saved. Test connections when ready; this makes real API requests."
        )

    def check_connections(self):
        if not self.model.get() or self.model.get() not in [entry["id"] for entry in self.models]:
            self.notice.set("Load models and choose an available model first.")
            return
        if not self.worker_passed:
            self.start(
                "Checking your local Ollama worker...",
                lambda: self.controller.json_operation(["verify-worker"], timeout=240),
                self.worker_checked,
            )
        else:
            self.check_cloud()

    def worker_checked(self, report):
        if report.get("status") != "ok":
            self.error(report)
            return
        self.worker_passed = True
        self.append("Local worker responded successfully. Checking the selected cloud judge...")
        self.check_cloud()

    def check_cloud(self):
        args = [
            "verify-judge",
            "--service",
            SERVICES[self.provider.get()],
            "--model",
            self.model.get(),
        ]
        self.start(
            "Checking "
            + self.provider.get()
            + " model "
            + self.model.get()
            + " (uses your API account)...",
            lambda: self.controller.json_operation(args, timeout=180),
            self.cloud_checked,
        )

    def cloud_checked(self, report):
        self.cloud_passed = report.get("status") == "ok"
        if not self.cloud_passed:
            self.error(report)
            self.append(
                "Your local worker passed. Retry Test connections after fixing cloud access; packages do not need reinstalling."
            )
            return
        self.connection_status.set("Both model connections passed. You can run a task.")
        self.notice.set("Connections passed. Open the Run a task tab.")
        self.append("Local worker and independent cloud judge checks passed.")

    def choose_target(self):
        from tkinter import filedialog

        path = filedialog.askdirectory(
            title="Choose your project folder (outside AASS)", mustexist=False
        )
        if path:
            self.target.set(path)

    def run_task(self):
        if (
            not self.controller.runtime.is_file()
            or SERVICES.get(self.provider.get()) not in self.available
            or self.model.get() not in [entry["id"] for entry in self.models]
        ):
            self.notice.set("Complete local setup and choose a model on the Setup tab first.")
            self.tabs.select(0)
            return
        target, task = self.target.get().strip(), self.task_text.get("1.0", "end").strip()
        if not target or not task:
            self.notice.set("Choose a project folder and describe the task first.")
            return
        self.start(
            "Running your task. Source, tests and review results appear below.",
            lambda: self.controller.run_task(target, task, self.stream),
            self.task_finished,
        )

    def task_finished(self, result):
        if isinstance(result, dict):
            self.error(result)
            return
        self.notice.set(
            "Task passed tests and independent review."
            if result.ok
            else "Task stopped without approval. Read the final result below, correct the reported issue and retry."
        )

    def cancel(self):
        if self.controller.cancel():
            self.notice.set("Cancelling this operation. Waiting for its child processes to stop...")

    def close(self):
        from tkinter import messagebox

        if self.busy:
            if messagebox.askyesno(
                "Stop current operation?",
                "Cancel the current operation and close AASS? Completed installation stages can be reused next time.",
                parent=self.window,
            ):
                self.closing = True
                self.cancel()
        else:
            self.window.after_cancel(self.poll_id)
            self.window.destroy()

    def docker_help(self):
        from tkinter import messagebox

        messagebox.showinfo(
            "Docker / Windows prerequisites",
            "Open Docker Desktop and wait until its Linux engine is running.\n\nIf Docker reports Virtual Machine Platform or WSL is missing, follow Docker's Windows instructions, save your work and restart Windows when requested. Restarting only Docker is insufficient.\n\nThen reopen AASS and click Prepare / check this PC. Existing packages and models are reused.",
            parent=self.window,
        )
        webbrowser.open("https://docs.docker.com/desktop/setup/install/windows-install/")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install", action="store_true", help="Start local preparation when the window opens"
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Construct and close the actual GUI without installing or contacting models",
    )
    args = parser.parse_args(argv)
    try:
        import tkinter as tk

        window = tk.Tk()
    except ImportError as error:
        print(
            "AASS needs the Tcl/Tk component of Python 3.12. Modify your Python installation and enable Tcl/Tk, then reopen AASS. Advanced terminal mode: python local_app.py. "
            + type(error).__name__
        )
        return 2
    except tk.TclError:
        print(
            "AASS could not open a graphical window. On Windows, repair Python's Tcl/Tk component. Advanced terminal mode: python local_app.py."
        )
        return 2
    app = SetupWizard(window, auto_install=args.install, smoke=args.smoke_test)
    if args.smoke_test:
        window.update_idletasks()
        window.update()
        window.after_cancel(app.poll_id)
        window.destroy()
        print(json.dumps({"status": "ok", "gui_constructed": True, "model_requests": 0}))
        return 0
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
