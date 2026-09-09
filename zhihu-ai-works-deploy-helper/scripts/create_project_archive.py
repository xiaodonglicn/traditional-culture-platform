#!/usr/bin/env python3
"""Create the final upload ZIP for a prepared project."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path, PurePath

from delivery_paths import delivery_directory_name


SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".pytest_cache",
    ".cache", ".next", ".nuxt", ".output", ".svelte-kit", ".vite", ".turbo",
    "dist", "build", "out", "coverage", ".yarn",
    "__MACOSX", ".AppleDouble", ".DocumentRevisions-V100", ".fseventsd",
    ".Spotlight-V100", ".TemporaryItems", ".Trash", ".Trashes",
}
SKIP_FILES = {
    ".DS_Store", ".localized", ".VolumeIcon.icns", "Icon\r",
    "pnpm-lock.yaml", "yarn.lock", ".yarnrc", ".yarnrc.yml", ".pnp.cjs", ".pnp.js", ".pnp.data.json",
    "agent-build-validation.json",
}
SENSITIVE_NAMES = {
    ".npmrc",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials.json",
    "service-account.json",
}
PRIVATE_KEY_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
)
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--plan", type=Path)
    return parser.parse_args()


def archive_path(project_root: Path) -> Path:
    name = delivery_directory_name(project_root.name)
    return project_root / f"{name}.zip"


def contains_private_key(path: Path) -> bool:
    if path.stat().st_size > 2 * 1024 * 1024:
        return False
    data = path.read_bytes()
    return any(marker in data for marker in PRIVATE_KEY_MARKERS)


def archive_contract(project_root: Path, plan_path: Path | None) -> tuple[set[PurePath], set[PurePath]]:
    path = plan_path or (project_root / "_tmp" / "deploy-plan.json")
    if not path.is_file():
        raise ValueError(f"a non-blocked deploy plan is required to create an archive: {path}")
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read archive plan: {error}") from error
    if not isinstance(plan, dict):
        raise ValueError("archive plan must be a JSON object")
    if plan.get("Status") == "blocked":
        raise ValueError("blocked deploy plan cannot produce an archive")
    if plan.get("Status") not in {"ready", "review-required"}:
        raise ValueError("archive plan status must be ready or review-required")
    findings = plan.get("Findings")
    if not isinstance(findings, list):
        raise ValueError("archive plan Findings must be an array")
    if any(
        isinstance(finding, dict)
        and (
            finding.get("Severity") == "error"
            or finding.get("Code") == "E_IFRAME_EMBEDDING_FORBIDDEN"
        )
        for finding in findings
    ):
        raise ValueError("deploy plan with error findings cannot produce an archive")
    excluded: set[PurePath] = set()
    protected: set[PurePath] = set()
    backend_components = [
        component for component in plan.get("Components", [])
        if isinstance(component, dict) and component.get("Unit") == "backend"
    ]
    cloudbaserc = project_root / "cloudbaserc.json"
    if backend_components:
        if not cloudbaserc.is_file() or cloudbaserc.is_symlink():
            raise ValueError("backend project archive requires a regular root cloudbaserc.json")
    elif cloudbaserc.exists() or cloudbaserc.is_symlink():
        raise ValueError("static project archive must not contain cloudbaserc.json")
    for component in plan.get("Components", []):
        if not isinstance(component, dict) or component.get("Unit") != "backend":
            continue
        for artifact in component.get("BuildArtifacts", []):
            value = artifact.get("Path") if isinstance(artifact, dict) else None
            if isinstance(value, str):
                excluded.add(PurePath(value))
        if not component.get("BuildRecipe") and isinstance(component.get("RuntimeEntry"), str):
            protected.add(PurePath(component["RuntimeEntry"]))
    return excluded, protected


def is_same_or_parent(path: PurePath, child: PurePath) -> bool:
    return path == child or path in child.parents


def collect_files(
    project_root: Path,
    output: Path,
    excluded: set[PurePath],
    protected: set[PurePath],
) -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []
    legacy_output = project_root / f"{project_root.name}.zip"
    for root, dirs, names in os.walk(project_root, topdown=True, followlinks=False):
        root_path = Path(root)
        relative_root = root_path.relative_to(project_root)
        kept_dirs: list[str] = []
        for name in sorted(dirs):
            candidate = root_path / name
            relative = relative_root / name
            pure_relative = PurePath(relative.as_posix())
            if any(is_same_or_parent(path, pure_relative) for path in excluded):
                continue
            if any(part in SKIP_DIRS for part in pure_relative.parts[:-1]) and not any(
                is_same_or_parent(pure_relative, path) for path in protected
            ):
                continue
            if name in SKIP_DIRS and not any(is_same_or_parent(pure_relative, path) for path in protected):
                continue
            if candidate.is_symlink():
                raise ValueError(f"symlink directory is forbidden in project archive: {relative.as_posix()}")
            kept_dirs.append(name)
        dirs[:] = kept_dirs

        for name in sorted(names):
            candidate = root_path / name
            relative = relative_root / name
            pure_relative = PurePath(relative.as_posix())
            if any(is_same_or_parent(path, pure_relative) for path in excluded):
                continue
            if any(part in SKIP_DIRS for part in pure_relative.parts[:-1]) and pure_relative not in protected:
                continue
            if candidate in {output, legacy_output} or name in SKIP_FILES or name.startswith("._") or candidate.suffix in {".pyc", ".tsbuildinfo"} or name.startswith(("npm-debug.log", "yarn-error.log", "pnpm-debug.log")):
                continue
            if candidate.is_symlink():
                raise ValueError(f"symlink file is forbidden in project archive: {relative.as_posix()}")
            mode = candidate.stat().st_mode
            if not stat.S_ISREG(mode):
                raise ValueError(f"non-regular file is forbidden in project archive: {relative.as_posix()}")
            lowered = name.lower()
            if lowered == ".env" or lowered.startswith(".env.") or lowered in SENSITIVE_NAMES:
                raise ValueError(f"sensitive file must not enter project archive: {relative.as_posix()}")
            if contains_private_key(candidate):
                raise ValueError(f"private key content must not enter project archive: {relative.as_posix()}")
            files.append((relative, candidate))
    if not files:
        raise ValueError("project archive would contain no files")
    return sorted(files, key=lambda item: item[0].as_posix())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_archive(
    files: list[tuple[Path, Path]],
    output: Path,
    project_directory_name: str,
    excluded: set[PurePath],
    protected: set[PurePath],
) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for relative, source in files:
                archive_name = (Path(project_directory_name) / relative).as_posix()
                info = zipfile.ZipInfo(archive_name, FIXED_TIME)
                info.create_system = 3
                mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        with zipfile.ZipFile(temporary) as archive:
            corrupt = archive.testzip()
            if corrupt is not None:
                raise ValueError(f"project archive CRC validation failed: {corrupt}")
            for name in archive.namelist():
                relative = PurePath(name).relative_to(project_directory_name)
                if any(part in SKIP_DIRS for part in relative.parts) and relative not in protected:
                    raise ValueError(f"project archive contains a forbidden generated directory: {relative.as_posix()}")
                if relative.name in SKIP_FILES or any(is_same_or_parent(path, relative) for path in excluded):
                    raise ValueError(f"project archive contains a forbidden generated file: {relative.as_posix()}")
        os.chmod(temporary, 0o666)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        raise SystemExit(f"error: project root is not a directory: {project_root}")
    output = archive_path(project_root)
    if output.exists() or output.is_symlink():
        if output.is_dir() and not output.is_symlink():
            raise SystemExit(f"error: archive path is an existing directory: {output}")
        output.unlink()
    try:
        excluded, protected = archive_contract(project_root, args.plan.resolve() if args.plan else None)
        files = collect_files(project_root, output, excluded, protected)
        write_archive(files, output, delivery_directory_name(project_root.name), excluded, protected)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise SystemExit(f"error: {error}") from error
    print(json.dumps({
        "archive": str(output),
        "sha256": sha256(output),
        "fileCount": len(files),
        "mode": "0666",
        "upload": f"Upload {output.name} directly",
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
