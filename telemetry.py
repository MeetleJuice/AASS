"""Atomic state and bounded, secret-free event metadata (single-writer per workspace)."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".aass-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Trajectory:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.exists():
            atomic_json(self.path, [])
        self.events()  # Corruption is a visible failure, never silently discarded.

    def events(self):
        data = json.loads(self.path.read_text())
        if not isinstance(data, list):
            raise ValueError("Trajectory must be an array")
        return data

    def append(self, *, iteration, files_modified, error_signature, action, strategy, run_id=None):
        events = self.events()
        events.append(
            {
                "run_id": run_id,
                "iteration": iteration,
                "files_modified": sorted(files_modified),
                "error_signature": error_signature,
                "action": action,
                "strategy": strategy,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        atomic_json(self.path, events[-1000:])
