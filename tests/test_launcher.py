import subprocess
import sys
from types import SimpleNamespace

import pytest

import launch_aass as launcher
from launch_aass import application_fingerprint, dependency_fingerprint, setup_step
from launch_aass import browser_available as actual_browser_available


def test_installer_inherits_output_and_reports_liveness(capfd):
    setup_step(
        "installer fixture",
        [
            sys.executable,
            "-u",
            "-c",
            'import time; print("child output", flush=True); time.sleep(0.1)',
        ],
        progress_interval=0.02,
    )
    output = capfd.readouterr().out
    assert "child output" in output
    assert "Still running: installer fixture" in output
    assert "Finished: installer fixture" in output


def test_failed_installer_preserves_exit_status_and_never_reports_finished(capfd):
    with pytest.raises(subprocess.CalledProcessError) as error:
        setup_step("failure fixture", [sys.executable, "-c", "raise SystemExit(7)"])
    assert error.value.returncode == 7
    assert "Finished:" not in capfd.readouterr().out


def test_setup_child_does_not_inherit_pip_tls_bypass_or_private_index(monkeypatch, capfd):
    monkeypatch.setenv("PIP_TRUSTED_HOST", "untrusted.example")
    monkeypatch.setenv("PIP_INDEX_URL", "https://private:credential@untrusted.example/simple")
    setup_step(
        "pip config boundary",
        [
            sys.executable,
            "-c",
            'import os; print("PIP_TRUSTED_HOST" in os.environ); print("PIP_INDEX_URL" in os.environ); print(os.environ["PIP_CONFIG_FILE"] == os.devnull)',
        ],
    )
    output = capfd.readouterr().out
    assert "False\nFalse\nTrue" in output.replace("\r\n", "\n")
    assert "credential" not in output


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = tmp_path / "application with spaces"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nversion="1.3.0"\n')
    (root / "requirements.lock").write_text("fixture==1\n")
    (root / "requirements-dev.lock").write_text("fixture==1\npytest-fixture==1\n")
    (root / "requirements-postgres.lock").write_text("fixture==1\npostgres-fixture==1\n")
    executable = (
        root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    )
    executable.parent.mkdir(parents=True)
    executable.touch()
    (root / "generated").mkdir()
    (root / "generated/architecture_spec.json").write_text("{}")
    monkeypatch.setattr(launcher, "__file__", str(root / "launch_aass.py"))
    monkeypatch.setattr(launcher.shutil, "which", lambda _name: None)
    monkeypatch.delenv("AASS_CHROMIUM_EXECUTABLE", raising=False)
    monkeypatch.setattr(launcher, "browser_available", lambda *_args: True)
    calls = []
    monkeypatch.setattr(
        launcher, "setup_step", lambda label, command, **kwargs: calls.append((label, command))
    )
    return SimpleNamespace(
        root=root, environment=root / ".venv", executable=executable, calls=calls
    )


def labels(runtime):
    return [label for label, _command in runtime.calls]


def test_first_install_commits_independent_phase_markers_after_all_checks(runtime, capsys):
    assert launcher.main(["--install-only"]) == 0
    assert labels(runtime) == [
        "Installing locked Python dependencies",
        "Installing AASS application",
    ]
    dependency_command = runtime.calls[0][1]
    assert "--require-hashes" in dependency_command
    assert "--only-binary=:all:" in dependency_command
    assert "--force-reinstall" in dependency_command
    assert (runtime.environment / ".aass-dependencies").read_text() == dependency_fingerprint(
        runtime.root
    )
    assert (runtime.environment / ".aass-application").is_file()
    assert (runtime.environment / ".aass-browser").is_file()
    assert not (runtime.environment / ".aass-installed").exists()
    assert "Application version: 1.3.0" in capsys.readouterr().out


def test_repeated_install_reuses_dependencies_and_application_but_probes_browser(
    runtime, monkeypatch
):
    probes = []
    monkeypatch.setattr(launcher, "browser_available", lambda *_args: probes.append(True) or True)
    launcher.main(["--install-only"])
    runtime.calls.clear()
    assert launcher.main(["--install-only"]) == 0
    assert runtime.calls == []
    assert len(probes) == 2


def test_source_version_update_reinstalls_only_application_metadata(runtime):
    launcher.main(["--install-only"])
    previous_dependencies = (runtime.environment / ".aass-dependencies").read_text()
    runtime.calls.clear()
    (runtime.root / "pyproject.toml").write_text('[project]\nversion="1.3.1"\n')
    assert launcher.main(["--install-only"]) == 0
    assert labels(runtime) == ["Installing AASS application"]
    assert "--no-deps" in runtime.calls[0][1]
    assert "--no-build-isolation" in runtime.calls[0][1]
    assert (runtime.environment / ".aass-dependencies").read_text() == previous_dependencies


def test_changed_lock_invalidates_markers_before_any_dependency_mutation(runtime, monkeypatch):
    launcher.main(["--install-only"])
    (runtime.root / "requirements.lock").write_text("fixture==2\n")
    (runtime.environment / ".aass-installed").write_text("legacy-success")
    seen = []

    def fail(label, command, **kwargs):
        seen.append(label)
        assert not any(
            (runtime.environment / name).exists()
            for name in (
                ".aass-dependencies",
                ".aass-application",
                ".aass-browser",
                ".aass-installed",
            )
        )
        raise subprocess.CalledProcessError(7, command)

    monkeypatch.setattr(launcher, "setup_step", fail)
    with pytest.raises(subprocess.CalledProcessError):
        launcher.main(["--install-only"])
    assert seen == ["Installing locked Python dependencies"]


def test_failed_application_upgrade_keeps_known_dependencies_but_not_success_marker(
    runtime, monkeypatch
):
    launcher.main(["--install-only"])
    previous_dependencies = (runtime.environment / ".aass-dependencies").read_text()
    (runtime.root / "pyproject.toml").write_text('[project]\nversion="1.3.1"\n')

    def fail(_label, command, **kwargs):
        raise subprocess.CalledProcessError(7, command)

    monkeypatch.setattr(launcher, "setup_step", fail)
    with pytest.raises(subprocess.CalledProcessError):
        launcher.main(["--install-only"])
    assert (runtime.environment / ".aass-dependencies").read_text() == previous_dependencies
    assert not (runtime.environment / ".aass-application").exists()


def test_removed_browser_cache_is_repaired_without_reinstalling_packages(runtime, monkeypatch):
    launcher.main(["--install-only"])
    runtime.calls.clear()
    availability = iter([False, True])
    monkeypatch.setattr(launcher, "browser_available", lambda *_args: next(availability))
    assert launcher.main(["--install-only"]) == 0
    assert labels(runtime) == ["Installing Chromium browser"]


def test_failed_browser_repair_does_not_commit_a_fresh_install(runtime, monkeypatch):
    monkeypatch.setattr(launcher, "browser_available", lambda *_args: False)
    with pytest.raises(SystemExit, match="Chromium was installed but could not start"):
        launcher.main(["--install-only"])
    assert not any(
        (runtime.environment / name).exists()
        for name in (".aass-dependencies", ".aass-application", ".aass-browser")
    )


def test_invalid_explicit_browser_is_reported_without_overriding_it(runtime, monkeypatch):
    monkeypatch.setenv("AASS_CHROMIUM_EXECUTABLE", str(runtime.root / "missing-browser"))
    monkeypatch.setattr(launcher, "browser_available", lambda *_args: False)
    with pytest.raises(SystemExit, match="configured/system Chromium"):
        launcher.main(["--install-only"])
    assert "Installing Chromium browser" not in labels(runtime)


def test_legacy_marker_alone_cannot_certify_dependencies(runtime):
    (runtime.environment / ".aass-installed").write_text("old-success")
    launcher.main(["--install-only"])
    assert labels(runtime)[0] == "Installing locked Python dependencies"


def test_corrupt_phase_marker_is_repaired_as_an_unverified_install(runtime):
    (runtime.environment / ".aass-dependencies").write_bytes(b"\xff\xfe")
    launcher.main(["--install-only"])
    assert labels(runtime)[0] == "Installing locked Python dependencies"
    assert (runtime.environment / ".aass-dependencies").read_text() == dependency_fingerprint(
        runtime.root
    )


def test_lifecycle_can_seed_a_verified_unchanged_dependency_lock(runtime):
    # The lifecycle owns the old/new lock comparison and pip check. This marker
    # grants reuse only to exactly those wheels and this interpreter identity.
    (runtime.environment / ".aass-dependencies").write_text(dependency_fingerprint(runtime.root))
    launcher.main(["--install-only"])
    assert labels(runtime) == ["Installing AASS application"]


def test_dependency_identity_ignores_app_location_and_version_but_not_lock(runtime, tmp_path):
    other = tmp_path / "moved application"
    other.mkdir()
    (other / "requirements.lock").write_bytes((runtime.root / "requirements.lock").read_bytes())
    (other / "pyproject.toml").write_text('[project]\nversion="2.0.0"\n')
    dependencies = dependency_fingerprint(runtime.root)
    assert dependency_fingerprint(other) == dependencies
    assert application_fingerprint(other, dependencies) != application_fingerprint(
        runtime.root, dependencies
    )
    (other / "requirements.lock").write_text("fixture==2\n")
    assert dependency_fingerprint(other) != dependencies


def test_optional_lock_selection_is_independently_verified(runtime):
    launcher.main(["--install-only", "--postgres"])
    assert str(runtime.root / "requirements-postgres.lock") in runtime.calls[0][1]
    assert (runtime.environment / ".aass-dependencies").read_text() == dependency_fingerprint(
        runtime.root, "requirements-postgres.lock"
    )


def test_browser_probe_filters_credentials_and_has_a_finite_deadline(runtime, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private-fixture-key")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert actual_browser_available(runtime.executable, runtime.root)
    command, options = calls[0]
    assert command[1] == "-I"
    assert options["timeout"] == 75
    assert "GEMINI_API_KEY" not in options["env"]
