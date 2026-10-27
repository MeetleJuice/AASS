"""Bound each Windows CI test and expose its safe name in GitHub annotations."""

import os
import threading

_timer = None


def pytest_runtest_setup(item):
    global _timer
    if _timer is not None:
        _timer.cancel()
    name = item.nodeid.split("[", 1)[0].replace("\r", "").replace("\n", "")[:300]
    timeout = max(1, min(120, int(os.environ.get("AASS_CI_TEST_TIMEOUT", "120"))))

    def stalled():
        print("::error title=Windows test timeout::Test exceeded its deadline: " + name, flush=True)
        os._exit(124)

    _timer = threading.Timer(timeout, stalled)
    _timer.daemon = True
    _timer.start()


def pytest_runtest_logfinish(nodeid, location):
    global _timer
    if _timer is not None:
        _timer.cancel()
        _timer = None
