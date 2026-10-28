import json
import sys

import httpx
import pytest

from circuit_breaker import CircuitBreaker
from judge_evaluator import JudgeEvaluator
from tools.mcp_gateway import MCPGateway
from tools.repo_mapper import RepoMapper
from worker_agent import WorkerAgent


@pytest.fixture
def http_transport(monkeypatch):
    real_client = httpx.Client

    def install(handler):
        monkeypatch.setattr(
            httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
        )

    return install


def test_ollama_protocol_and_fresh_context(http_transport):
    requests = []

    def handler(request):
        data = json.loads(request.content)
        requests.append(data)
        return httpx.Response(
            200, json={"message": {"content": json.dumps({"action": "map", "reason": "inspect"})}}
        )

    http_transport(handler)
    worker = WorkerAgent()
    budget = CircuitBreaker()
    for _ in range(2):
        assert worker.step("task", {}, "strategy", budget)["action"] == "map"
    assert all(len(r["messages"]) == 2 for r in requests)
    assert requests[0]["format"]["type"] == "object"
    assert requests[0]["options"]["num_predict"] == 2048
    assert requests[0]["think"] is False
    assert budget.tokens == sum(
        len(json.dumps(r["messages"]).encode()) + r["options"]["num_predict"] for r in requests
    )


@pytest.mark.parametrize(
    "verdict",
    [
        {"approved": "true", "reason": "bad", "issues": []},
        {"approved": True},
        [],
    ],
)
def test_malformed_judge_fails_closed(http_transport, verdict):
    http_transport(
        lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(verdict)}}]}
        )
    )
    with pytest.raises(ValueError):
        JudgeEvaluator("fixture", "independent").evaluate("task", {}, CircuitBreaker())


def test_judge_issues_override_approval(http_transport):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer fixture"
        assert request.url.scheme == "https"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"approved": True, "reason": "inconsistent", "issues": ["bug"]}
                            )
                        }
                    }
                ]
            },
        )

    http_transport(handler)
    assert not JudgeEvaluator("fixture", "model").evaluate("task", {}, CircuitBreaker())["approved"]


def test_judge_requires_credentials_and_tls():
    with pytest.raises(ValueError):
        JudgeEvaluator("", "model")
    with pytest.raises(ValueError):
        JudgeEvaluator("fixture", "model", "http://untrusted/v1")


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"action": "arbitrary", "reason": "x"},
        {"action": "write", "path": "x", "reason": "x"},
        {"action": "test", "command": "sh", "reason": "x"},
    ],
)
def test_bad_worker_actions(value):
    with pytest.raises(ValueError):
        WorkerAgent.validate(value)


async def test_real_mcp_stdio_handshake_and_tool_allowlist(tmp_path):
    server = tmp_path / "server.py"
    server.write_text(
        "from mcp.server.fastmcp import FastMCP\n"
        'm=FastMCP("fixture")\n'
        "@m.tool()\ndef echo(value: str) -> str:\n return value\n"
        'if __name__ == "__main__": m.run(transport="stdio")\n'
    )
    gateway = MCPGateway(["echo"])
    try:
        await gateway.connect_stdio(sys.executable, [str(server)])
        assert [t["name"] for t in await gateway.list_tools()] == ["echo"]
        result = await gateway.call("echo", {"value": "real MCP response"})
        assert result["content"][0]["text"] == "real MCP response"
        with pytest.raises(PermissionError):
            await gateway.call("delete_everything", {})
    finally:
        await gateway.close()


def test_repository_graph_uses_git_tracked_files(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "app.py").write_text("import json\nfrom pathlib import Path\n")
    (tmp_path / ".env").write_text("hidden=yes")
    subprocess.run(["git", "-C", str(tmp_path), "add", "app.py", ".env"], check=True)
    graph = RepoMapper(tmp_path).map()
    assert graph["files"] == ["app.py"]
    assert graph["imports"]["app.py"] == ["json", "pathlib"]


def test_anthropic_judge_protocol(http_transport):
    def handler(request):
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "fixture"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert json.loads(request.content)["max_tokens"] == 4096
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"approved": True, "reason": "verified", "issues": []}),
                    }
                ]
            },
        )

    http_transport(handler)
    judge = JudgeEvaluator("fixture", "model", "https://api.anthropic.com/v1", provider="anthropic")
    assert judge.evaluate("task", {}, CircuitBreaker())["approved"]


def test_model_response_size_limit_is_enforced_before_json_parse(http_transport):
    from tools.http_client import MAX_RESPONSE_BYTES

    http_transport(lambda request: httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(ValueError, match="size limit"):
        WorkerAgent().step("task", {}, "strategy", CircuitBreaker())


def test_screenshot_is_attached_to_local_worker_and_budgeted(http_transport):
    def handler(request):
        message = json.loads(request.content)["messages"][-1]
        assert message["images"] == ["aW1hZ2U="]
        assert "image_base64" not in message["content"]
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps({"action": "map", "reason": "inspect screenshot"})
                }
            },
        )

    http_transport(handler)
    WorkerAgent().step("task", {"image_base64": "aW1hZ2U="}, "strategy", CircuitBreaker())
    from circuit_breaker import SafetyStop

    with pytest.raises(SafetyStop, match="Token"):
        WorkerAgent().step("task", {"image_base64": "x" * 64000}, "strategy", CircuitBreaker())


def test_new_project_without_git_metadata_can_be_mapped(tmp_path):
    (tmp_path / "app.py").write_text("import json\n")
    (tmp_path / ".env").write_text("private=value\n")
    graph = RepoMapper(tmp_path).map()
    assert graph["version_control"] == "none"
    assert graph["files"] == ["app.py"]
    assert graph["imports"]["app.py"] == ["json"]


@pytest.mark.parametrize(
    ("response", "code"),
    [
        ({"message": {"content": ""}}, "worker_json_invalid"),
        ({"message": {"content": '{"action":"write","files":[]}'}}, "worker_action_schema"),
        (
            {"done_reason": "length", "message": {"content": '{"action":"map","reason":"ok"}'}},
            "worker_output_truncated",
        ),
    ],
)
def test_worker_protocol_failures_are_specific_and_preserve_charged_budget(
    http_transport, response, code
):
    from worker_agent import WorkerProtocolError

    http_transport(lambda request: httpx.Response(200, json=response))
    budget = CircuitBreaker()
    with pytest.raises(WorkerProtocolError) as caught:
        WorkerAgent().step("task", {}, "strategy", budget)
    assert caught.value.code == code
    assert 2048 < budget.tokens < 64000


def test_action_schema_requires_arguments_for_each_action():
    from jsonschema import Draft202012Validator

    from worker_agent import ACTION_SCHEMA

    validator = Draft202012Validator(ACTION_SCHEMA)
    assert validator.is_valid(
        {"action": "test", "reason": "verify", "command": ["python", "-m", "unittest"]}
    )
    for bad in [
        {"action": "test", "reason": "verify"},
        {"action": "test", "reason": "verify", "command": "python -m unittest"},
        {"action": "write", "reason": "write", "path": "app.py"},
        {"action": "mcp", "reason": "call", "tool": "unknown"},
        {"action": "test", "reason": "verify", "command": []},
    ]:
        assert not validator.is_valid(bad)
        with pytest.raises(ValueError):
            WorkerAgent.validate(bad)


def test_schema_rejection_records_only_fixed_field_names(http_transport):
    from worker_agent import WorkerProtocolError

    observed = []
    http_transport(
        lambda request: httpx.Response(
            200,
            json={
                "message": {"content": json.dumps({"action": "test", "reason": "FAKE_PRIVATE_KEY"})}
            },
        )
    )
    with pytest.raises(WorkerProtocolError) as caught:
        WorkerAgent(observer=lambda **event: observed.append(event)).step(
            "task", {}, "strategy", CircuitBreaker()
        )
    assert caught.value.details["field"] == "command"
    assert observed[-1]["event_type"] == "action_rejected"
    assert "FAKE_PRIVATE_KEY" not in json.dumps(observed)
