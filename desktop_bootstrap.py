"""Install the latest verified AASS release in a permanent per-user folder."""

import argparse
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path

from app_lifecycle import LifecycleError, _version, install_source, managed_root, start_app
from update_manager import UpdateError, discover_release, download_release
from verify_release import verify


def bootstrap(source, target, *, offline=False, launch=True, callback=print):
    source, target = Path(source).resolve(), Path(target).absolute()
    local = None
    if (source / "RELEASE-MANIFEST.json").exists():
        local = verify(source)
    selected = source
    work = None
    try:
        if not offline:
            callback("Checking the latest verified AASS release on GitHub...")
            try:
                release = discover_release()
                minimum = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))[
                    "project"
                ]["version"]
                if _version(release.version) < _version(minimum):
                    raise LifecycleError(
                        "release_pending",
                        "The new GitHub source is still awaiting its verified release. Wait for the release workflow to finish, then rerun Install-AASS.bat.",
                    )
                if not local or not local.get("source_revision", "").startswith(
                    release.source_prefix
                ):
                    work = Path(tempfile.mkdtemp(prefix="aass-desktop-install-"))
                    verified = download_release(work, callback, release=release)
                    selected = verified.root
            except UpdateError as error:
                if local is None:
                    raise LifecycleError(error.code, str(error)) from None
                callback(
                    "The latest-release check is unavailable. Installing the verified ZIP you downloaded; use Update later."
                )
        elif local is None:
            raise LifecycleError(
                "offline_source",
                "A GitHub Code ZIP needs an online verified-release download. Connect and rerun the installer.",
            )
        callback("Installing AASS in " + str(target))
        installed = install_source(selected, target, callback)
        # When Code ZIP/release was refreshed, retain original file selection.
        state = installed / ".aass"
        from settings import save_credentials_file, selected_credentials_file

        try:
            selected_file = selected_credentials_file(source)
        except (ValueError, OSError):
            selected_file = None
        if selected_file is None:
            selected_file = next(
                (source / name for name in (".env", ".env.txt") if (source / name).is_file()), None
            )
        if selected_file is not None and not (state / "credentials.json").exists():
            try:
                save_credentials_file(selected_file, installed)
            except (ValueError, OSError):
                callback(
                    "Your previous credential-file selection needs attention; choose it again in the setup window."
                )
        callback(
            "AASS is in its permanent folder. Local setup will finish and create your desktop icon."
        )
        if launch:
            start_app(installed, install=True)
        return installed
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--root", type=Path)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use a local manifest-verified release without checking GitHub",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Install verified source only, without opening the GUI",
    )
    args = parser.parse_args(argv)
    try:
        root = bootstrap(
            args.source,
            args.root or managed_root(),
            offline=args.offline,
            launch=not args.no_launch,
        )
        print("AASS application folder: " + str(root), flush=True)
        return 0
    except (LifecycleError, UpdateError, OSError, ValueError) as error:
        print(
            "AASS setup needs attention: "
            + (
                str(error)
                if isinstance(error, (LifecycleError, UpdateError))
                else type(error).__name__
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
