"""Fetch and verify complete AASS releases from the fixed official GitHub repo.

The updater never reads API keys or executes downloaded code. HTTPS origin,
checksums and attached release evidence establish publisher-controlled release
integrity; they are not an Authenticode signature or a universal AV guarantee.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from verify_release import is_link, verify

REPOSITORY = "MeetleJuice/AASS"
WEB_ORIGIN = "https://github.com"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
LATEST_URL = f"{WEB_ORIGIN}/{REPOSITORY}/releases/latest"
ASSET_HOSTS = {
    "github.com",
    "api.github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
}
EVIDENCE_NAMES = (
    "SHA256SUMS",
    "defender-scan.json",
    "dependency-audit.json",
    "source-security.json",
    "SBOM.json",
)
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 48 * 1024 * 1024
MAX_EXTRACTED_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILES = 500
MAX_DOWNLOAD_SECONDS = 180
TAG = re.compile(
    r"v((?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3}))-([0-9a-f]{7,40})\Z"
)
SHA = re.compile(r"[0-9a-f]{40}\Z")
RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
PRIVATE_PARTS = {".aass", ".venv", ".git", "generated", "__pycache__"}
BINARY_SUFFIXES = {
    ".exe",
    ".dll",
    ".pyd",
    ".so",
    ".msi",
    ".com",
    ".scr",
    ".zip",
    ".whl",
    ".7z",
    ".tar",
    ".gz",
}


class UpdateError(RuntimeError):
    """Only fixed, user-reviewable messages; never raw HTTP URLs or response bodies."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Release:
    tag: str
    version: str
    archive_name: str
    assets: dict[str, str]

    @property
    def source_prefix(self):
        return TAG.fullmatch(self.tag)[2]


@dataclass(frozen=True)
class VerifiedRelease:
    root: Path
    manifest: dict
    release: Release
    archive_sha256: str

    @property
    def directory(self):
        return self.root.parent.parent


class _Redirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def redirect_request(self, request, fp, code, message, headers, newurl):
        _approved_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if isinstance(href, str):
                self.links.append(href)


def _approved_url(value):
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ASSET_HOSTS
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise UpdateError(
            "untrusted_download",
            "GitHub redirected the update to an unapproved destination. The existing installation was preserved.",
        )
    return value


def _opener(opener=None):
    return opener or urllib.request.build_opener(_Redirect())


def _read(url, *, limit, opener, deadline=None):
    _approved_url(url)
    deadline = deadline if deadline is not None else time.monotonic() + 20
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise UpdateError(
            "download_timeout",
            "The update download took too long. Retry when the connection is responsive.",
        )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AASS-Release-Updater",
            "Accept": "application/vnd.github+json" if url == API_URL else "*/*",
        },
    )
    call = opener.open if hasattr(opener, "open") else opener
    with call(request, timeout=min(20, remaining)) as response:
        _approved_url(response.geturl())
        length = response.headers.get("Content-Length")
        if length is not None:
            try:
                if int(length) < 0 or int(length) > limit:
                    raise UpdateError(
                        "download_size", "The release download exceeds the supported size limit."
                    )
            except ValueError:
                raise UpdateError(
                    "invalid_download", "GitHub returned an invalid download length."
                ) from None
        data = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise UpdateError(
                    "download_timeout",
                    "The update download took too long. Retry when the connection is responsive.",
                )
            # HTTPResponse.read1 returns after one buffered/socket read rather
            # than waiting to fill a large chunk while a slow peer drips bytes.
            reader = getattr(response, "read1", response.read)
            chunk = reader(min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > limit:
                raise UpdateError(
                    "download_size", "The release download exceeds the supported size limit."
                )
        if length is not None and int(length) != len(data):
            raise UpdateError(
                "incomplete_download",
                "The update download was incomplete. Retry it; the existing installation is unchanged.",
            )
    return bytes(data)


def _tag_release(tag, assets):
    match = TAG.fullmatch(tag) if isinstance(tag, str) else None
    if not match:
        raise UpdateError(
            "invalid_release", "The latest GitHub entry is not a supported verified AASS release."
        )
    version = match[1]
    archive = f"AASS-{version}.zip"
    expected = {archive, *EVIDENCE_NAMES}
    if not isinstance(assets, dict) or set(assets) != expected:
        raise UpdateError(
            "missing_release_evidence",
            "The GitHub release is missing its full ZIP or required verification reports. It cannot be installed yet.",
        )
    for name, url in assets.items():
        expected_url = f"{WEB_ORIGIN}/{REPOSITORY}/releases/download/{tag}/{name}"
        if url != expected_url:
            raise UpdateError(
                "untrusted_asset",
                "The release contains an unexpected download location. The existing installation was preserved.",
            )
    return Release(tag, version, archive, assets)


def _api_release(data):
    if (
        not isinstance(data, dict)
        or data.get("draft") is not False
        or data.get("prerelease") is not False
    ):
        raise UpdateError(
            "invalid_release", "The latest GitHub entry is not a published stable AASS release."
        )
    tag = data.get("tag_name")
    match = TAG.fullmatch(tag) if isinstance(tag, str) else None
    if not match:
        raise UpdateError(
            "invalid_release", "The latest GitHub entry is not a supported verified AASS release."
        )
    expected = {f"AASS-{match[1]}.zip", *EVIDENCE_NAMES}
    entries = data.get("assets")
    if not isinstance(entries, list) or len(entries) > 100:
        raise UpdateError("invalid_release", "GitHub returned an invalid release asset list.")
    assets = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise UpdateError("invalid_release", "GitHub returned an invalid release asset entry.")
        name = entry.get("name")
        if name in expected:
            if name in assets:
                raise UpdateError(
                    "invalid_release", "The release contains duplicate download names."
                )
            assets[name] = entry.get("browser_download_url")
    return _tag_release(tag, assets)


def discover_release(*, opener=None):
    """Find the newest published release without tokens or arbitrary repo access."""
    transport = _opener(opener)
    try:
        try:
            raw = _read(API_URL, limit=MAX_METADATA_BYTES, opener=transport)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            raw = None
        if raw is not None:
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                raise UpdateError(
                    "invalid_release", "GitHub returned invalid release metadata."
                ) from None
            return _api_release(payload)
        # Public HTML fallback works without an API token if API rate limits or
        # network policy block api.github.com. The final tag remains fixed-repo.
        request = urllib.request.Request(LATEST_URL, headers={"User-Agent": "AASS-Release-Updater"})
        call = transport.open if hasattr(transport, "open") else transport
        with call(request, timeout=20) as response:
            final = response.geturl()
            _approved_url(final)
            prefix = f"{WEB_ORIGIN}/{REPOSITORY}/releases/tag/"
            if not final.startswith(prefix):
                raise UpdateError(
                    "invalid_release", "GitHub did not identify a stable AASS release."
                )
            tag = final.removeprefix(prefix)
            match = TAG.fullmatch(tag)
            if not match:
                raise UpdateError(
                    "invalid_release", "GitHub did not identify a supported stable AASS release."
                )
        assets_url = f"{WEB_ORIGIN}/{REPOSITORY}/releases/expanded_assets/{tag}"
        html = _read(assets_url, limit=MAX_METADATA_BYTES, opener=transport).decode("utf-8")
        links = _Links()
        links.feed(html)
        expected = {f"AASS-{match[1]}.zip", *EVIDENCE_NAMES}
        assets = {}
        prefix = f"/{REPOSITORY}/releases/download/{tag}/"
        for href in links.links:
            if href.startswith(prefix) and href.removeprefix(prefix) in expected:
                name = href.removeprefix(prefix)
                if name in assets:
                    raise UpdateError(
                        "invalid_release", "The release contains duplicate download names."
                    )
                assets[name] = WEB_ORIGIN + href
        return _tag_release(tag, assets)
    except UpdateError:
        raise
    except (OSError, ValueError, UnicodeError, urllib.error.URLError):
        raise UpdateError(
            "release_connection",
            "Could not check GitHub for updates. Check the connection and try again; the existing installation is unchanged.",
        ) from None


def _json_file(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        raise UpdateError(
            "invalid_evidence", "A release verification report is missing or malformed."
        ) from None
    if not isinstance(data, dict):
        raise UpdateError("invalid_evidence", "A release verification report is malformed.")
    return data


def _verify_reports(directory, release, digest):
    checksum = (directory / "SHA256SUMS").read_text(encoding="utf-8-sig").strip()
    if checksum != digest + "  " + release.archive_name:
        raise UpdateError(
            "checksum_mismatch",
            "The downloaded release checksum does not match. Nothing was installed.",
        )
    report = _json_file(directory / "defender-scan.json")
    if (
        report.get("passed") is not True
        or report.get("archive") != release.archive_name
        or report.get("archive_sha256") != digest
        or report.get("archive_exit") != 0
        or report.get("payload_exit") != 0
        or report.get("detections") != 0
        or not report.get("engine")
        or not report.get("signature_version")
        or report.get("microsoft_scanner_signature") != "Valid"
        or report.get("installed_environment_scanned") is not True
        or report.get("browser_bundle_scanned") is not True
    ):
        raise UpdateError(
            "scan_evidence",
            "The release has no successful Microsoft Defender scan for this exact ZIP and installed payload. Nothing was installed.",
        )
    audit = _json_file(directory / "dependency-audit.json")
    dependencies = audit.get("dependencies")
    if (
        not isinstance(dependencies, list)
        or not dependencies
        or any(not isinstance(dep, dict) or dep.get("vulns") != [] for dep in dependencies)
    ):
        raise UpdateError(
            "dependency_evidence",
            "The release dependency review is missing or reports vulnerabilities. Nothing was installed.",
        )
    source = _json_file(directory / "source-security.json")
    results = source.get("results")
    if (
        not isinstance(results, list)
        or not source.get("metrics")
        or source.get("errors")
        or any(
            not isinstance(item, dict) or item.get("issue_severity") in ("MEDIUM", "HIGH")
            for item in results
        )
    ):
        raise UpdateError(
            "source_evidence",
            "The release source review is missing or reports unresolved findings. Nothing was installed.",
        )
    sbom = _json_file(directory / "SBOM.json")
    if (
        sbom.get("bomFormat") != "CycloneDX"
        or not isinstance(sbom.get("components"), list)
        or not sbom["components"]
    ):
        raise UpdateError(
            "sbom_evidence",
            "The release dependency inventory is missing or malformed. Nothing was installed.",
        )


def _safe_parts(name):
    parts = name.rstrip("/").split("/")
    if not parts or any(
        not part
        or part in {".", ".."}
        or part[-1:] in {".", " "}
        or any(ord(c) < 32 or c in '\\<>:"|?*' for c in part)
        or part.split(".", 1)[0].upper() in RESERVED
        for part in parts
    ):
        raise UpdateError(
            "unsafe_archive", "The release ZIP contains an unsafe file path. Nothing was installed."
        )
    return parts


def _extract(directory, release):
    archive_path = directory / release.archive_name
    destination = directory / "source"
    destination.mkdir()
    expected_root = f"AASS-{release.version}"
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if (
                not 1 <= len(entries) <= MAX_FILES
                or sum(info.file_size for info in entries) > MAX_EXTRACTED_BYTES
            ):
                raise UpdateError(
                    "archive_size",
                    "The release ZIP exceeds supported source limits. Nothing was installed.",
                )
            seen = set()
            manifest_name = expected_root + "/RELEASE-MANIFEST.json"
            for info in entries:
                parts = _safe_parts(info.filename)
                key = info.filename.rstrip("/").casefold()
                mode = info.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if (
                    parts[0] != expected_root
                    or key in seen
                    or info.flag_bits & 1
                    or file_type not in (0, stat.S_IFREG, stat.S_IFDIR)
                    or info.file_size > MAX_FILE_BYTES
                ):
                    raise UpdateError(
                        "unsafe_archive",
                        "The release ZIP contains unsafe or duplicate source entries. Nothing was installed.",
                    )
                seen.add(key)
                if len(parts) > 1:
                    relative = PurePosixPath(*parts[1:])
                    if (
                        any(part.casefold() in PRIVATE_PARTS for part in relative.parts)
                        or relative.name.casefold().startswith(".env")
                        and relative.name != ".env.example"
                        or relative.suffix.casefold() in BINARY_SUFFIXES
                    ):
                        raise UpdateError(
                            "private_archive",
                            "The release ZIP contains private state or unexpected binary payloads. Nothing was installed.",
                        )
            try:
                manifest = json.loads(archive.read(manifest_name))
            except (KeyError, ValueError, UnicodeError):
                raise UpdateError(
                    "invalid_manifest", "The release ZIP has no valid source manifest."
                ) from None
            if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
                raise UpdateError("invalid_manifest", "The release source manifest is malformed.")
            expected = {expected_root + "/" + name for name in manifest["files"]} | {manifest_name}
            actual = {info.filename for info in entries if not info.is_dir()}
            if expected != actual:
                raise UpdateError(
                    "invalid_manifest", "The release ZIP contains files missing from its manifest."
                )
            for info in entries:
                parts = _safe_parts(info.filename)
                target = destination.joinpath(*parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, length=65536)
        root = destination / expected_root
        checked = verify(root)
        revision = checked.get("source_revision")
        if (
            checked.get("version") != release.version
            or checked.get("dirty") is not False
            or not isinstance(revision, str)
            or not SHA.fullmatch(revision)
            or not revision.startswith(release.source_prefix)
        ):
            raise UpdateError(
                "unreviewed_source",
                "The release manifest does not match its clean published source revision.",
            )
        return root, checked
    except UpdateError:
        raise
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile):
        raise UpdateError(
            "invalid_archive",
            "The downloaded release could not be verified or extracted. Nothing was installed.",
        ) from None


def download_release(stage, callback=None, *, release=None, opener=None):
    """Download into an owned new staging directory and return verified source.

    Existing application files, environments and private state are never touched.
    Callers may activate the returned source only after their preparation checks.
    """
    work = None
    try:
        release = release or discover_release(opener=opener)
        # Revalidate even caller-provided metadata so this function cannot fetch
        # arbitrary URLs or install a partial/different GitHub artifact.
        release = _tag_release(release.tag, release.assets)
        stage = Path(stage)
        if is_link(stage):
            raise UpdateError(
                "unsafe_staging", "The update staging directory must be a normal local directory."
            )
        stage.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="release-", dir=stage))
        transport = _opener(opener)
        deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
        total = 0
        for name in (release.archive_name, *EVIDENCE_NAMES):
            if callback:
                callback("Downloading " + name + "...")
            data = _read(
                release.assets[name],
                limit=MAX_ARCHIVE_BYTES if name == release.archive_name else MAX_METADATA_BYTES,
                opener=transport,
                deadline=deadline,
            )
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise UpdateError(
                    "download_size", "The release download exceeds the total size limit."
                )
            (work / name).write_bytes(data)
        digest = hashlib.sha256((work / release.archive_name).read_bytes()).hexdigest()
        if callback:
            callback("Checking archive checksum, scan reports and source manifest...")
        _verify_reports(work, release, digest)
        root, manifest = _extract(work, release)
        if callback:
            callback(
                "Verified AASS "
                + release.version
                + " source "
                + manifest["source_revision"][:7]
                + "."
            )
        return VerifiedRelease(root, manifest, release, digest)
    except UpdateError:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
        raise
    except (OSError, ValueError, UnicodeError, urllib.error.URLError):
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
        raise UpdateError(
            "update_download",
            "The release download could not finish. Retry when GitHub and the connection are responsive; the existing installation is unchanged.",
        ) from None
