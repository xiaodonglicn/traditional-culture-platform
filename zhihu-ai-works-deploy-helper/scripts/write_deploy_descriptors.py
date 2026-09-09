#!/usr/bin/env python3
"""Write CloudBase 1.1 frontend/backend source-build descriptors from a deploy plan."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from cloudbase_runtime import cloudbaserc_descriptor
from delivery_paths import delivery_directory_name
from skill_config import DEPLOY_SCHEMA_VERSION


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--frontend-install-cmd", default="npm ci")
    return parser.parse_args()


def load_plan(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"error: cannot read deploy plan {path}: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit("error: deploy plan must be a JSON object")
    if value.get("Status") == "blocked":
        raise SystemExit("error: blocked deploy plan cannot produce descriptors")
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def safe_path(value: Any, label: str, allow_dot: bool = False) -> str:
    if value == "." and allow_dot:
        return value
    if not isinstance(value, str) or not value or "\\" in value or any(char in value for char in "\r\n\x00"):
        raise SystemExit(f"error: {label} must be a non-empty POSIX relative path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise SystemExit(f"error: {label} must be a normalized, non-traversing relative path")
    return pure.as_posix()


def frontend_descriptor(component: dict[str, Any], output_root: Path, install_cmd: str) -> dict[str, Any]:
    framework = component.get("Framework")
    node_version = component.get("NodeVersion")
    output = safe_path(component.get("OutputPath"), "frontend OutputPath", allow_dot=True)
    static_files = component.get("DeliveryMode") == "static-files"
    build = component.get("BuildCommand")
    if not isinstance(framework, str) or not isinstance(node_version, str):
        raise SystemExit("error: frontend Framework and NodeVersion must be resolved")
    if static_files and framework != "other":
        raise SystemExit("error: static-files frontend Framework must be other")
    if not static_files and framework == "other":
        raise SystemExit("error: Framework other is reserved for static-files delivery")
    if not static_files and not isinstance(build, str):
        raise SystemExit("error: framework frontend BuildCommand must be resolved")
    if not static_files and (not install_cmd.strip() or "&" in install_cmd or any(char in install_cmd for char in "\r\n\x00")):
        raise SystemExit("error: frontend install command must be one non-empty command without '&' or control characters")
    install_value = install_cmd
    directory = component.get("Directory")
    if (
        not static_files
        and install_cmd == "npm ci"
        and isinstance(directory, str)
        and directory != "."
        and isinstance(build, str)
        and f"--prefix {directory}" in build
    ):
        install_value = f"npm ci --prefix {shlex.quote(safe_path(directory, 'frontend Directory'))}"
    return {
        "SchemaVersion": DEPLOY_SCHEMA_VERSION,
        "Env": [],
        "Framework": framework,
        "NodeVersion": node_version,
        "BuildCmd": "" if static_files else build,
        "InstallCmd": "" if static_files else install_value,
        "DeployCmd": f"tcb hosting deploy {'.' if output == '.' else './' + output} /",
        "BuildPath": f"./{delivery_directory_name(output_root.name)}",
    }


def build_step(component: dict[str, Any]) -> str:
    commands: list[str] = []
    recipe = component.get("BuildRecipe")
    if not isinstance(recipe, list):
        raise SystemExit("error: backend BuildRecipe must be an array")
    for item in recipe:
        command = item.get("Execute") if isinstance(item, dict) else None
        if not isinstance(command, str) or not command.strip() or any(char in command for char in "\r\n\x00"):
            raise SystemExit("error: backend BuildRecipe contains an invalid Execute command")
        commands.append(command)
    directory = component.get("Directory")
    recipe_directories = {item.get("Directory") for item in recipe if isinstance(item, dict)}
    if commands and isinstance(directory, str) and directory != "." and directory not in recipe_directories:
        commands.insert(0, f"npm ci --prefix {shlex.quote(safe_path(directory, 'backend Directory'))}")
    if not commands:
        return f"test -f {shlex.quote(safe_path(component.get('RuntimeEntry'), 'RuntimeEntry'))}"
    artifacts = component.get("BuildArtifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise SystemExit("error: backend build requires at least one BuildArtifact")
    checks = []
    for artifact in artifacts:
        path = artifact.get("Path") if isinstance(artifact, dict) else None
        checks.append(f"test -e {shlex.quote(safe_path(path, 'BuildArtifact Path'))}")
    return " && ".join([*commands, *checks])


def custom_step(name: str, command: str) -> dict[str, str]:
    if not name.strip() or any(char in name for char in "\r\n\x00"):
        raise SystemExit("error: CustomStep Name must be a non-empty single-line string")
    if not command.strip() or any(char in command for char in "\r\n\x00"):
        raise SystemExit("error: CustomStep Command must be a non-empty single-line string")
    return {"Name": name, "Command": command}


def backend_descriptor(plan: dict[str, Any], component: dict[str, Any], output_root: Path) -> dict[str, Any]:
    mode = component.get("RuntimeManifestMode")
    entry = safe_path(component.get("RuntimeEntry"), "RuntimeEntry")
    if mode not in {"root", "overlay"}:
        raise SystemExit("error: RuntimeManifestMode must be root or overlay")
    node_version = component.get("NodeVersion")
    if not isinstance(node_version, str) or not node_version.isdigit():
        raise SystemExit("error: backend NodeVersion must be a detected Node major")
    custom_steps = [
        custom_step("安装构建依赖", "npm ci"),
        custom_step("构建或验证项目", build_step(component)),
    ]
    if mode == "overlay":
        custom_steps.append(custom_step("切换运行时依赖清单", "node _tmp/prepare-backend-package.js"))
    custom_steps.extend([
        custom_step("安装生产依赖", "npm install --omit=dev --ignore-scripts"),
        custom_step("验证运行时交付", " && ".join((
            "npm ls --omit=dev",
            f"test -f {shlex.quote(entry)}",
            "test -x scf_bootstrap",
            "test -f cloudbaserc.json",
            "cat package.json",
            "cat scf_bootstrap",
            "cat cloudbaserc.json",
        ))),
        custom_step("安装 CloudBase CLI", "npm i @cloudbase/cli@3.8.0-beta.3 -g"),
        custom_step("部署云函数", " && ".join((
            'tcb login --apiKeyId "$API_SECRET_ID" --apiKey "$API_SECRET_KEY" --token "$API_TOKEN"',
            'tcb fn deploy ${functionName} --dir . --force -e "$CLOUDBASE_ENV_ID" --httpFn --yes',
        ))),
    ])
    routes = component.get("Routes", [])
    return {
        "SchemaVersion": DEPLOY_SCHEMA_VERSION,
        "Runtime": "node",
        "NodeVersion": node_version,
        "InstallDependencies": True,
        "Routes": sorted(set(routes)) if isinstance(routes, list) else [],
        "Env": [],
        "CustomSteps": custom_steps,
    }


def main() -> int:
    args = parse_args()
    output_root = args.output_root.resolve()
    if not output_root.is_dir():
        raise SystemExit(f"error: output root is not a directory: {output_root}")
    plan = load_plan(args.plan.resolve())
    components = [item for item in plan.get("Components", []) if isinstance(item, dict)]
    frontends = [item for item in components if item.get("Unit") == "frontend"]
    backends = [item for item in components if item.get("Unit") == "backend"]
    if len(frontends) > 1 or len(backends) > 1 or not (frontends or backends):
        raise SystemExit("error: plan must contain at most one component per unit and at least one unit")
    descriptor_dir = output_root / "_tmp"
    if descriptor_dir.is_symlink():
        raise SystemExit("error: refusing to write through symlinked _tmp directory")
    written: list[str] = []
    if frontends:
        path = descriptor_dir / "frontend.deploy.json"
        write_json_atomic(path, frontend_descriptor(frontends[0], output_root, args.frontend_install_cmd))
        written.append(str(path))
    if backends:
        path = descriptor_dir / "backend.deploy.json"
        cloudbaserc_path = output_root / "cloudbaserc.json"
        if cloudbaserc_path.is_symlink():
            raise SystemExit("error: refusing to replace symlinked cloudbaserc.json")
        try:
            cloudbaserc = cloudbaserc_descriptor(backends[0])
        except ValueError as error:
            raise SystemExit(f"error: {error}") from error
        backend = backend_descriptor(plan, backends[0], output_root)
        write_json_atomic(path, backend)
        written.append(str(path))
        write_json_atomic(cloudbaserc_path, cloudbaserc)
        written.append(str(cloudbaserc_path))
    print(json.dumps({"written": written}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
