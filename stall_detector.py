"""Preserves the initializer's three-event fixation intercept; ignores successes."""

import json
from pathlib import Path


def check_fixation(history_path="trajectory.json", run_id=None):
    history = json.loads(Path(history_path).read_text())
    if not isinstance(history, list):
        raise ValueError("Trajectory must be an array")
    if run_id is not None:
        history = [event for event in history if event.get("run_id") == run_id]
    if len(history) < 3:
        return False
    recent = history[-3:]
    return (
        all(item.get("error_signature") not in (None, "", "INIT", "SUCCESS") for item in recent)
        and len({tuple(sorted(t["files_modified"])) for t in recent}) == 1
        and len({t["error_signature"] for t in recent}) == 1
    )
