"""Replay the user's rewrite pattern with fixture decisions and actual Docker tests.

This verifies orchestration and files, not live Ollama/Gemini reasoning quality.
"""

import json
import os

import httpx
import pytest

from crdal_supervisor import CRDALSupervisor
from judge_evaluator import JudgeEvaluator
from worker_agent import WorkerAgent

CALCULATOR = """import sys

def add(a,b): return a+b
def subtract(a,b): return a-b
def multiply(a,b): return a*b
def divide(a,b):
 if b == 0: raise ValueError("Cannot divide by zero")
 return a/b

def main():
 try:
  if len(sys.argv)!=4: raise ValueError("Usage: calculator.py number operator number")
  a, op, b = float(sys.argv[1]), sys.argv[2], float(sys.argv[3])
  operations = {"+": add, "-": subtract, "*": multiply, "/": divide}
  if op not in operations: raise ValueError("Unknown operator")
  print(operations[op](a,b))
  return 0
 except ValueError as error:
  print(str(error))
  return 2
if __name__ == "__main__": sys.exit(main())
"""
TESTS = """import unittest, subprocess, sys
from pathlib import Path
from calculator import add, subtract, multiply, divide
class CalculatorTests(unittest.TestCase):
 def test_add(self):
  for a,b in [(2,3),(-2,-3),(0,0),(1.5,2.25)]: self.assertAlmostEqual(add(a,b), a+b)
 def test_subtract(self):
  for a,b in [(2,3),(-2,-3),(0,0),(1.5,2.25)]: self.assertAlmostEqual(subtract(a,b), a-b)
 def test_multiply(self):
  for a,b in [(2,3),(-2,-3),(0,0),(1.5,2.25)]: self.assertAlmostEqual(multiply(a,b), a*b)
 def test_divide(self):
  for a,b in [(6,3),(-6,-3),(0,1),(1.5,2.25)]: self.assertAlmostEqual(divide(a,b), a/b)
 def test_zero(self):
  with self.assertRaises(ValueError): divide(1,0)
 def test_cli(self):
  r=subprocess.run([sys.executable,'calculator.py','1.5','+','2.25'],capture_output=True,text=True)
  self.assertEqual(r.returncode,0)
  self.assertEqual(float(r.stdout),3.75)
 def test_bad_cli(self):
  r=subprocess.run([sys.executable,'calculator.py','1','/','0'],capture_output=True,text=True)
  self.assertNotEqual(r.returncode,0)
  self.assertIn('Cannot divide by zero',r.stdout)
 def test_readme(self):
  self.assertIn('python -m unittest discover -v', Path('README.md').read_text())
"""


@pytest.mark.skipif(os.environ.get("AASS_INTEGRATION") != "1", reason="set AASS_INTEGRATION=1")
def test_rewrite_protocol_loop_pivots_and_delivers_calculator_with_real_tests(
    tmp_path, monkeypatch
):
    def write(path, content):
        return {"action": "write", "reason": "fixture", "path": path, "content": content}

    actions = iter(
        [
            write("calculator.py", CALCULATOR),
            {"action": "write", "reason": "invalid multiple-file action", "files": []},
            write("calculator.py", CALCULATOR + "\n"),
            {"action": "write", "reason": "invalid multiple-file action", "files": []},
            write("calculator.py", CALCULATOR),
            write("test_calculator.py", TESTS),
            write(
                "README.md",
                "Run: python calculator.py 2 + 3\nTests: python -m unittest discover -v\n",
            ),
            {
                "action": "test",
                "reason": "verify all artifacts",
                "command": ["python", "-m", "unittest", "discover", "-v"],
            },
            {"action": "finish", "reason": "request independent review"},
        ]
    )
    contexts, reviews, progress = [], [], []

    def route(request):
        body = json.loads(request.content)
        if request.url.host == "127.0.0.1":
            contexts.append(json.loads(body["messages"][1]["content"]))
            assert body["think"] is False
            assert body["options"]["num_predict"] == 2048
            return httpx.Response(200, json={"message": {"content": json.dumps(next(actions))}})
        evidence = json.loads(body["messages"][1]["content"])["evidence"]
        assert set(evidence["changes"]) == {"calculator.py", "test_calculator.py", "README.md"}
        assert "Ran 8 tests" in evidence["tests"][-1]["stderr"]
        assert evidence["tests"][-1]["returncode"] == 0
        reviews.append(evidence)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"approved": True, "reason": "fixture approval", "issues": []}
                            )
                        }
                    }
                ]
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(route), **kw)
    )
    supervisor = CRDALSupervisor(
        tmp_path,
        WorkerAgent(),
        JudgeEvaluator("fixture", "fixture", "https://judge.test/v1"),
        progress=progress.append,
    )
    report = supervisor.run(
        "Build a CLI calculator with four operations, zero/decimal handling, unittest file and README; run tests and review."
    )
    assert report["status"] == "approved"
    assert report["reserved_tokens"] <= 64000
    assert report["iterations"] == 11  # Nine decisions plus two automatic verification checkpoints.
    assert len(contexts) == 9
    assert len(supervisor.evidence) == 3
    assert contexts[5]["strategy"] != contexts[0]["strategy"]
    assert "add" in contexts[5]["context"]["completed_artifacts"][0]["definitions"]
    assert len(reviews) == 1
    assert any(event["outcome"] == "needs repair" for event in progress)
    events = json.loads((tmp_path / ".aass/trajectory.json").read_text())
    assert events[1]["error_signature"] == "worker_action_schema"
    assert "invalid multiple-file action" not in json.dumps(events)
    assert (tmp_path / "calculator.py").read_text() == CALCULATOR
