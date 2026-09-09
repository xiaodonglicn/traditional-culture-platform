#!/usr/bin/env python3
"""Materialize Agent-precomputed runtime inputs for CloudBase source builds."""

from __future__ import annotations

import argparse
import json
import glob
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from write_scf_bootstrap import safe_relative, write_bootstrap


RUNTIME_SECTIONS = ("dependencies", "optionalDependencies")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    return parser.parse_args()


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(value)
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def normalized_name(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-_")
    if not result or not result[0].isalpha():
        result = f"fn-{result}".strip("-_")
    result = result[:64].rstrip("-_")
    if not result or not result[0].isalpha():
        raise ValueError("project directory cannot form a valid CloudBase function name")
    return result


def package_name(value: Any, fallback: str) -> str:
    if isinstance(value, str) and len(value) <= 214 and re.fullmatch(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*", value):
        return value
    return fallback


def package_version(value: Any) -> str:
    if isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", value):
        return value
    return "1.0.0"


def safe_manifest_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str):
        raise ValueError("RuntimePackagePath is unresolved")
    pure = PurePosixPath(value.replace("\\", "/"))
    if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
        raise ValueError("RuntimePackagePath must be project-root-relative")
    path = root.joinpath(*pure.parts).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError("RuntimePackagePath escapes project root") from error
    return path


def discover_workspace_manifests(root: Path) -> dict[str, tuple[str, dict[str, Any]]]:
    result: dict[str, tuple[str, dict[str, Any]]] = {}
    root_manifest = load_object(root / "package.json")
    patterns = root_manifest.get("workspaces", [])
    if isinstance(patterns, dict):
        patterns = patterns.get("packages", [])
    if not isinstance(patterns, list):
        return result
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern or PurePosixPath(pattern).is_absolute() or ".." in PurePosixPath(pattern).parts:
            continue
        for match in glob.glob(str(root / pattern)):
            directory_path = Path(match).resolve()
            try:
                directory_path.relative_to(root)
            except ValueError:
                continue
            path = directory_path / "package.json"
            if not path.is_file():
                continue
            manifest = load_object(path)
            name = manifest.get("name")
            if isinstance(name, str) and name:
                directory = directory_path.relative_to(root).as_posix()
                result[name] = (directory, manifest)
    return result


def runtime_manifest(root: Path, component: dict[str, Any]) -> dict[str, Any]:
    source_path = safe_manifest_path(root, component.get("RuntimePackagePath"))
    source = load_object(source_path)
    workspaces = discover_workspace_manifests(root)
    dependencies: dict[str, str] = {}
    queue = [source]
    visited: set[str] = set()
    source_manifest = source
    while queue:
        manifest = queue.pop(0)
        manifest_name = manifest.get("name")
        if isinstance(manifest_name, str):
            if manifest_name in visited:
                continue
            visited.add(manifest_name)
        for section in RUNTIME_SECTIONS:
            values = manifest.get(section, {})
            if not isinstance(values, dict):
                continue
            for name, version in values.items():
                if name in workspaces:
                    directory, workspace_manifest = workspaces[name]
                    if manifest is not source_manifest and str(version).startswith("workspace:"):
                        raise ValueError(
                            f"transitive workspace protocol dependency {name!r} in {manifest_name!r} "
                            "cannot be normalized by a root-only overlay"
                        )
                    if directory != ".":
                        dependencies[str(name)] = f"file:./{directory}"
                    queue.append(workspace_manifest)
                else:
                    dependencies[str(name)] = str(version)
    entry_value = component.get("RuntimeEntry")
    if not isinstance(entry_value, str):
        raise ValueError("RuntimeEntry is unresolved")
    entry = safe_relative(entry_value).as_posix()
    output: dict[str, Any] = {
        "name": package_name(source.get("name"), normalized_name(root.name).lower()),
        "version": package_version(source.get("version")),
        "private": source.get("private") if isinstance(source.get("private"), bool) else True,
        "main": entry,
        "scripts": {"start": f"node {entry}"},
        "dependencies": dict(sorted(dependencies.items())),
    }
    if source.get("type") in {"module", "commonjs"}:
        output["type"] = source["type"]
    return output


def bootstrap_start_script(component: dict[str, Any]) -> str | None:
    launch = component.get("RuntimeLaunch")
    if not isinstance(launch, dict):
        raise ValueError("RuntimeLaunch is unresolved")
    kind = launch.get("Kind")
    if kind == "node-entry":
        if launch.get("Entry") != component.get("RuntimeEntry"):
            raise ValueError("RuntimeLaunch entry does not match RuntimeEntry")
        return None
    if kind == "npm-script":
        script = launch.get("Script")
        if not isinstance(script, str) or not script.strip():
            raise ValueError("RuntimeLaunch npm script is unresolved")
        return script
    raise ValueError("RuntimeLaunch Kind must be node-entry or npm-script")


def helper_source(entry: str) -> str:
    return f'''#!/usr/bin/env node
Promise.all([import("node:fs"), import("node:path")]).then(([fsModule, pathModule]) => {{
  const fs = fsModule.default || fsModule;
  const path = pathModule.default || pathModule;
  const root = process.cwd();
  const source = path.join(root, "_tmp", "backend.runtime.package.json");
  const target = path.join(root, "package.json");
  const entry = {json.dumps(entry)};
  if (!fs.existsSync(source)) throw new Error("missing precomputed backend.runtime.package.json");
  const manifest = JSON.parse(fs.readFileSync(source, "utf8"));
  if (manifest.main !== entry || manifest.scripts?.start !== `node ${{entry}}`) throw new Error("runtime manifest entry mismatch");
  if (!fs.existsSync(path.join(root, entry))) throw new Error(`missing runtime entry: ${{entry}}`);
  const temporary = path.join(root, `.package.json.${{process.pid}}.tmp`);
  fs.copyFileSync(source, temporary);
  fs.renameSync(temporary, target);
}}).catch((error) => {{ console.error(error); process.exitCode = 1; }});
'''


def main() -> int:
    args = parse_args()
    root = args.project_root.resolve()
    plan = load_object(args.plan.resolve())
    if plan.get("Status") == "blocked":
        raise SystemExit("error: blocked deploy plan cannot produce backend runtime inputs")
    backends = [item for item in plan.get("Components", []) if isinstance(item, dict) and item.get("Unit") == "backend"]
    if len(backends) != 1:
        raise SystemExit(f"error: expected exactly one backend component, found {len(backends)}")
    component = backends[0]
    mode = component.get("RuntimeManifestMode")
    if mode not in {"root", "overlay"}:
        raise SystemExit("error: backend RuntimeManifestMode must be root or overlay")
    try:
        entry_value = component.get("RuntimeEntry")
        if not isinstance(entry_value, str):
            raise ValueError("RuntimeEntry is unresolved")
        entry = safe_relative(entry_value).as_posix()
        node_version = component.get("NodeVersion")
        if not isinstance(node_version, str) or not node_version.isdigit():
            raise ValueError("backend NodeVersion must be a detected Node major")
        overlay_manifest = runtime_manifest(root, component) if mode == "overlay" else None
        written = [str(write_bootstrap(
            root,
            PurePosixPath(entry),
            start_script=bootstrap_start_script(component),
        ))]
        if mode == "overlay":
            descriptor_dir = root / "_tmp"
            if descriptor_dir.is_symlink():
                raise ValueError("refusing to write through symlinked _tmp directory")
            descriptor_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = descriptor_dir / "backend.runtime.package.json"
            helper_path = descriptor_dir / "prepare-backend-package.js"
            assert overlay_manifest is not None
            atomic_json(manifest_path, overlay_manifest)
            atomic_text(helper_path, helper_source(entry))
            written.extend((str(manifest_path), str(helper_path)))
    except (OSError, ValueError, argparse.ArgumentTypeError) as error:
        raise SystemExit(f"error: {error}") from error
    print(json.dumps({"written": written}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
