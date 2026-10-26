"""Expose concise public CI test annotations without dumping environments or full logs."""

import re
import sys
import xml.etree.ElementTree as ET


def main(path):
    root = ET.parse(path).getroot()  # nosec B314 # trusted local pytest output
    for case in root.iter("testcase"):
        for failure in list(case.findall("failure")) + list(case.findall("error")):
            text = "\n".join((failure.text or failure.get("message", "")).splitlines()[-12:])[
                -1800:
            ]
            text = re.sub(
                r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]+)",
                "[REDACTED]",
                text,
            )
            text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            title = (case.get("classname", "") + "." + case.get("name", "")).replace(",", "_")
            print(f"::error title={title}::{text}")


if __name__ == "__main__":
    main(sys.argv[1])
