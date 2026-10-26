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
from worker_agent import WorkerAgent


@pytest.mark.skipif(os.environ.get("AASS_INTEGRATION") != "1", reason="set AASS_INTEGRATION=1")
def test_full_runtime_http_worker_container_tests_review_gate(tmp_path, monkeypatch):
    actions = iter(
        [
            {
                "action": "write",
                "path": "calculator.py",
                "content": "def add(a,b): return a+b\n",
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
    )

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/api/chat"
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert request["model"] == "fixture-model"
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
        report = CRDALSupervisor(tmp_path, worker, judge, budget=CircuitBreaker()).run(
            "Implement addition"
        )
        assert report["status"] == "approved", report
        assert (tmp_path / "calculator.py").read_text() == "def add(a,b): return a+b\n"
        assert report["iterations"] == 4
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
