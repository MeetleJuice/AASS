"""Complete-release update acceptance and preservation at trust boundaries."""

import hashlib
import io
import json
import stat
import urllib.error
import zipfile

import pytest

import update_manager as updates

REVISION = "a" * 40
TAG = "v1.3.0-aaaaaaa"
VERSION = "1.3.0"
ARCHIVE = "AASS-1.3.0.zip"
PREFIX = "AASS-1.3.0/"


class Response(io.BytesIO):
    def __init__(self, data, url, *, length=None):
        super().__init__(data)
        self.url = url
        self.headers = {"Content-Length": str(len(data) if length is None else length)}

    def geturl(self):
        return self.url


class Transport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        assert 0 < timeout <= 20
        value = self.responses[request.full_url]
        if isinstance(value, BaseException):
            raise value
        if callable(value):
            return value(request)
        return Response(value, request.full_url)


def release():
    names = {ARCHIVE, *updates.EVIDENCE_NAMES}
    return updates.Release(
        TAG,
        VERSION,
        ARCHIVE,
        {
            name: f"https://github.com/MeetleJuice/AASS/releases/download/{TAG}/{name}"
            for name in names
        },
    )


def api_payload():
    current = release()
    return {
        "tag_name": TAG,
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": name, "browser_download_url": url} for name, url in current.assets.items()
        ],
    }


def make_assets(*, extra=None, manifest_updates=None, symlink=None):
    files = {
        "app.py": b"print('reviewed app')\n",
        "assets/aass.ico": b"\x00\x00\x01\x00\r\nicon-binary",
    }
    manifest = {
        "format": 1,
        "version": VERSION,
        "source_revision": REVISION,
        "dirty": False,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    manifest.update(manifest_updates or {})
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(PREFIX + name, data)
        archive.writestr(PREFIX + "RELEASE-MANIFEST.json", json.dumps(manifest))
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(PREFIX + symlink)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "../../private")
    data = memory.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    report = {
        "passed": True,
        "archive": ARCHIVE,
        "archive_sha256": digest,
        "archive_exit": 0,
        "payload_exit": 0,
        "detections": 0,
        "engine": "reviewed-engine",
        "signature_version": "reviewed-signatures",
        "microsoft_scanner_signature": "Valid",
        "installed_environment_scanned": True,
        "browser_bundle_scanned": True,
    }
    return {
        ARCHIVE: data,
        "SHA256SUMS": (digest + "  " + ARCHIVE + "\n").encode(),
        "defender-scan.json": json.dumps(report).encode(),
        "dependency-audit.json": json.dumps(
            {"dependencies": [{"name": "fixture", "vulns": []}]}
        ).encode(),
        "source-security.json": json.dumps(
            {"results": [], "metrics": {"_totals": {"loc": 1}}, "errors": []}
        ).encode(),
        "SBOM.json": json.dumps(
            {"bomFormat": "CycloneDX", "components": [{"name": "fixture"}]}
        ).encode(),
    }


def transport(assets):
    return Transport({release().assets[name]: data for name, data in assets.items()})


def change_json(assets, name, **values):
    obj = json.loads(assets[name])
    obj.update(values)
    assets[name] = json.dumps(obj).encode()


def test_api_discovery_is_fixed_repo_stable_release_without_credentials(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private-key-not-for-updates")
    http = Transport({updates.API_URL: json.dumps(api_payload()).encode()})
    result = updates.discover_release(opener=http)
    assert result == release()
    assert len(http.calls) == 1
    assert "Authorization" not in dict(http.calls[0].header_items())
    assert "private-key" not in repr(http.calls[0].header_items())


def test_api_rate_limit_falls_back_to_public_official_latest_assets():
    current = release()
    html = "".join(
        f'<a href="/{updates.REPOSITORY}/releases/download/{TAG}/{name}">{name}</a>'
        for name in current.assets
    )
    rate_limit = urllib.error.HTTPError(updates.API_URL, 403, "private raw error", {}, None)
    http = Transport(
        {
            updates.API_URL: rate_limit,
            updates.LATEST_URL: lambda request: Response(
                b"ignored", f"https://github.com/MeetleJuice/AASS/releases/tag/{TAG}"
            ),
            f"https://github.com/MeetleJuice/AASS/releases/expanded_assets/{TAG}": html.encode(),
        }
    )
    assert updates.discover_release(opener=http) == current
    assert len(http.calls) == 3


@pytest.mark.parametrize("value", ["v1.3.0", "main", "v1.3.0-AAAAAAA", "v1.3.0-aaaaaaa?key=secret"])
def test_nonreviewed_release_tags_fail_before_asset_download(value):
    payload = api_payload()
    payload["tag_name"] = value
    http = Transport({updates.API_URL: json.dumps(payload).encode()})
    with pytest.raises(updates.UpdateError, match="supported"):
        updates.discover_release(opener=http)
    assert len(http.calls) == 1


@pytest.mark.parametrize("field", ["draft", "prerelease"])
def test_unpublished_or_prerelease_cannot_be_installed(field):
    payload = api_payload()
    payload[field] = True
    with pytest.raises(updates.UpdateError, match="published stable"):
        updates.discover_release(opener=Transport({updates.API_URL: json.dumps(payload).encode()}))


def test_release_missing_required_evidence_is_not_replaced_by_weaker_source_zip():
    payload = api_payload()
    payload["assets"] = [item for item in payload["assets"] if item["name"] != "defender-scan.json"]
    with pytest.raises(updates.UpdateError) as caught:
        updates.discover_release(opener=Transport({updates.API_URL: json.dumps(payload).encode()}))
    assert caught.value.code == "missing_release_evidence"


def test_release_asset_cannot_point_to_another_repo_or_host():
    payload = api_payload()
    payload["assets"][0]["browser_download_url"] = (
        "https://github.com/attacker/other/releases/download/tag/file"
    )
    with pytest.raises(updates.UpdateError) as caught:
        updates.discover_release(opener=Transport({updates.API_URL: json.dumps(payload).encode()}))
    assert caught.value.code == "untrusted_asset"


def test_fallback_redirect_cannot_select_another_repository():
    http = Transport(
        {
            updates.API_URL: urllib.error.URLError("private-url-token"),
            updates.LATEST_URL: lambda request: Response(
                b"", "https://github.com/attacker/other/releases/tag/" + TAG
            ),
        }
    )
    with pytest.raises(updates.UpdateError) as caught:
        updates.discover_release(opener=http)
    assert caught.value.code == "invalid_release"
    assert "private-url-token" not in str(caught.value)


def test_download_verifies_whole_source_and_preserves_existing_state(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    secret = existing / ".env"
    secret.write_text("GEMINI_API_KEY=must-remain-private\n")
    messages = []
    result = updates.download_release(
        tmp_path / "stage", messages.append, release=release(), opener=transport(make_assets())
    )
    assert result.root.name == "AASS-1.3.0"
    assert result.manifest["source_revision"] == REVISION
    assert result.directory.is_dir()
    assert (result.root / "assets/aass.ico").read_bytes() == b"\x00\x00\x01\x00\r\nicon-binary"
    assert secret.read_text() == "GEMINI_API_KEY=must-remain-private\n"
    assert "must-remain-private" not in "".join(messages)
    assert not (existing / "app.py").exists()


@pytest.mark.parametrize(
    "kind",
    [
        "checksum",
        "archive",
        "scan",
        "payload",
        "browser",
        "source",
        "dependency",
        "sbom",
        "report_json",
    ],
)
def test_failed_artifact_or_evidence_never_leaves_installable_source(tmp_path, kind):
    assets = make_assets()
    if kind == "checksum":
        assets["SHA256SUMS"] = ("0" * 64 + "  " + ARCHIVE).encode()
    elif kind == "archive":
        assets[ARCHIVE] += b"tampered"
    elif kind == "scan":
        change_json(assets, "defender-scan.json", detections=1)
    elif kind == "payload":
        change_json(assets, "defender-scan.json", installed_environment_scanned=False)
    elif kind == "browser":
        change_json(assets, "defender-scan.json", browser_bundle_scanned=False)
    elif kind == "source":
        change_json(assets, "source-security.json", results=[{"issue_severity": "HIGH"}])
    elif kind == "dependency":
        change_json(assets, "dependency-audit.json", dependencies=[{"vulns": [{"id": "known"}]}])
    elif kind == "sbom":
        change_json(assets, "SBOM.json", components=[])
    else:
        assets["defender-scan.json"] = b"private-malformed-body"
    stage = tmp_path / "stage"
    with pytest.raises(updates.UpdateError) as caught:
        updates.download_release(stage, release=release(), opener=transport(assets))
    assert not list(stage.iterdir())
    assert "private-malformed-body" not in str(caught.value)


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        PREFIX + "../outside.py",
        "/absolute.py",
        PREFIX + "x\\outside.py",
        PREFIX + "C:/outside.py",
        PREFIX + "NUL.txt",
        PREFIX + "trailing .",
        PREFIX + ".aass/credentials.json",
        PREFIX + ".env",
        PREFIX + "app.exe",
        PREFIX + "APP.py",
    ],
)
def test_unsafe_or_private_extra_archive_entries_are_rejected(tmp_path, path):
    assets = make_assets(extra={path: b"private or unreviewed"})
    with pytest.raises(updates.UpdateError):
        updates.download_release(tmp_path / "stage", release=release(), opener=transport(assets))
    assert not (tmp_path / "outside.py").exists()
    assert not list((tmp_path / "stage").iterdir())


def test_symlink_in_archive_is_not_followed_or_extracted(tmp_path):
    with pytest.raises(updates.UpdateError) as caught:
        updates.download_release(
            tmp_path / "stage",
            release=release(),
            opener=transport(make_assets(symlink="linked.py")),
        )
    assert caught.value.code == "unsafe_archive"


@pytest.mark.parametrize(
    "values",
    [
        {"dirty": True},
        {"source_revision": "b" * 40},
        {"source_revision": "main"},
        {"version": "1.2.9"},
    ],
)
def test_manifest_must_match_clean_tagged_source(tmp_path, values):
    with pytest.raises(updates.UpdateError) as caught:
        updates.download_release(
            tmp_path / "stage",
            release=release(),
            opener=transport(make_assets(manifest_updates=values)),
        )
    assert caught.value.code == "unreviewed_source"


def test_partial_network_failure_cleans_only_its_own_staging(tmp_path):
    assets = make_assets()
    http = transport(assets)
    http.responses[release().assets["defender-scan.json"]] = urllib.error.URLError(
        "https://private.example/?key=secret"
    )
    stage = tmp_path / "stage"
    stage.mkdir()
    previous = stage / "previous-reviewed-update"
    previous.mkdir()
    (previous / "keep.txt").write_text("preserve")
    with pytest.raises(updates.UpdateError) as caught:
        updates.download_release(stage, release=release(), opener=http)
    assert sorted(p.name for p in stage.iterdir()) == [previous.name]
    assert "secret" not in str(caught.value)


def test_asset_redirect_to_unapproved_host_fails(tmp_path):
    http = transport(make_assets())
    http.responses[release().assets[ARCHIVE]] = lambda request: Response(
        b"ignored", "https://attacker.example/payload"
    )
    with pytest.raises(updates.UpdateError) as caught:
        updates.download_release(tmp_path / "stage", release=release(), opener=http)
    assert caught.value.code == "untrusted_download"


def test_https_redirect_handler_cannot_downgrade_or_send_to_arbitrary_host():
    request = __import__("urllib.request", fromlist=["Request"]).Request(release().assets[ARCHIVE])
    handler = updates._Redirect()
    for destination in [
        "http://github.com/file",
        "file:///tmp/file",
        "https://user:secret@github.com/file",
        "https://attacker.github.com/file",
    ]:
        with pytest.raises(updates.UpdateError):
            handler.redirect_request(request, None, 302, "Found", {}, destination)


def test_oversized_download_stops_before_source_extraction(tmp_path):
    http = transport(make_assets())
    http.responses[release().assets[ARCHIVE]] = lambda request: Response(
        b"small", request.full_url, length=updates.MAX_ARCHIVE_BYTES + 1
    )
    with pytest.raises(updates.UpdateError) as caught:
        updates.download_release(tmp_path / "stage", release=release(), opener=http)
    assert caught.value.code == "download_size"
    assert not list((tmp_path / "stage").iterdir())


def test_revalidates_injected_release_before_any_download(tmp_path):
    bad = updates.Release(TAG, VERSION, ARCHIVE, {ARCHIVE: "https://attacker.example/payload"})
    http = Transport({})
    with pytest.raises(updates.UpdateError):
        updates.download_release(tmp_path / "stage", release=bad, opener=http)
    assert not http.calls
    assert not (tmp_path / "stage").exists()


def test_slow_metadata_body_has_an_absolute_deadline(monkeypatch):
    class SlowResponse(Response):
        def read1(self, _size):
            return super().read(1)

    ticks = 0

    def clock():
        nonlocal ticks
        ticks += 3
        return ticks

    monkeypatch.setattr(updates.time, "monotonic", clock)
    http = Transport({updates.API_URL: lambda request: SlowResponse(b"x" * 100, request.full_url)})
    with pytest.raises(updates.UpdateError) as caught:
        updates._read(updates.API_URL, limit=200, opener=http)
    assert caught.value.code == "download_timeout"


def test_truncated_download_is_rejected_and_staging_removed(tmp_path):
    http = transport(make_assets())
    original = make_assets()[ARCHIVE]
    http.responses[release().assets[ARCHIVE]] = lambda request: Response(
        original[:-5], request.full_url, length=len(original)
    )
    with pytest.raises(updates.UpdateError) as caught:
        updates.download_release(tmp_path / "stage", release=release(), opener=http)
    assert caught.value.code == "incomplete_download"
    assert not list((tmp_path / "stage").iterdir())


def test_declared_source_hash_mismatch_is_not_activated(tmp_path):
    assets = make_assets(
        manifest_updates={
            "files": {
                "app.py": "0" * 64,
                "assets/aass.ico": hashlib.sha256(b"\x00\x00\x01\x00\r\nicon-binary").hexdigest(),
            }
        }
    )
    with pytest.raises(updates.UpdateError):
        updates.download_release(tmp_path / "stage", release=release(), opener=transport(assets))
    assert not list((tmp_path / "stage").iterdir())
