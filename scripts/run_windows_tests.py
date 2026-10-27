"""Run CI tests under a separate watchdog, including native-code stalls."""

import argparse
import os
import queue
import re
import signal
import subprocess
import threading
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    parser.add_argument("--junitxml", required=True)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
    command = [
        args.python,
        "-u",
        "-m",
        "pytest",
        "-vv",
        "-s",
        "--junitxml=" + args.junitxml,
        *args.tests,
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=os.name != "nt"
    )
    chunks = queue.Queue()

    def read():
        while True:
            chunk = process.stdout.read1(4096)
            if not chunk:
                chunks.put(None)
                return
            chunks.put(chunk)

    threading.Thread(target=read, daemon=True).start()
    current = "test collection"
    deadline = time.monotonic() + args.timeout
    tail = ""
    ended = False
    while not ended or process.poll() is None:
        if time.monotonic() > deadline:
            safe = current.split("[", 1)[0].replace("\r", "").replace("\n", "")[:300]
            print("::error title=Windows test timeout::Stalled check: " + safe, flush=True)
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
            else:
                os.killpg(process.pid, signal.SIGKILL)
            if process.poll() is None:
                process.kill()
            process.wait(timeout=15)
            return 124
        try:
            chunk = chunks.get(timeout=0.1)
        except queue.Empty:
            continue
        if chunk is None:
            ended = True
            continue
        text = chunk.decode("utf-8", errors="replace")
        print(text, end="", flush=True)
        tail = (tail + text)[-32768:]
        matches = re.findall(r"tests/[^\s:]+(?:::[^\s]+)+", tail)
        if matches and matches[-1] != current:
            current = matches[-1]
            deadline = time.monotonic() + args.timeout
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
