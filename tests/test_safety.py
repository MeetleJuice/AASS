import json

import pytest

from circuit_breaker import MAX_TOKENS, CircuitBreaker, SafetyStop
from crdal_supervisor import workspace_path
from initialize_aass import bootstrap_workspace, load_credentials
from sandboxes.container import snapshot, validate_command
from stall_detector import check_fixation
from telemetry import Trajectory


def test_hard_caps_and_precharge():
    with pytest.raises(ValueError):
        CircuitBreaker(token_limit=MAX_TOKENS + 1)
    budget = CircuitBreaker(token_limit=12, iteration_limit=1)
    budget.tick()
    with pytest.raises(SafetyStop):
        budget.tick()
    budget.reserve("abc", 9)
    assert budget.tokens == 12
    with pytest.raises(SafetyStop):
        budget.reserve("x", 1)
    with pytest.raises(SafetyStop):
        CircuitBreaker().reserve("", 4097)


@pytest.mark.parametrize(
    "argv",
    [
        ["sh", "-c", "echo hi"],
        ["python", "-c", "print(1)"],
        ["python", "-m", "pytest", ";rm"],
        ["python", "-m", "pytest", "$(id)"],
        ["python", "-m", "pytest", "-p", "evil"],
        "python -m unittest",
        [],
    ],
)
def test_command_policy(argv):
    with pytest.raises(SafetyStop):
        validate_command(argv)


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/tmp/outside",
        ".env",
        "a/.git/config",
        "trajectory.json",
        "my_credentials.txt",
        "x.pem",
    ],
)
def test_file_containment(tmp_path, path):
    with pytest.raises(SafetyStop):
        workspace_path(tmp_path, path)


def test_symlink_rejected(tmp_path):
    (tmp_path / "link").symlink_to(tmp_path / "target")
    with pytest.raises(SafetyStop):
        workspace_path(tmp_path, "link")


def test_snapshot_filters_secrets_and_links(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    (src / ".env").write_text("DO_NOT_EXPORT=yes")
    (src / "credentials.txt").write_text("DO_NOT_EXPORT=yes")
    (src / "test_ok.py").write_text("pass")
    (src / "link.py").symlink_to(src / "test_ok.py")
    (src / ".aass").mkdir()
    (src / ".aass/state.json").write_text("{}")
    snapshot(src, dst)
    assert sorted(p.name for p in dst.iterdir()) == ["test_ok.py"]


def test_bootstrap_preserves_trajectory_and_omits_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("AASS_JUDGE_API_KEY", "never-persist-this")
    bootstrap_workspace(tmp_path, [])
    trajectory = tmp_path / "trajectory.json"
    trajectory.write_text('[{"custom": true}]')
    bootstrap_workspace(tmp_path, ["qwen3.5:9b"])
    assert json.loads(trajectory.read_text()) == [{"custom": True}]
    spec = (tmp_path / "generated/architecture_spec.json").read_text()
    assert "never-persist-this" not in spec
    assert len(json.loads(spec)["build_order"]) == 5
    assert "AASS_JUDGE_API_KEY" in spec


def test_credentials_do_not_evaluate_shell_or_override_bindings(tmp_path, monkeypatch):
    monkeypatch.setenv("AASS_JUDGE_API_KEY", "existing")
    path = tmp_path / "config"
    path.write_text("AASS_JUDGE_API_KEY=replacement\nPATH=/evil\nAASS_JUDGE_MODEL=model\n")
    load_credentials(path)
    import os

    assert os.environ["AASS_JUDGE_API_KEY"] == "existing"
    assert os.environ["PATH"] != "/evil"
    assert os.environ["AASS_JUDGE_MODEL"] == "model"


def test_seeded_fixation_and_success_exclusion(tmp_path):
    history = Trajectory(tmp_path / "trajectory.json")
    for i in range(3):
        history.append(
            iteration=i, files_modified=["a.py"], error_signature="same", action="write", strategy=0
        )
    assert check_fixation(history.path)
    history.append(
        iteration=3, files_modified=["a.py"], error_signature="SUCCESS", action="write", strategy=0
    )
    assert not check_fixation(history.path)
    history.path.write_text("corrupt")
    with pytest.raises(json.JSONDecodeError):
        check_fixation(history.path)


def test_corrupt_trajectory_fails_closed(tmp_path):
    path = tmp_path / "trajectory.json"
    path.write_text("{}")
    with pytest.raises(ValueError):
        Trajectory(path)
