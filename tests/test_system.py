"""Real Ollama HTTP protocol + real Docker + deterministic judge protocol fixture.

This test deliberately does NOT claim live LLM behavior or an independent model review.
"""

import http.server
import json
import os
import threading

import httpx
import pytest

from circuit_breaker import CircuitBreaker
from crdal_supervisor import CRDALSupervisor
from judge_evaluator import JudgeEvaluator
from telemetry import Trajectory
from worker_agent import WorkerAgent


@pytest.mark.skipif(os.environ.get("AASS_INTEGRATION") != "1", reason="set AASS_INTEGRATION=1")
@pytest.mark.parametrize("repair_failure", [False, True], ids=["first-pass", "failed-test-repair"])
def test_full_runtime_http_worker_container_tests_review_gate(
    tmp_path, monkeypatch, repair_failure
):
    actions = [
        {
            "action": "write",
            "path": "calculator.py",
            "content": "def add(a,b): return a-b\n"
            if repair_failure
            else "def add(a,b): return a+b\n",
            "reason": "implementation",
        },
        {
            "action": "write",
            "path": "test_calculator.py",
            "content": "import unittest\nfrom calculator import add\nclass Addition(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n",
            "reason": "functional test",
        },
        {
            "action": "test",
            "command": ["python", "-m", "unittest", "discover", "-v"],
            "reason": "verify",
        },
        {"action": "finish", "reason": "tests passed"},
    ]
    if repair_failure:
        actions[3:3] = [
            {
                "action": "write",
                "path": "calculator.py",
                "content": "def add(a,b): return a+b\n",
                "reason": "Repair the implementation after observing the actual failing unit test",
            },
            {
                "action": "test",
                "command": ["python", "-m", "unittest", "discover", "-v"],
                "reason": "Retest the repaired file before review",
            },
        ]
    expected_iterations = len(actions)
    actions = iter(actions)
    worker_requests = []
    judge_calls = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/api/chat"
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert request["model"] == "fixture-model"
            worker_requests.append(json.loads(request["messages"][1]["content"]))
            body = json.dumps({"message": {"content": json.dumps(next(actions))}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    real_client = httpx.Client

    def judge_handler(request):
        evidence = json.loads(json.loads(request.content)["messages"][1]["content"])["evidence"]
        assert "calculator.py" in evidence["changes"]
        assert "Ran 1 test" in evidence["tests"][-1]["stderr"]
        assert evidence["tests"][-1]["returncode"] == 0
        if repair_failure:
            assert [test["returncode"] for test in evidence["tests"]] == [1, 0]
            assert "FAILED (failures=1)" in evidence["tests"][0]["stderr"]
            assert evidence["changes"]["calculator.py"] == "def add(a,b): return a+b\n"
        judge_calls.append(evidence)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "approved": True,
                                    "reason": "protocol fixture approval",
                                    "issues": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    def client(**kwargs):
        def routing(request):
            if request.url.host == "judge.test":
                return judge_handler(request)
            with httpx.HTTPTransport() as transport:
                response = transport.handle_request(request)
                response.read()
                return response

        return real_client(transport=httpx.MockTransport(routing), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    try:
        worker = WorkerAgent(f"http://127.0.0.1:{server.server_port}", "fixture-model")
        judge = JudgeEvaluator("fixture-key", "fixture-judge", "https://judge.test/v1")
        supervisor = CRDALSupervisor(tmp_path, worker, judge, budget=CircuitBreaker())
        report = supervisor.run("Implement addition")
        assert report["status"] == "approved", report
        assert (tmp_path / "calculator.py").read_text() == "def add(a,b): return a+b\n"
        assert report["iterations"] == expected_iterations
        assert len(judge_calls) == 1
        assert len(worker_requests) == expected_iterations
        if repair_failure:
            # Actual Docker failure output reaches the next protocol request;
            # the fixture worker repairs it, rather than a model making a decision.
            failed_context = worker_requests[3]["context"]
            assert not failed_context["verified_since_write"]
            assert "AssertionError" in failed_context["observation"]
            assert "FAILED (failures=1)" in failed_context["observation"]
            assert not worker_requests[4]["context"]["verified_since_write"]
            assert worker_requests[5]["context"]["verified_since_write"]

        # Reopen persisted state through fresh objects. This verifies process-independent
        # history, not a physical Windows desktop close/reopen acceptance test.
        state = json.loads((tmp_path / ".aass/canvas.json").read_text(encoding="utf-8"))
        history = Trajectory(tmp_path / ".aass/trajectory.json").events()
        assert state == report
        assert history[-1]["action"] == "approved"
        assert len(history) == expected_iterations
        assert all(event["run_id"] == report["run_id"] for event in history)
        if repair_failure:
            assert history[2]["action"] == "test"
            assert history[2]["error_signature"].startswith("test:1:")
        reopened = CRDALSupervisor(tmp_path, worker, judge, budget=CircuitBreaker())
        assert reopened.history.events() == history
        assert json.loads(reopened.canvas.read_text(encoding="utf-8")) == report
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
