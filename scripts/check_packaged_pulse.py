"""Exercise installed Pulse without model requests; keep Windows gates intact."""

import argparse
import json
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--python", required=True)
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
a = parser.parse_args()
r = subprocess.run(
    [a.python, "-m", "pulse.cli", "--root", str(a.root), "--directory", str(a.output)],
    cwd=a.root,
    capture_output=True,
    timeout=180,
)
assert r.returncode == 0, "Packaged Pulse process failed"
summary = json.loads((a.output / "summary.json").read_text())
rows = json.loads((a.output / "benchmark-results.json").read_text())
assert summary["status"] in {"passed", "blocked"}, summary["status"]
assert len(rows) == 8 and summary["total"] == 8
assert all(row["status"] in {"passed", "blocked"} for row in rows)
assert "model_requested" not in (a.output / "events.jsonl").read_text()
probe = "from pulse.report import export_zip,open_report; import sys; export_zip(sys.argv[1],sys.argv[2]); assert open_report(sys.argv[2])['summary']['total']==8"
result = subprocess.run(
    [a.python, "-c", probe, str(a.output), str(a.output / "report.zip")],
    cwd=a.root,
    capture_output=True,
    timeout=30,
)
assert result.returncode == 0, "Packaged Pulse export/reopen failed"
print(
    "Installed Pulse completed eight bounded diagnostics and exported/reopened its report without model calls."
)
