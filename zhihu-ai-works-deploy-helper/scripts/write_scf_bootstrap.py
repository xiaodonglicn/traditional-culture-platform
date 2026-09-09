#!/usr/bin/env python3
"""Generate a CloudBase bootstrap for an npm start script or Node entry."""

from __future__ import annotations

import argparse
import os
import re
import shlex
from pathlib import Path, PurePosixPath

from skill_config import MANAGED_RUNTIME_ENVIRONMENT


def safe_relative(value: str) -> PurePosixPath:
    if "\\" in value or any(character in value for character in "\r\n\x00"):
        raise argparse.ArgumentTypeError("entry must use POSIX separators and contain no control characters")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise argparse.ArgumentTypeError("entry must be a normalized, non-traversing project-root-relative path")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--entry", required=True, type=safe_relative)
    parser.add_argument("--start-script")
    parser.add_argument("--node-version", help=argparse.SUPPRESS)
    return parser.parse_args()


def bootstrap_content(entry: PurePosixPath, start_script: str | None = None) -> str:
    if start_script is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", start_script):
        raise ValueError("start script must be a safe npm script name")
    command = (
        f"npm run {shlex.quote(start_script)}"
        if start_script is not None
        else f"node {shlex.quote(entry.as_posix())}"
    )
    environment = "".join(
        f"export {name}={shlex.quote(value)}\n"
        for name, value in MANAGED_RUNTIME_ENVIRONMENT
    )
    return (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        f"{environment}"
        f"exec {command}\n"
    )


def write_bootstrap(project_root: Path, entry: PurePosixPath, *, start_script: str | None = None) -> Path:
    project_root = project_root.resolve()
    if not project_root.is_dir():
        raise ValueError(f"project root is not a directory: {project_root}")
    bootstrap = project_root / "scf_bootstrap"
    if bootstrap.exists() and bootstrap.is_symlink():
        raise ValueError("refusing to replace symlinked scf_bootstrap")
    content = bootstrap_content(entry, start_script)
    with bootstrap.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    os.chmod(bootstrap, 0o755)
    return bootstrap


def main() -> int:
    args = parse_args()
    try:
        print(write_bootstrap(args.project_root, args.entry, start_script=args.start_script))
    except ValueError as error:
        raise SystemExit(f"error: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
