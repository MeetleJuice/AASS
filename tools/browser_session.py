"""Stateful browser helper over private stdio; provider keys never reach its SDK/renderer."""

import json
import os
import queue
import signal
import subprocess
import sys
import threading
from pathlib import Path

from settings import SECRET_NAMES, subprocess_environment


class BrowserSession:
    def __init__(self, origins):
        self.process = subprocess.Popen(
            [sys.executable, "-I", "-u", "-m", "tools.browser_session"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            env=subprocess_environment(),
            cwd=Path(__file__).resolve().parents[1],
            start_new_session=os.name != "nt",
        )
        self.responses = queue.Queue(maxsize=32)

        def read():
            for line in self.process.stdout:
                self.responses.put(line[:65536])
            self.responses.put(None)

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            self.ask({"operation": "initialize", "origins": list(origins)})
        except BaseException:
            self.close(force=True)
            raise

    def ask(self, action):
        payload = json.dumps(action)
        if len(payload.encode()) > 32768:
            raise ValueError("Browser action exceeds input limit")
        self.process.stdin.write(payload + "\n")
        self.process.stdin.flush()
        try:
            line = self.responses.get(timeout=30)
            if line is None:
                raise RuntimeError("Browser helper stopped")
            response = json.loads(line)
            if response.get("error"):
                raise RuntimeError("Browser action failed: " + response["error"])
            return response.get("result")
        except queue.Empty:
            self.close(force=True)
            raise TimeoutError("Browser action timed out") from None

    def navigate(self, url):
        return self.ask({"operation": "navigate", "url": url})

    def click(self, selector=None, *, x=None, y=None):
        return self.ask({"operation": "click", "selector": selector, "x": x, "y": y})

    def screenshot(self, path):
        return self.ask({"operation": "screenshot", "path": str(path)})

    def text(self):
        return self.ask({"operation": "text"})

    def close(self, force=False):
        if self.process.poll() is None and not force:
            try:
                self.ask({"operation": "close"})
                self.process.wait(timeout=10)
            except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired):
                force = True
        if self.process.poll() is None and force:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
            else:
                os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=10)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()
        self.reader.join(timeout=2)


def serve():
    from tools.computer_use import ComputerUse

    def reply(**data):
        print(json.dumps(data), flush=True)

    if any(os.environ.get(name) for name in SECRET_NAMES):
        reply(error="CredentialBindingsNotAllowed")
        return 2
    first = json.loads(sys.stdin.readline(32769))
    if first.get("operation") != "initialize":
        raise ValueError("Initialization required")
    with ComputerUse(first["origins"]) as browser:
        reply(result="ready")
        while line := sys.stdin.readline(32769):
            try:
                if len(line.encode()) > 32768:
                    raise ValueError("Action too large")
                action = json.loads(line)
                operation = action.get("operation")
                if operation == "close":
                    reply(result="closed")
                    return 0
                if operation == "probe":
                    browser.page.set_content("<title>AASS readiness</title>")
                    result = browser.page.title() == "AASS readiness"
                elif operation == "navigate":
                    result = browser.navigate(action["url"])
                elif operation == "click":
                    browser.click(action.get("selector"), x=action.get("x"), y=action.get("y"))
                    result = "clicked"
                elif operation == "screenshot":
                    browser.screenshot(action["path"])
                    result = "saved"
                elif operation == "text":
                    result = browser.page.locator("body").inner_text()[:8192]
                else:
                    raise ValueError("Unknown browser operation")
                reply(result=result)
            except Exception as error:
                reply(error=type(error).__name__)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(serve())
    except Exception:
        print(json.dumps({"error": "BrowserInitializationFailed"}), flush=True)
        raise SystemExit(2) from None
