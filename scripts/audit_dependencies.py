"""Audit every pinned platform dependency, including Windows markers on a Linux auditor."""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from packaging.requirements import Requirement


def neutral_pins(path):
    pins = []
    for line in Path(path).read_text().splitlines():
        text = line.strip().rstrip("\\").strip()
        if not text or text.startswith(("#", "--")):
            continue
        requirement = Requirement(text)
        specs = list(requirement.specifier)
        if (
            requirement.url
            or len(specs) != 1
            or specs[0].operator != "=="
            or "*" in specs[0].version
        ):
            raise ValueError("Audit requires exact version pins, not arbitrary URLs or ranges")
        pins.append(requirement.name + "==" + specs[0].version)
    if not pins:
        raise ValueError("No pinned dependencies found")
    return sorted(set(pins))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--format", choices=["json", "cyclonedx-json"], default="json")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aass-audit-") as directory:
        path = Path(directory) / "all-platforms.txt"
        path.write_text("\n".join(neutral_pins(args.lock)) + "\n")
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pip_audit",
                "-r",
                str(path),
                "--disable-pip",
                "--no-deps",
                "-f",
                args.format,
                "-o",
                str(args.output),
            ],
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
