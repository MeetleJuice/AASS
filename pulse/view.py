"""Responsive Tk Pulse view; process work never runs on Tk's event thread."""

import json
import sys
import time
import uuid

from pulse.benchmarks import manifest
from pulse.report import documents, export_zip, load


def notify_sound():
    if sys.platform == "win32":
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_OK)
        except (RuntimeError, OSError, ImportError):
            pass


class PulseView:
    def __init__(self, owner, *, auto_start=True):
        import tkinter as tk
        from tkinter import ttk

        self.owner = owner
        self.window = tk.Toplevel(owner.window)
        self.window.title("AASS Pulse — diagnostic laboratory")
        self.window.geometry("860x700")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.running = False
        self.directory = None
        self.started = None
        self.completed = 0
        self.errors = 0
        self.recoveries = 0
        self.local = tk.BooleanVar(value=False)
        self.cloud = tk.BooleanVar(value=False)
        self.include_environment = tk.BooleanVar(value=True)
        self.include_events = tk.BooleanVar(value=True)
        self.include_metrics = tk.BooleanVar(value=True)
        main = ttk.Frame(self.window, padding=14)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="AASS Pulse", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(
            main,
            text="Default: bounded harness checks with real Docker tools; no model generation.\nLive evaluations send benchmark source only. No user project is evaluated.",
            wraplength=790,
        ).pack(anchor="w")
        ttk.Checkbutton(
            main,
            text="Enable live local Ollama evaluation (slower; shared 64,000-token / 20-step ceiling)",
            variable=self.local,
        ).pack(anchor="w")
        ttk.Checkbutton(
            main,
            text="Also enable independent cloud review (API charges; explicit consent each run)",
            variable=self.cloud,
        ).pack(anchor="w")
        self.start_button = ttk.Button(main, text="Run All Tests", command=self.start)
        self.start_button.pack(anchor="w", pady=6)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(
            main,
            text="Worker: configured local Ollama model; cloud: "
            + owner.provider.get()
            + " / "
            + owner.model.get(),
            wraplength=790,
        ).pack(anchor="w")
        self.metrics = tk.StringVar(
            value="Model usage and monetary cost unavailable until reported."
        )
        self.elapsed = tk.StringVar(value="Elapsed: 0s")
        for variable in [self.status, self.metrics, self.elapsed]:
            ttk.Label(main, textvariable=variable, wraplength=790).pack(anchor="w")
        self.progress = ttk.Progressbar(main, mode="determinate", maximum=len(manifest()["cases"]))
        self.progress.pack(fill="x", pady=8)
        self.table = ttk.Treeview(main, columns=("status", "mode"), show="tree headings", height=8)
        self.table.heading("#0", text="Benchmark")
        self.table.heading("status", text="Outcome")
        self.table.heading("mode", text="Evidence mode")
        for case in manifest()["cases"]:
            self.table.insert(
                "", "end", iid=case["id"], text=case["title"], values=("pending", "deterministic")
            )
        self.table.pack(fill="x")
        frame = ttk.Frame(main)
        frame.pack(fill="both", expand=True, pady=8)
        self.timeline = tk.Text(frame, height=9, wrap="word", state="disabled")
        scrollbar = ttk.Scrollbar(frame, command=self.timeline.yview)
        self.timeline.configure(yscrollcommand=scrollbar.set)
        self.timeline.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        controls = ttk.Frame(main)
        controls.pack(fill="x")
        self.cancel_button = ttk.Button(controls, text="Cancel safely", command=self.cancel)
        self.cancel_button.pack(side="left")
        self.review_button = ttk.Button(
            controls, text="Review Results", command=self.review, state="disabled"
        )
        self.review_button.pack(side="left", padx=8)
        self.export_button = ttk.Button(
            controls, text="Create Diagnostic ZIP", command=self.review, state="disabled"
        )
        self.export_button.pack(side="left")
        self.after_id = self.window.after(200, self.tick)
        if auto_start:
            self.window.after(100, self.start)

    def start(self):
        from tkinter import messagebox

        if self.running or self.owner.busy:
            return
        if self.cloud.get() and not self.local.get():
            messagebox.showinfo(
                "AASS Pulse",
                "Enable live local evaluation before independent cloud review.",
                parent=self.window,
            )
            return
        if self.local.get() and not messagebox.askyesno(
            "Live evaluation consent",
            "Run live Ollama benchmark tasks? This can take several minutes. "
            + (
                "Cloud review sends benchmark code and uses your API account; charges may apply."
                if self.cloud.get()
                else "Cloud review is disabled; tasks requiring review will be blocked, not approved."
            ),
            parent=self.window,
        ):
            return
        self.directory = self.owner.root / ".aass/pulse" / uuid.uuid4().hex
        self.directory.mkdir(parents=True)
        self.running = True
        self.status.set("Checking environment readiness; no benchmark has completed yet.")
        self.started = time.monotonic()
        self.completed = self.errors = self.recoveries = 0
        self.progress.configure(value=0)
        self.start_button.configure(state="disabled")
        self.review_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        for case in manifest()["cases"]:
            self.table.set(case["id"], "status", "pending")
        command = [
            self.owner.controller._runtime(),
            "-m",
            "pulse.cli",
            "--root",
            str(self.owner.root),
            "--directory",
            str(self.directory),
        ]
        live_local = self.local.get()
        if live_local:
            command += ["--live-local"]
        if self.cloud.get():
            command += ["--live-cloud"]
        self.owner.start(
            "Running AASS Pulse in isolated benchmark workspaces.",
            lambda: self.owner.controller._execute(
                command,
                callback=self.stream,
                credentials=live_local,
                timeout=3600,
                label="Pulse",
            ),
            self.finished,
            kind="pulse",
        )

    def stream(self, line):
        if line.startswith("PULSE "):
            try:
                self.owner.events.put(("pulse", (self, json.loads(line[6:]))))
            except ValueError:
                pass

    def event(self, event):
        name = event.get("event_type", "event")
        test_id = event.get("test_id")
        if name == "test_started" and test_id:
            self.table.set(test_id, "status", "running")
            self.table.set(test_id, "mode", event.get("mode", "deterministic"))
        if name == "test_finished" and test_id:
            self.completed += 1
            self.progress.configure(value=self.completed)
            self.table.set(test_id, "status", event.get("outcome", "failed"))
        if name == "action_rejected":
            self.errors += 1
        if name in ("schema_recovered", "strategy_pivot"):
            self.recoveries += 1
        self.status.set(
            f"{self.completed}/{len(manifest()['cases'])} completed — {test_id or 'suite'}: {name}"
        )
        self.metrics.set(
            f"Errors: {self.errors}; recoveries: {self.recoveries}; reserved budget: {event.get('reserved_tokens', 'unavailable')}; action: {event.get('action', '—')}. Cost unavailable."
        )
        self.timeline.configure(state="normal")
        self.timeline.insert(
            "end",
            f"{event.get('elapsed', 0):.1f}s {test_id or 'suite'} — {name} {event.get('action', '')} {event.get('outcome', '')}\n",
        )
        if int(self.timeline.index("end-1c").split(".")[0]) > 1000:
            self.timeline.delete("1.0", "200.0")
        self.timeline.see("end")
        self.timeline.configure(state="disabled")

    def finished(self, result):
        self.running = False
        self.start_button.configure(state="normal")
        self.review_button.configure(state="normal")
        self.export_button.configure(state="normal")
        summary = load(self.directory, "summary.json")
        status = summary.get("status", "interrupted")
        if status == "running":
            status = "interrupted"
        counts = summary.get("counts", {})
        for row in load(self.directory, "benchmark-results.json") or []:
            if row.get("id") in self.table.get_children():
                self.table.set(row["id"], "status", row.get("status", "blocked"))
        self.status.set(
            "Finished: "
            + status
            + " — "
            + ", ".join(f"{key}: {value}" for key, value in counts.items())
        )
        notify_sound()
        # Nonblocking native Tk dialog; sound failure cannot suppress visual completion.
        dialog = self.owner.tk.Toplevel(self.window)
        dialog.title("AASS Pulse complete")
        self.owner.ttk.Label(dialog, text=self.status.get(), wraplength=580, padding=14).pack()
        self.owner.ttk.Button(
            dialog, text="Review Results", command=lambda: (dialog.destroy(), self.review())
        ).pack(side="left", padx=14, pady=10)
        self.owner.ttk.Button(
            dialog, text="Create Diagnostic ZIP", command=lambda: (dialog.destroy(), self.review())
        ).pack(side="left", padx=14, pady=10)

    def tick(self):
        if self.running and self.started:
            self.elapsed.set(f"Elapsed: {int(time.monotonic() - self.started)}s")
        self.after_id = self.window.after(200, self.tick)

    def cancel(self):
        if self.running and self.directory:
            (self.directory / "cancel").touch()
            self.status.set("Cancelling owned benchmark processes; retaining partial results…")

    def review(self):
        if self.running or not self.directory:
            return
        tk, ttk = self.owner.tk, self.owner.ttk
        review = tk.Toplevel(self.window)
        review.title("Review diagnostic export")
        content = documents(self.directory)
        text = tk.Text(review, width=95, height=25, wrap="word")
        text.pack(fill="both", expand=True)
        text.insert(
            "end",
            content["SUMMARY.md"]
            + "\nExport contains:\n"
            + "\n".join(content)
            + "\n\nExcluded: private files, user projects, source code, paths, exception text and raw model/test output. Nothing is uploaded.",
        )
        text.configure(state="disabled")
        for label, var in [
            ("Include environment metadata", self.include_environment),
            ("Include event metadata", self.include_events),
            ("Include model/tool metrics", self.include_metrics),
        ]:
            ttk.Checkbutton(review, text=label, variable=var).pack(anchor="w")
        ttk.Button(review, text="Create Diagnostic ZIP", command=self.export).pack(pady=8)
        ttk.Button(review, text="Compare another exported run", command=self.compare).pack(pady=4)

    def compare(self):
        from tkinter import filedialog, messagebox

        from pulse.engine import compare
        from pulse.report import open_report, safe_environment, safe_summary

        path = filedialog.askopenfilename(parent=self.window, filetypes=[("Pulse ZIP", "*.zip")])
        if not path:
            return
        try:
            earlier = open_report(path)
            current = {
                "summary": safe_summary(load(self.directory, "summary.json")),
                "environment": safe_environment(load(self.directory, "environment.json")),
            }
            result = compare(earlier, current)
            messagebox.showinfo("Run comparison", json.dumps(result, indent=2), parent=self.window)
        except (OSError, ValueError, KeyError):
            messagebox.showerror(
                "Run comparison", "This is not a valid bounded Pulse report.", parent=self.window
            )

    def export(self):
        from tkinter import filedialog, messagebox

        if self.running or not self.directory:
            return
        path = filedialog.asksaveasfilename(
            parent=self.window,
            defaultextension=".zip",
            initialfile="AASS-Pulse-diagnostics.zip",
            filetypes=[("Diagnostic ZIP", "*.zip")],
        )
        if not path:
            return
        try:
            export_zip(
                self.directory,
                path,
                include_environment=self.include_environment.get(),
                include_events=self.include_events.get(),
                include_metrics=self.include_metrics.get(),
            )
            messagebox.showinfo(
                "AASS Pulse", "Diagnostic ZIP saved. Nothing was uploaded.", parent=self.window
            )
        except (OSError, ValueError):
            messagebox.showerror(
                "AASS Pulse",
                "Could not create ZIP. Choose a writable destination.",
                parent=self.window,
            )

    def close(self):
        if self.running:
            self.cancel()
            return
        self.window.after_cancel(self.after_id)
        self.owner.pulse_view = None
        self.window.destroy()
