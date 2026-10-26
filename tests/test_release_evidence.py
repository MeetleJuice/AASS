"""A release needs evidence for the exact archive and installed runtime."""

import hashlib
import json
import zipfile

import pytest

from scripts.check_release_evidence import check


def evidence_fixture(directory, *, version="1.2.1", dirty=False):
    code = b"print('verified source')\n"
    manifest = {
        "format": 1,
        "version": version,
        "source_revision": "a" * 40,
        "dirty": dirty,
        "files": {"app.py": hashlib.sha256(code).hexdigest()},
    }
    archive = directory / "AASS-1.2.1.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(f"AASS-{version}/app.py", code)
        bundle.writestr(f"AASS-{version}/RELEASE-MANIFEST.json", json.dumps(manifest))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    scan = {
        "passed": True,
        "archive": archive.name,
        "archive_sha256": digest,
        "archive_exit": 0,
        "payload_exit": 0,
        "detections": 0,
        "engine": "fixture-engine",
        "signature_version": "fixture-signatures",
        "microsoft_scanner_signature": "Valid",
        "installed_environment_scanned": True,
        "browser_bundle_scanned": True,
    }
    (directory / "defender-scan.json").write_text(json.dumps(scan))
    (directory / "SHA256SUMS").write_text(digest + "  " + archive.name + "\n")
    (directory / "dependency-audit.json").write_text(
        json.dumps({"dependencies": [{"name": "fixture", "vulns": []}]})
    )
    (directory / "source-security.json").write_text(
        json.dumps({"results": [], "errors": [], "metrics": {"_totals": {"loc": 1}}})
    )
    return scan


def test_matching_archive_and_installed_runtime_evidence_pass(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    evidence_fixture(tmp_path)
    check(tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("archive_sha256", "b" * 64),
        ("archive", "another-release.zip"),
        ("installed_environment_scanned", False),
        ("browser_bundle_scanned", False),
        ("detections", 1),
    ],
)
def test_scan_of_other_or_incomplete_payload_cannot_publish(tmp_path, field, value):
    report = evidence_fixture(tmp_path)
    report[field] = value
    (tmp_path / "defender-scan.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="Defender evidence"):
        check(tmp_path)


@pytest.mark.parametrize("kwargs", [{"dirty": True}, {"version": "1.1.0"}])
def test_dirty_or_wrong_version_artifact_cannot_publish(tmp_path, kwargs):
    evidence_fixture(tmp_path, **kwargs)
    with pytest.raises(ValueError):
        check(tmp_path)


def test_different_source_revision_cannot_publish(tmp_path, monkeypatch):
    evidence_fixture(tmp_path)
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    with pytest.raises(ValueError, match="different source revision"):
        check(tmp_path)
