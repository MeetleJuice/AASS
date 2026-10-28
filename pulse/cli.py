"""Pulse process boundary: only sanitized event metadata is written to stdout."""

import argparse
import json
from pathlib import Path

from pulse.engine import PulseEngine


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--live-local", action="store_true")
    parser.add_argument("--live-cloud", action="store_true")
    args = parser.parse_args(argv)

    def stream(event):
        print("PULSE " + json.dumps(event), flush=True)

    engine = PulseEngine(
        args.root,
        directory=args.directory,
        live_local=args.live_local,
        live_cloud=args.live_cloud,
        callback=stream,
    )
    engine.run()
    return 0  # Failure/blocked/cancelled statuses are persisted, never inferred from process exit.


if __name__ == "__main__":
    raise SystemExit(main())
