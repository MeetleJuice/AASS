"""Ordinary CI timing logs and a parameter-free last-started breadcrumb."""

import os
from pathlib import Path

_completed = 0


def pytest_runtest_logstart(nodeid, location):
    destination = os.environ.get("AASS_CI_PROGRESS")
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(nodeid.split("[", 1)[0][:1000], encoding="utf-8")


def pytest_runtest_logreport(report):
    global _completed
    if report.when == "call" or report.when == "setup" and report.skipped:
        _completed += 1
        if _completed % 100 == 0:
            print(f"\nCI progress: {_completed} test calls completed", flush=True)
    if report.duration >= 10:
        print(
            f"\nCI timing: {report.when} {report.duration:.1f}s; {_completed} calls completed",
            flush=True,
        )
