#!/usr/bin/env python3
"""Download, validate, and install one advisory Skill ZIP update."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from skill_config import load_skill_manifest, parse_skill_manifest, version_tuple


MAX_PACKAGE_BYTES = 100 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-dir", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--version", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--size", required=True, type=int)
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args()


def print_report(**values: object) -> None:
    values["blocking"] = False
    print(json.dumps(values, ensure_ascii=False, sort_keys=True))


def validate_inputs(local_version: str, version: str, url: str, sha256: str, size: int) -> None:
    if version_tuple(version, "remote version") <= version_tuple(local_version, "local version"):
        raise ValueError(f"remote version {version} is not newer than local version {local_version}")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an absolute HTTP or HTTPS URL")
    if SHA256_PATTERN.fullmatch(sha256) is None:
        raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
    if size <= 0:
        raise ValueError("size must be a positive integer")
    if size > MAX_PACKAGE_BYTES:
        raise ValueError("size exceeds the 100 MiB package limit")


def download_package(url: str, expected_size: int, expected_sha256: str, output: Path, timeout: float) -> None:
    request = Request(url, headers={"User-Agent": "zhihu-ai-works-deploy-helper/update-install"})
    digest = hashlib.sha256()
    received = 0
    with urlopen(request, timeout=timeout) as response, output.open("wb") as handle:
        content_length = response.headers.get("Content-Length")
        if content_length is not None and int(content_length) != expected_size:
            raise ValueError(
                f"Content-Length mismatch: expected {expected_size}, received {content_length}"
            )
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > expected_size or received > MAX_PACKAGE_BYTES:
                raise ValueError("download exceeds declared package size")
            digest.update(chunk)
            handle.write(chunk)
    if received != expected_size:
        raise ValueError(f"download size mismatch: expected {expected_size}, received {received}")
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(f"SHA-256 mismatch: expected {expected_sha256}, received {actual_sha256}")


def safe_members(archive: zipfile.ZipFile, expected_root: str) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    seen: set[str] = set()
    roots: set[str] = set()
    total_size = 0
    for info in archive.infolist():
        name = info.filename
        if not name or "\\" in name or "\x00" in name or re.match(r"^[A-Za-z]:", name):
            raise ValueError(f"unsafe ZIP member path: {name!r}")
        path = PurePosixPath(name)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError(f"unsafe ZIP member path: {name!r}")
        normalized = path.as_posix().rstrip("/")
        collision_key = normalized.casefold()
        if collision_key in seen:
            raise ValueError(f"duplicate ZIP member: {normalized}")
        seen.add(collision_key)
        roots.add(path.parts[0])
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if file_type == stat.S_IFLNK:
            raise ValueError(f"symlink ZIP member is forbidden: {name}")
        if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise ValueError(f"non-regular ZIP member is forbidden: {name}")
        total_size += info.file_size
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("uncompressed ZIP content exceeds 200 MiB")
        members.append(info)
    if roots != {expected_root}:
        raise ValueError(f"ZIP must contain one top-level directory named {expected_root}")
    return members


def validate_archive(archive: zipfile.ZipFile, expected_name: str, expected_version: str) -> list[zipfile.ZipInfo]:
    members = safe_members(archive, expected_name)
    names = {info.filename.rstrip("/") for info in members}
    manifest_name = f"{expected_name}/manifest.json"
    skill_name = f"{expected_name}/SKILL.md"
    if manifest_name not in names or skill_name not in names:
        raise ValueError("ZIP must contain root manifest.json and SKILL.md")
    try:
        manifest_value = json.loads(archive.read(manifest_name).decode("utf-8"))
    except (KeyError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"package manifest.json is invalid: {error}") from error
    manifest = parse_skill_manifest(manifest_value, "package manifest.json")
    if manifest.name != expected_name:
        raise ValueError(f"package name mismatch: expected {expected_name}, received {manifest.name}")
    if manifest.version != expected_version:
        raise ValueError(
            f"package version mismatch: expected {expected_version}, received {manifest.version}"
        )
    return members


def extract_archive(archive: zipfile.ZipFile, members: list[zipfile.ZipInfo], destination: Path) -> None:
    for info in members:
        path = destination.joinpath(*PurePosixPath(info.filename).parts)
        if info.is_dir():
            path.mkdir(parents=True, exist_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, path.open("wb") as target:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
        mode = info.external_attr >> 16
        os.chmod(path, 0o755 if mode & 0o111 else 0o644)


def main() -> int:
    args = parse_args()
    skill_dir = args.skill_dir.resolve()
    try:
        local = load_skill_manifest(skill_dir / "manifest.json")
        validate_inputs(local.version, args.version, args.url, args.sha256, args.size)
        with tempfile.TemporaryDirectory(prefix="skill-update-install-") as temporary:
            root = Path(temporary)
            package = root / "skill.zip"
            download_package(args.url, args.size, args.sha256, package, args.timeout)
            extract_root = root / "extracted"
            extract_root.mkdir()
            with zipfile.ZipFile(package) as archive:
                members = validate_archive(archive, local.name, args.version)
                extract_archive(archive, members, extract_root)
            result = subprocess.run(
                ["npx", "skills", "add", str(extract_root / local.name), "-g"],
                check=False,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or "npx skills add failed"
                raise ValueError(detail)
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.TimeoutExpired) as error:
        print_report(
            status="update-failed",
            localVersion=getattr(locals().get("local"), "version", None),
            remoteVersion=args.version,
            error=str(error),
        )
        return 0
    report: dict[str, object] = {
        "status": "updated",
        "localVersion": local.version,
        "remoteVersion": args.version,
        "recheckRequired": True,
    }
    if urlparse(args.url).scheme == "http":
        report["warning"] = "ZIP URL uses insecure HTTP transport"
    print_report(**report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
