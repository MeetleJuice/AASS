"""Preserve bounded synthetic CI evidence even without a complete JUnit file."""

import json
import os
import re
import sys
from pathlib import Path


def safe(value):
    for name, secret in os.environ.items():
        if secret and (
            name.endswith(("_API_KEY", "_TOKEN", "_PASSWORD", "_DSN"))
            or name in {"GH_TOKEN", "GITHUB_TOKEN"}
        ):
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(
        r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]+)", "[REDACTED]", value
    )
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main():
    outcome, output, breadcrumb = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    print("::notice title=Windows test phase::Outcome: " + safe(outcome))
    exit_file = output.parent / "windows-process-exit.json"
    if exit_file.is_file():
        data = json.loads(exit_file.read_text(encoding="utf-8"))
        code = data.get("returncode")
        if isinstance(code, int):
            print(f"::notice title=Python process exit::{code} ({hex(code & 0xFFFFFFFF)})")
    if outcome != "success":
        if output.is_file():
            with output.open("rb") as stream:
                stream.seek(max(0, output.stat().st_size - 7000))
                tail = stream.read(7000).decode("utf-8", errors="replace")
            print("::error title=Windows output tail::" + safe(tail))
        if breadcrumb.is_file():
            name = breadcrumb.read_text(encoding="utf-8")[:1000]
            print(
                "::notice title=Last started test::"
                + safe(name)
                + "; this is not proof that this test caused the failure."
            )


if __name__ == "__main__":
    main()
