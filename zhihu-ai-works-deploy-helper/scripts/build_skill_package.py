#!/usr/bin/env python3
"""Build a deterministic Skill ZIP and its four-field update manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from skill_config import default_skill_manifest


FIXED_TIME = (1980, 1, 1, 0, 0, 0)
ROOT_FILES = ("SKILL.md", "manifest.json", "README.md")
RESOURCE_DIRS = ("agents", "references", "scripts")
SKIP_NAMES = {"__pycache__", ".DS_Store"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--url", required=True)
    return parser.parse_args()


def validate_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an absolute HTTP or HTTPS URL")
    return value


def collect_files(root: Path) -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []
    for name in ROOT_FILES:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"required package file is missing or unsafe: {name}")
        files.append((Path(name), path))
    for directory_name in RESOURCE_DIRS:
        directory = root / directory_name
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(f"required package directory is missing or unsafe: {directory_name}")
        for current_root, directories, names in os.walk(directory, topdown=True, followlinks=False):
            current = Path(current_root)
            kept: list[str] = []
            for name in sorted(directories):
                path = current / name
                if name in SKIP_NAMES:
                    continue
                if path.is_symlink():
                    raise ValueError(f"symlink is forbidden in Skill package: {path.relative_to(root)}")
                kept.append(name)
            directories[:] = kept
            for name in sorted(names):
                path = current / name
                relative = path.relative_to(root)
                if name in SKIP_NAMES or path.suffix == ".pyc":
                    continue
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f"non-regular file is forbidden in Skill package: {relative}")
                files.append((relative, path))
    return sorted(files, key=lambda item: item[0].as_posix())


def write_zip(output: Path, package_root: str, files: list[tuple[Path, Path]]) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for relative, source in files:
                info = zipfile.ZipInfo((Path(package_root) / relative).as_posix(), FIXED_TIME)
                info.create_system = 3
                mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        with zipfile.ZipFile(temporary) as archive:
            corrupt = archive.testzip()
            if corrupt is not None:
                raise ValueError(f"Skill package CRC validation failed: {corrupt}")
        os.chmod(temporary, 0o666)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: object) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o666)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    args = parse_args()
    try:
        url = validate_url(args.url)
        manifest = default_skill_manifest()
        root = Path(__file__).resolve().parent.parent
        output_dir = args.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{manifest.name}_v{manifest.version}.zip"
        files = collect_files(root)
        write_zip(output, manifest.name, files)
        update_manifest = {
            "latest_version": manifest.version,
            "url": url,
            "sha256": file_sha256(output),
            "size": output.stat().st_size,
        }
        update_manifest_path = output_dir / "deploy-manifest.json"
        write_json_atomic(update_manifest_path, update_manifest)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise SystemExit(f"error: {error}") from error
    print(json.dumps({
        "archive": str(output),
        "manifest": str(update_manifest_path),
        **update_manifest,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
