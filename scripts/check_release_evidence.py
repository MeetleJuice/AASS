"""Fail closed unless scan, dependency audit, source scan and exact artifact agree."""

import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_release import verify  # noqa: E402


def check(directory):
    directory = Path(directory)
    archive = directory / "AASS-1.2.0.zip"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    scan = json.loads((directory / "defender-scan.json").read_text(encoding="utf-8-sig"))
    if (
        scan.get("passed") is not True
        or scan.get("archive") != archive.name
        or scan.get("archive_sha256") != digest
        or scan.get("archive_exit") != 0
        or scan.get("payload_exit") != 0
        or scan.get("detections") != 0
        or not scan.get("engine")
        or not scan.get("signature_version")
        or scan.get("microsoft_scanner_signature") != "Valid"
        or scan.get("installed_environment_scanned") is not True
        or scan.get("browser_bundle_scanned") is not True
    ):
        raise ValueError("No successful Microsoft Defender evidence for this exact archive")
    expected = (directory / "SHA256SUMS").read_text().strip()
    if expected != digest + "  " + archive.name:
        raise ValueError("Release checksum mismatch")
    audit = json.loads((directory / "dependency-audit.json").read_text())
    if not audit.get("dependencies") or any(dep.get("vulns") for dep in audit["dependencies"]):
        raise ValueError("Dependency audit is missing or reports vulnerabilities")
    source = json.loads((directory / "source-security.json").read_text())
    if (
        not isinstance(source.get("results"), list)
        or not source.get("metrics")
        or source.get("errors")
        or any(f.get("issue_severity") in ("MEDIUM", "HIGH") for f in source.get("results", []))
    ):
        raise ValueError("Source security scan failed")
    with tempfile.TemporaryDirectory(prefix="aass-evidence-") as scratch:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                parts = Path(info.filename).parts
                if ".." in parts or info.filename.startswith(("/", "\\")):
                    raise ValueError("Unsafe archive path")
            if (
                len(bundle.infolist()) > 500
                or sum(info.file_size for info in bundle.infolist()) > 20 * 1024 * 1024
            ):
                raise ValueError("Release archive exceeds source size limits")
            bundle.extractall(scratch)
        roots = list(Path(scratch).iterdir())
        if len(roots) != 1:
            raise ValueError("Unexpected archive roots")
        manifest = verify(roots[0])
        if manifest.get("version") != "1.2.0" or roots[0].name != "AASS-1.2.0":
            raise ValueError("Artifact version does not match the reviewed release")
        if manifest.get("dirty") or not manifest.get("source_revision"):
            raise ValueError("Cannot publish a dirty or unidentified source tree")
    if os.environ.get("GITHUB_SHA") and manifest["source_revision"] != os.environ["GITHUB_SHA"]:
        raise ValueError("Artifact belongs to a different source revision")
    print("Release evidence matches the exact archive.")


if __name__ == "__main__":
    check(sys.argv[1])
