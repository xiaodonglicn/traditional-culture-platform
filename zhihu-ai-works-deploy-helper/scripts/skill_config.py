#!/usr/bin/env python3
"""Load and validate deterministic settings from the Skill manifest."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SKILL_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = SKILL_ROOT / "manifest.json"
VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DEPLOY_SCHEMA_VERSION = "1.1.0"
MANAGED_RUNTIME_ENVIRONMENT = (
    ("PORT", "9000"),
    ("HOST", "0.0.0.0"),
    ("HOSTNAME", "0.0.0.0"),
    ("NITRO_HOST", "0.0.0.0"),
    ("NITRO_PORT", "9000"),
)


@dataclass(frozen=True)
class SkillManifest:
    manifest_version: int
    name: str
    version: str
    update_manifest_url: str


def version_tuple(value: str, label: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"{label} must use MAJOR.MINOR.PATCH, got {value!r}")
    return tuple(int(part) for part in match.groups())


def absolute_http_url(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} must be an absolute HTTP or HTTPS URL")
    return value


def parse_skill_manifest(value: Any, source: str) -> SkillManifest:
    if not isinstance(value, dict):
        raise ValueError(f"{source}: top level must be an object")
    required = ("manifest_version", "name", "version", "update_manifest_url")
    missing = [key for key in required if key not in value]
    if missing:
        raise ValueError(f"{source}: missing required field(s): {', '.join(missing)}")
    manifest_version = value["manifest_version"]
    if not isinstance(manifest_version, int) or isinstance(manifest_version, bool) or manifest_version != 1:
        raise ValueError(f"{source}: manifest_version must be integer 1")
    name = value["name"]
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{source}: name must be a non-empty string")
    version = value["version"]
    if not isinstance(version, str):
        raise ValueError(f"{source}: version must be a string")
    version_tuple(version, f"{source}: version")
    return SkillManifest(
        manifest_version=manifest_version,
        name=name,
        version=version,
        update_manifest_url=absolute_http_url(
            value["update_manifest_url"], f"{source}: update_manifest_url"
        ),
    )


def load_skill_manifest(path: Path = MANIFEST_PATH) -> SkillManifest:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read Skill manifest {path}: {error}") from error
    return parse_skill_manifest(value, str(path))


def default_skill_manifest() -> SkillManifest:
    try:
        return load_skill_manifest()
    except ValueError as error:
        raise SystemExit(f"error: {error}") from error
