"""Bounded Git tracked-file and Python import graph mapper."""

import ast
import os
import subprocess
from pathlib import Path

from settings import is_link


class RepoMapper:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)

    def map(self):
        try:
            result = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=self.root,
                capture_output=True,
                check=True,
                timeout=10,
            )
            paths = result.stdout.decode().split("\0")
            version_control = "git"
        except (FileNotFoundError, subprocess.CalledProcessError):
            # A new project or a ZIP download may have no Git installation/metadata.
            paths = []
            version_control = "none"
            for directory, dirs, names in os.walk(self.root, followlinks=False):
                base = Path(directory)
                dirs[:] = [
                    d
                    for d in sorted(dirs)
                    if not d.startswith(".")
                    and d not in {"node_modules", "__pycache__", "generated"}
                    and not is_link(base / d)
                ]
                paths.extend(
                    (base / name).relative_to(self.root).as_posix() for name in sorted(names)
                )
                if len(paths) > 5000:
                    break
        files, imports = [], {}
        for name in paths[:5000]:
            if not name or any(part.startswith(".") for part in Path(name).parts):
                continue
            path = (self.root / name).resolve()
            if (
                not path.is_relative_to(self.root)
                or not path.is_file()
                or is_link(self.root / name)
                or path.stat().st_nlink > 1
            ):
                continue
            if path.suffix in (".pem", ".key", ".env") or "credential" in name.lower():
                continue
            files.append(name)
            if path.suffix == ".py" and path.stat().st_size < 256_000:
                try:
                    tree = ast.parse(path.read_text())
                    imports[name] = sorted(
                        {
                            n.module
                            for n in ast.walk(tree)
                            if isinstance(n, ast.ImportFrom) and n.module
                        }
                        | {
                            a.name
                            for n in ast.walk(tree)
                            if isinstance(n, ast.Import)
                            for a in n.names
                        }
                    )
                except (SyntaxError, UnicodeError):
                    imports[name] = ["<unparseable>"]
        return {
            "files": files,
            "imports": imports,
            "truncated": len(paths) > 5000,
            "version_control": version_control,
        }
