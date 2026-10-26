"""Refresh exact wheel hashes from the official PyPI JSON API; run only during maintenance."""

import concurrent.futures
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Reviewed runtime closure. Test/postgres/security tools are excluded from end-user installation.
RUNTIME = {
    "annotated-types": "0.8.0",
    "anyio": "4.15.1",
    "attrs": "26.1.0",
    "certifi": "2026.10.23",
    "cffi": "2.1.1",
    "click": "8.5.0",
    "cryptography": "50.0.2",
    "filelock": "4.2.1",
    "greenlet": "3.5.6",
    "h11": "0.16.0",
    "httpcore": "1.0.9",
    "httpx": "0.28.1",
    "httpx-sse": "0.4.3",
    "idna": "3.20",
    "jsonschema": "4.26.0",
    "jsonschema-specifications": "2025.9.1",
    "mcp": "1.30.0",
    "packaging": "26.3",
    "playwright": "1.64.1",
    "pycparser": "3.12",
    "pydantic": "2.14.1",
    "pydantic-core": "2.50.1",
    "pydantic-settings": "2.16.1",
    "pyee": "14.0.0",
    "pyjwt": "2.15.1",
    "python-dotenv": "1.2.4",
    "python-multipart": "0.0.32",
    "referencing": "0.37.0",
    "rpds-py": "2026.9.1",
    "sse-starlette": "3.6.0",
    "starlette": "1.10.0",
    "typing-extensions": "4.16.0",
    "typing-inspection": "0.4.4",
    "uvicorn": "0.54.0",
    "setuptools": "84.2.1",
    "wheel": "0.48.0",
}
DEV = {
    "pytest": "9.1.1",
    "pytest-asyncio": "1.4.1",
    "ruff": "0.17.2",
    "psycopg": "3.3.6",
    "psycopg-binary": "3.3.6",
    "iniconfig": "2.3.1",
    "pluggy": "1.7.0",
    "pygments": "2.21.0",
}


def requirement(item):
    name, version = item
    # Names/versions come only from the reviewed constant maps above; fixed verified HTTPS.
    with urllib.request.urlopen(  # nosec B310 # fixed official PyPI HTTPS metadata
        f"https://pypi.org/pypi/{name}/{version}/json", timeout=20
    ) as response:
        metadata = json.load(response)
    hashes = sorted(
        {
            file["digests"]["sha256"]
            for file in metadata["urls"]
            if file["packagetype"] == "bdist_wheel" and not file.get("yanked")
        }
    )
    if not hashes:
        raise RuntimeError(f"No verified wheels published for {name}=={version}")
    return name, f"{name}=={version} \\\n" + " \\\n".join(
        "    --hash=sha256:" + digest for digest in hashes
    ) + "\n"


def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        lines = dict(pool.map(requirement, sorted((RUNTIME | DEV).items())))
    header = "# Exact versions and SHA-256 wheel hashes from official PyPI. No sdists.\n"
    (ROOT / "requirements.lock").write_text(
        header + "\n".join(lines[name] for name in sorted(RUNTIME))
    )
    (ROOT / "requirements-dev.lock").write_text(
        header + "\n".join(lines[name] for name in sorted(RUNTIME | DEV))
    )
    postgres = RUNTIME | {name: DEV[name] for name in ("psycopg", "psycopg-binary")}
    (ROOT / "requirements-postgres.lock").write_text(
        header + "\n".join(lines[name] for name in sorted(postgres))
    )
    print(f"Locked {len(RUNTIME)} runtime and {len(RUNTIME | DEV)} development packages.")


if __name__ == "__main__":
    main()
