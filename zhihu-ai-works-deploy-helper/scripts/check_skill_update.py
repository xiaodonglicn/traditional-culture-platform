#!/usr/bin/env python3
"""Advisory check for a newer ZIP-distributed Skill version."""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from skill_config import load_skill_manifest, version_tuple


MAX_MANIFEST_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = 100 * 1024 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-dir", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def print_report(**values: object) -> None:
    values["blocking"] = False
    print(json.dumps(values, ensure_ascii=False, sort_keys=True))


def fetch_json(url: str, timeout: float) -> Any:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "zhihu-ai-works-deploy-helper/update-check"},
    )
    with urlopen(request, timeout=timeout) as response:
        length = response.headers.get("Content-Length")
        if length is not None and int(length) > MAX_MANIFEST_BYTES:
            raise ValueError("remote update manifest exceeds 1 MiB")
        payload = response.read(MAX_MANIFEST_BYTES + 1)
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("remote update manifest exceeds 1 MiB")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"remote update manifest is invalid JSON: {error}") from error


def package_metadata(value: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    url = value.get("url")
    parsed = urlparse(url) if isinstance(url, str) else None
    if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        errors.append("url must be an absolute HTTP or HTTPS URL")
    sha256 = value.get("sha256")
    if not isinstance(sha256, str) or SHA256_PATTERN.fullmatch(sha256) is None:
        errors.append("sha256 must be 64 lowercase hexadecimal characters")
    size = value.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        errors.append("size must be a positive integer")
    elif size > MAX_PACKAGE_BYTES:
        errors.append("size exceeds the 100 MiB package limit")
    if parsed is not None and parsed.scheme == "http":
        warnings.append("ZIP URL uses insecure HTTP transport")
    return {"url": url, "sha256": sha256, "size": size}, errors, warnings


def main() -> int:
    args = parse_args()
    skill_dir = args.skill_dir.resolve()
    try:
        local = load_skill_manifest(skill_dir / "manifest.json")
        local_key = version_tuple(local.version, "local version")
    except ValueError as error:
        print_report(status="check-failed", error=str(error))
        return 0

    base = {
        "localVersion": local.version,
        "updateManifestUrl": local.update_manifest_url,
    }
    transport_warnings: list[str] = []
    if urlparse(local.update_manifest_url).scheme == "http":
        transport_warnings.append("update manifest uses insecure HTTP transport")
    try:
        remote = fetch_json(local.update_manifest_url, args.timeout)
    except (HTTPError, URLError, OSError, ValueError, socket.timeout) as error:
        print_report(status="check-failed", error=str(error), **base)
        return 0
    if not isinstance(remote, dict):
        print_report(status="remote-unversioned", warning="remote update manifest must be an object", **base)
        return 0
    remote_version = remote.get("latest_version")
    if not isinstance(remote_version, str):
        print_report(
            status="remote-unversioned",
            warning="remote update manifest is missing string latest_version",
            **base,
        )
        return 0
    try:
        remote_key = version_tuple(remote_version, "remote latest_version")
    except ValueError as error:
        print_report(status="remote-unversioned", warning=str(error), **base)
        return 0

    if remote_key > local_key:
        status = "update-available"
    elif remote_key == local_key:
        status = "current"
    else:
        status = "local-ahead"
    report: dict[str, Any] = {
        **base,
        "status": status,
        "remoteVersion": remote_version,
    }
    metadata, metadata_errors, metadata_warnings = package_metadata(remote)
    report.update(metadata)
    transport_warnings.extend(metadata_errors)
    transport_warnings.extend(metadata_warnings)
    if status == "update-available":
        report["installable"] = not metadata_errors
    if transport_warnings:
        report["warning"] = "; ".join(transport_warnings)
    print_report(**report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
