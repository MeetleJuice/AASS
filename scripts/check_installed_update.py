"""Exercise a packaged same-revision update with real runtime checks, without model calls."""

import argparse
import json
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    root, source = args.root.resolve(), args.source.resolve()
    if sys.prefix != sys.base_prefix:
        parser.error("Run this check with base Python, outside the installed virtual environment.")
    if root == source or root.is_relative_to(source) or source.is_relative_to(root):
        parser.error("The installed application and pristine release must be separate folders.")
    sys.path.insert(0, str(root))
    from app_lifecycle import _managed, apply_transaction
    from settings import (
        is_link,
        provider_preferences,
        save_credentials_file,
        save_provider_preferences,
        selected_credentials_file,
    )
    from verify_release import verify

    _managed(root)
    installed, pristine = verify(root), verify(source)
    if installed != pristine or installed.get("dirty"):
        parser.error("This check requires matching clean installed and pristine release manifests.")
    manifest = (root / "RELEASE-MANIFEST.json").read_bytes()
    markers = {
        name: (root / ".venv" / name).read_bytes()
        for name in (".aass-dependencies", ".aass-application")
    }
    settings = [root / ".aass" / name for name in ("credentials.json", "provider.json")]
    originals = {}
    for path in settings:
        if is_link(path) or (path.exists() and (not path.is_file() or path.stat().st_size > 8192)):
            parser.error("Existing settings cannot be safely saved for this check.")
        originals[path] = path.read_bytes() if path.exists() else None
    try:
        with tempfile.TemporaryDirectory(prefix="aass-update-verification-") as directory:
            private = Path(directory) / "selected.env"
            private.write_text("# Verification fixture: no credentials\n", encoding="utf-8")
            save_credentials_file(private, root)
            save_provider_preferences("gemini", "fixture-not-a-live-model", root)
            expected_settings = {path: path.read_bytes() for path in settings}
            apply_transaction(root, source)
            assert verify(root) == pristine
            assert (root / "RELEASE-MANIFEST.json").read_bytes() == manifest
            assert selected_credentials_file(root) == private
            assert provider_preferences(root) == {
                "service": "gemini",
                "model": "fixture-not-a-live-model",
            }
            assert all(path.read_bytes() == value for path, value in expected_settings.items())
            assert all(
                (root / ".venv" / name).read_bytes() == value for name, value in markers.items()
            )
            journal = json.loads(
                (root / ".aass/update-transaction.json").read_text(encoding="utf-8")
            )
            assert journal["phase"] == "committed"
            status = json.loads((root / ".aass/update-status.json").read_text(encoding="utf-8"))
            assert status["status"] == "updated"
            assert private.read_text(encoding="utf-8") == "# Verification fixture: no credentials\n"
    finally:
        for path, value in originals.items():
            if value is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(value)
    assert verify(source) == pristine
    print(
        "Packaged same-revision update passed real runtime checks and preserved private selections."
    )
    print(
        "GitHub download, GUI restart and live model generation were not exercised by this check."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
