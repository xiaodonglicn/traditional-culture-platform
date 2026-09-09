#!/usr/bin/env python3
"""Perform a conservative, read-only inventory and emit a draft TCB deploy plan."""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from cloudbase_runtime import CLOUD_FUNCTION_RUNTIMES, cloud_function_runtime

from skill_config import MANAGED_RUNTIME_ENVIRONMENT


SKIP_DIRS = {".git", ".hg", ".svn", "_tmp", "node_modules", "dist", "build", "coverage", ".next", ".nuxt", ".output", ".cache"}
SOURCE_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
MANAGED_RUNTIME_ENV_NAMES = frozenset(name for name, _ in MANAGED_RUNTIME_ENVIRONMENT)
PROCESS_ENV_ACCESS_PATTERN = re.compile(
    r"\bprocess\s*\.\s*env\s*(?:\.\s*(?P<dot>[A-Za-z_$][\w$]*)|\[\s*['\"](?P<bracket>[^'\"]+)['\"]\s*\])"
)
PROCESS_ENV_DESTRUCTURE_PATTERN = re.compile(
    r"\{(?P<body>[^{}]+)\}\s*=\s*process\s*\.\s*env\b"
)
PROCESS_ENV_REFERENCE_PATTERN = re.compile(r"\bprocess\s*\.\s*env\b")
SENSITIVE_NAMES = {".npmrc", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials.json", "service-account.json"}
STATIC_FILE_SUFFIXES = {
    ".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
}
STATIC_FILE_NAMES = {"robots.txt", "humans.txt", "sitemap.xml", "manifest.json", "site.webmanifest", "browserconfig.xml", "_headers"}
IFRAME_HEADER_CONFIG_NAMES = {
    "_headers",
    "firebase.json",
    "netlify.toml",
    "nginx.conf",
    "staticwebapp.config.json",
    "vercel.json",
}
IFRAME_SCAN_SKIP_DIRS = SKIP_DIRS | {"__tests__", "docs", "examples", "fixtures", "test", "tests"}
IFRAME_RESTRICTION_PATTERNS = (
    (
        "Content-Security-Policy frame-ancestors 'none'",
        re.compile(
            r"\bframe-ancestors\s+(?:\\?[\"']none\\?[\"']|\bnone\b)\s*(?=;|$|\\?[\"'`},\]])",
            re.I | re.M,
        ),
    ),
    (
        "Content-Security-Policy frame-ancestors 'self' only",
        re.compile(
            r"\bframe-ancestors\s+(?:\\?[\"']self\\?[\"']|\bself\b)\s*(?=;|$|\\?[\"'`},\]])",
            re.I | re.M,
        ),
    ),
    (
        "Helmet frameAncestors 'none'",
        re.compile(r"\bframeAncestors\b\s*[:=]\s*\[[^,\]\r\n]{0,120}\bnone\b[^,\]\r\n]{0,120}\]", re.I),
    ),
    (
        "Helmet frameAncestors 'self' only",
        re.compile(r"\bframeAncestors\b\s*[:=]\s*\[[^,\]\r\n]{0,120}\bself\b[^,\]\r\n]{0,120}\]", re.I),
    ),
    (
        "X-Frame-Options forbids cross-origin embedding",
        re.compile(r"\b(?:x-frame-options|xFrameOptions|frameguard)\b[\s\S]{0,160}?\b(?:deny|sameorigin)\b", re.I),
    ),
    (
        "JavaScript frame-busting redirect",
        re.compile(
            r"\bif\s*\([^)]*(?:(?:window\.)?(?:top|parent)\s*!={1,2}\s*(?:window\.)?self|(?:window\.)?self\s*!={1,2}\s*(?:window\.)?(?:top|parent))[^)]*\)"
            r"\s*\{?[\s\S]{0,240}?\b(?:window\.)?(?:top|parent)\.location(?:\.(?:href|replace|assign))?\s*(?:=|\()",
            re.I,
        ),
    ),
)
DATABASE_DEPENDENCIES = {
    "@aws-sdk/client-dynamodb",
    "@aws-sdk/lib-dynamodb",
    "@libsql/client",
    "@mikro-orm/core",
    "@neondatabase/serverless",
    "@planetscale/database",
    "@prisma/client",
    "@supabase/supabase-js",
    "better-sqlite3",
    "cassandra-driver",
    "drizzle-orm",
    "ioredis",
    "knex",
    "kysely",
    "level",
    "lowdb",
    "mongodb",
    "mongoose",
    "mssql",
    "mysql",
    "mysql2",
    "objection",
    "oracledb",
    "pg",
    "pg-promise",
    "postgres",
    "redis",
    "sequelize",
    "sqlite3",
    "tedious",
    "typeorm",
}
DATABASE_DEPENDENCY_PREFIXES = ("@mikro-orm/", "@prisma/", "drizzle-")
DATABASE_SOURCE_PATTERNS = (
    (r"\b(?:DATABASE|DB|POSTGRES(?:QL)?|MYSQL|MONGODB|MONGO|REDIS|SQLITE)_URL\b", "database connection environment variable"),
    (r"\b(?:MONGODB_URI|DATABASE_URI|DB_CONNECTION_STRING)\b", "database connection environment variable"),
    (r"\b(?:DB|PG|POSTGRES|POSTGRESQL|MYSQL|MONGO|MONGODB|REDIS)_(?:HOST|PORT|USER|USERNAME|PASSWORD|DATABASE|DB|NAME)\b", "database connection environment variable"),
    (r"\bPG(?:HOST|PORT|USER|PASSWORD|DATABASE)\b", "PostgreSQL connection environment variable"),
    (r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis(?:s)?|libsql|sqlite)://", "database connection URL"),
    (r"\bnew\s+PrismaClient\s*\(", "Prisma client"),
    (r"\bmongoose\.connect\s*\(", "Mongoose connection"),
    (r"\bnew\s+MongoClient\s*\(", "MongoDB client"),
    (r"\b(?:createClient|createPool)\s*\([^)]*(?:url|host|connectionString)", "database client connection"),
    (r"\b(?:cloudbase|tcb|wx\.cloud)\.database\s*\(", "CloudBase database API"),
    (r"\b(?:getFirestore|initializeFirestore|admin\.firestore)\s*\(", "Firestore API"),
)
SERVER_FRONTEND_PATTERNS = (
    r"\bexpress\.static\s*\(",
    r"\bsendFile\s*\(",
    r"\bssrLoadModule\s*\(",
    r"\bvite\.middlewares\b",
)
RELATIVE_MODULE_PATTERNS = (
    r"\b(?:import|export)\s+(?:[^'\"\n;]+?\s+from\s+)?['\"](\.{1,2}/[^'\"]+)['\"]",
    r"\brequire\s*\(\s*['\"](\.{1,2}/[^'\"]+)['\"]\s*\)",
    r"\bimport\s*\(\s*['\"](\.{1,2}/[^'\"]+)['\"]\s*\)",
)
FRAMEWORK_CONTRACTS_PATH = Path(__file__).resolve().parent.parent / "references" / "node-framework-contracts.json"


@dataclass
class Package:
    directory: Path
    relative: str
    manifest_path: Path
    manifest: dict[str, Any]
    workspace_member: bool = False

    @property
    def dependencies(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for key in ("dependencies", "devDependencies"):
            value = self.manifest.get(key, {})
            if isinstance(value, dict):
                result.update({str(name): str(version) for name, version in value.items()})
        return result

    @property
    def production_dependencies(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for key in ("dependencies", "optionalDependencies"):
            value = self.manifest.get(key, {})
            if isinstance(value, dict):
                result.update({str(name): str(version) for name, version in value.items()})
        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frontend-dir")
    parser.add_argument("--backend-dir")
    parser.add_argument("--frontend-build-command")
    parser.add_argument("--backend-build-command")
    parser.add_argument("--frontend-output-dir")
    parser.add_argument("--backend-output-dir")
    parser.add_argument("--backend-entry")
    parser.add_argument("--build-validation", type=Path)
    parser.add_argument("--frontend-node-version")
    parser.add_argument("--backend-node-version")
    parser.add_argument(
        "--backend-cloud-function-node-version",
        choices=[str(major) for major in CLOUD_FUNCTION_RUNTIMES],
        help="reviewed CloudBase function runtime override; does not change detected NodeVersion",
    )
    parser.add_argument("--backend-route-prefix", action="append", dest="backend_route_prefixes")
    parser.add_argument("--health-check-path")
    return parser.parse_args()


def load_build_validation(path: Path | None, root: Path) -> dict[str, Any] | None:
    if path is None:
        return None
    value = load_manifest(path.resolve())
    steps = value.get("Steps")
    artifacts = value.get("Artifacts")
    runtime_entry = value.get("RuntimeEntry")
    lockfile = value.get("Lockfile")
    if not isinstance(steps, list) or not steps or not isinstance(artifacts, list):
        raise SystemExit("error: build validation requires non-empty Steps and an Artifacts array")
    if not isinstance(runtime_entry, str) or not safe_project_relative(runtime_entry):
        raise SystemExit("error: build validation RuntimeEntry must be project-root-relative")
    if not isinstance(lockfile, str) or not safe_project_relative(lockfile):
        raise SystemExit("error: build validation Lockfile must be project-root-relative")
    if not (root / lockfile).is_file():
        raise SystemExit("error: build validation Lockfile does not exist")
    for step in steps:
        if not isinstance(step, dict) or step.get("Kind") not in {"install", "build", "start-probe"}:
            raise SystemExit("error: build validation step Kind must be install, build, or start-probe")
        if not isinstance(step.get("Command"), str) or not step["Command"].strip() or any(char in step["Command"] for char in "\r\n\x00"):
            raise SystemExit("error: build validation commands must be non-empty single-line strings")
        if not isinstance(step.get("Cwd"), str) or not safe_project_relative(step["Cwd"], allow_dot=True):
            raise SystemExit("error: build validation Cwd must be project-root-relative")
        allowed_exit_codes = {0, None} if step.get("Kind") == "start-probe" else {0}
        if step.get("Result") != "passed" or step.get("ExitCode") not in allowed_exit_codes:
            raise SystemExit("error: install/build validation requires exit code 0; a terminated start-probe may use null")
        if step.get("Kind") == "start-probe" and (
            step.get("Host") != "0.0.0.0"
            or step.get("Port") != 9000
            or step.get("TimeoutSeconds") != 30
            or step.get("HttpResponse") is not True
        ):
            raise SystemExit("error: start-probe must record 0.0.0.0:9000, a 30-second timeout, and an HTTP response")
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("Role") not in {"server-runtime", "runtime-assets", "runtime-metadata"}:
            raise SystemExit("error: build validation contains an unsupported artifact role")
        if not isinstance(artifact.get("Path"), str) or not safe_project_relative(artifact["Path"]):
            raise SystemExit("error: build validation artifact paths must be project-root-relative")
        if not isinstance(artifact.get("Source"), str) or not artifact["Source"].strip():
            raise SystemExit("error: build validation artifacts require a non-empty Source")
        if artifact.get("Required") is not True or artifact.get("Verification") not in {"fresh", "http-probed"}:
            raise SystemExit("error: build validation artifacts must be required and verified")
        artifact_path = root.joinpath(*PurePosixPath(artifact["Path"]).parts)
        try:
            artifact_path.resolve().relative_to(root.resolve())
        except ValueError as error:
            raise SystemExit("error: build validation artifact escapes the project root") from error
        if artifact_path.is_symlink() or not artifact_path.exists():
            raise SystemExit(f"error: build validation artifact does not exist: {artifact['Path']}")
    runtime_path = root.joinpath(*PurePosixPath(runtime_entry).parts)
    try:
        runtime_path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise SystemExit("error: build validation RuntimeEntry escapes the project root") from error
    if runtime_path.is_symlink() or not runtime_path.is_file():
        raise SystemExit("error: build validation RuntimeEntry does not exist")
    return value


def safe_project_relative(value: str, allow_dot: bool = False) -> bool:
    if value == "." and allow_dot:
        return True
    if not value or "\\" in value or any(char in value for char in "\r\n\x00"):
        return False
    pure = PurePosixPath(value)
    return not pure.is_absolute() and bool(pure.parts) and not any(part in {"", ".", ".."} for part in pure.parts)


def relative_to_root(path: Path, root: Path) -> str:
    relative = path.absolute().relative_to(root.resolve())
    return relative.as_posix() or "."


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"error: cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"error: package manifest must be an object: {path}")
    return value


def normalize_component_dir(value: str, root: Path) -> Path:
    pure = PurePosixPath(value.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise SystemExit(f"error: component directory must be source-root-relative: {value}")
    path = (root / Path(*pure.parts)).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise SystemExit(f"error: component directory escapes source root: {value}") from error
    if not (path / "package.json").is_file():
        raise SystemExit(f"error: component directory has no package.json: {value}")
    return path


def workspace_patterns(manifest: dict[str, Any]) -> list[str]:
    raw = manifest.get("workspaces", [])
    if isinstance(raw, dict):
        raw = raw.get("packages", [])
    if not isinstance(raw, list):
        return []
    return [value for value in raw if isinstance(value, str) and value and not PurePosixPath(value).is_absolute() and ".." not in PurePosixPath(value).parts]


def discover_packages(root: Path) -> list[Package]:
    root_manifest_path = root / "package.json"
    if not root_manifest_path.is_file():
        return []
    root_manifest = load_manifest(root_manifest_path)
    directories = {root}
    for pattern in workspace_patterns(root_manifest):
        for match in glob.glob(str(root / pattern)):
            candidate = Path(match).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if (candidate / "package.json").is_file():
                directories.add(candidate)
    packages = []
    for directory in sorted(directories):
        manifest_path = directory / "package.json"
        packages.append(Package(
            directory,
            relative_to_root(directory, root),
            manifest_path,
            load_manifest(manifest_path),
            workspace_member=directory != root,
        ))
    return packages


def inspect_build_free_static(root: Path, findings: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prove that a package-free source root is an already-built static website."""
    if (root / "package.json").exists() or not (root / "index.html").is_file():
        return None

    evidence: list[str] = []
    unsupported: list[str] = []
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in dirs:
            path = current_path / name
            relative = relative_to_root(path, root)
            if path.is_symlink():
                unsupported.append(relative)
            elif name == "_tmp":
                continue
            elif name in SKIP_DIRS:
                unsupported.append(relative)
            else:
                kept_dirs.append(name)
        dirs[:] = kept_dirs
        for name in names:
            path = current_path / name
            relative = relative_to_root(path, root)
            lowered = name.lower()
            if path.is_symlink() or not path.is_file():
                unsupported.append(relative)
                continue
            if lowered == ".env" or lowered.startswith(".env.") or lowered in SENSITIVE_NAMES:
                unsupported.append(relative)
                continue
            if path.suffix.lower() not in STATIC_FILE_SUFFIXES and lowered not in STATIC_FILE_NAMES:
                unsupported.append(relative)
                continue
            evidence.append(relative)

    if unsupported:
        add_finding(
            findings,
            "E_STATIC_TREE_UNSAFE",
            "error",
            "frontend",
            unsupported[:50],
            "A package-free static candidate contains unsupported, generated, sensitive, or linked paths.",
            "Keep only reviewed HTML, CSS, JavaScript, source maps, images, fonts, and standard static metadata files in the deploy directory, then rerun detection.",
        )
        return None
    return {
        "Unit": "frontend",
        "Directory": ".",
        "Framework": "other",
        "NodeVersion": "20",
        "BuildCommand": None,
        "BuildRecipe": [],
        "BuildArtifacts": [],
        "OutputPath": ".",
        "Entry": "index.html",
        "DeliveryMode": "static-files",
        "Evidence": sorted(evidence),
    }


def add_finding(
    findings: list[dict[str, Any]],
    code: str,
    severity: str,
    unit: str,
    evidence: list[str],
    reason: str,
    remediation: str,
) -> None:
    item = {
        "Code": code,
        "Severity": severity,
        "Unit": unit,
        "Evidence": sorted(set(evidence)),
        "Reason": reason,
        "Remediation": remediation,
    }
    signature = (code, unit, tuple(item["Evidence"]))
    if not any((entry["Code"], entry["Unit"], tuple(entry["Evidence"])) == signature for entry in findings):
        findings.append(item)


def detect_package_manager(root: Path, findings: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        ("npm", "package-lock.json"),
        ("yarn", "yarn.lock"),
        ("pnpm", "pnpm-lock.yaml"),
        ("bun", "bun.lock"),
        ("bun", "bun.lockb"),
    ]
    present = [(manager, lock) for manager, lock in candidates if (root / lock).is_file()]
    managers = sorted({manager for manager, _ in present})
    if len(managers) > 1:
        add_finding(findings, "E_LOCKFILE_CONFLICT", "error", "project", [lock for _, lock in present], "Multiple package-manager lockfiles are present and npm conversion has not completed.", "In the isolated delivery source, run npm install, keep the generated package-lock.json, remove non-npm lockfiles and package-manager-only runtime files, then rerun detection.")
        return {"Name": "conflict", "Lockfile": None}
    if present:
        manager, lockfile = present[0]
        if manager != "npm":
            add_finding(findings, "E_PACKAGE_MANAGER_UNSUPPORTED", "error", "project", [lockfile], f"The delivery contract uses npm, but the isolated source has not yet been converted from {manager}.", "Run npm install in the isolated delivery source. If it succeeds, keep package-lock.json, remove the old package-manager lock/config files, and rerun detection; if it fails, fix only the incompatibility named by npm and retry.")
        return {"Name": manager, "Lockfile": lockfile}
    add_finding(findings, "E_LOCKFILE_MISSING", "error", "project", ["package.json"] if (root / "package.json").exists() else [], "The isolated delivery source has no npm lockfile yet.", "Run npm install once in the isolated delivery source, retain the generated package-lock.json, and rerun detection. The generated lockfile is delivery source, not a build artifact.")
    return {"Name": "unknown", "Lockfile": None}


def package_for_dir(packages: list[Package], directory: Path, root: Path) -> Package:
    for package in packages:
        if package.directory == directory:
            return package
    package = Package(
        directory,
        relative_to_root(directory, root),
        directory / "package.json",
        load_manifest(directory / "package.json"),
        workspace_member=False,
    )
    packages.append(package)
    return package


def frontend_framework(package: Package) -> str | None:
    deps = package.dependencies
    # vinext applications also depend on Next.js. Detect the concrete runtime
    # adapter before the compatibility framework so it is not misclassified.
    if "vinext" in deps:
        return "vinext"
    if "next" in deps:
        return "next"
    if "nuxt" in deps:
        return "nuxt"
    if "@sveltejs/kit" in deps:
        return "sveltekit"
    if "vitepress" in deps:
        return "vitepress"
    if "astro" in deps:
        return "astro"
    if "@angular/core" in deps:
        return "angular"
    if "react-scripts" in deps:
        return "create-react-app"
    if "vite" in deps:
        return "vite"
    if "vue" in deps:
        return "vue"
    if "react" in deps:
        return "react"
    return None


def backend_framework(package: Package) -> str | None:
    deps = package.production_dependencies
    for dependency, name in (("express", "express"), ("koa", "koa"), ("@nestjs/core", "nestjs"), ("fastify", "fastify"), ("@hapi/hapi", "hapi")):
        if dependency in deps:
            return name
    return None


def read_small_sources(directory: Path) -> list[tuple[Path, str]]:
    results: list[tuple[Path, str]] = []
    total = 0
    for root, dirs, names in os.walk(directory, topdown=True, followlinks=False):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not (Path(root) / name).is_symlink()]
        for name in names:
            path = Path(root) / name
            if path.suffix.lower() not in SOURCE_SUFFIXES or path.is_symlink() or path.stat().st_size > 512 * 1024:
                continue
            total += path.stat().st_size
            if total > 8 * 1024 * 1024:
                return results
            try:
                results.append((path, path.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return results


def iframe_scan_text(path: Path, text: str) -> str:
    """Mask comments while preserving offsets used for evidence line numbers."""
    def mask(match: re.Match[str]) -> str:
        return "".join("\n" if character == "\n" else " " for character in match.group(0))

    if path.suffix.lower() in SOURCE_SUFFIXES:
        text = re.sub(r"/\*.*?\*/", mask, text, flags=re.S)
        text = re.sub(r"(^|[ \t])//[^\r\n]*", mask, text, flags=re.M)
    elif path.name.lower() in {"_headers", "netlify.toml", "nginx.conf"}:
        text = re.sub(r"^[ \t]*#[^\r\n]*", mask, text, flags=re.M)
    return text


def iframe_config_sources(root: Path) -> list[tuple[Path, str]]:
    sources: list[tuple[Path, str]] = []
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            name for name in dirs
            if name not in IFRAME_SCAN_SKIP_DIRS and not (current_path / name).is_symlink()
        ]
        for name in names:
            path = current_path / name
            if name.lower() not in IFRAME_HEADER_CONFIG_NAMES or path.is_symlink():
                continue
            try:
                if not path.is_file() or path.stat().st_size > 512 * 1024:
                    continue
                sources.append((path, path.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return sources


def inspect_iframe_embedding_constraints(
    root: Path,
    runtime_packages: list[tuple[Package, list[Path] | None]],
    findings: list[dict[str, Any]],
) -> None:
    candidates: dict[Path, str] = dict(iframe_config_sources(root))
    for package, source_scope in runtime_packages:
        allowed_sources = set(source_scope) if source_scope is not None else None
        for path, text in read_small_sources(package.directory):
            if allowed_sources is not None and path not in allowed_sources:
                continue
            relative_parts = path.relative_to(package.directory).parts
            if any(part in IFRAME_SCAN_SKIP_DIRS for part in relative_parts[:-1]):
                continue
            if re.search(r"(?:^|\.)(?:spec|test)\.[^.]+$", path.name, re.I):
                continue
            candidates[path] = text
        try:
            candidates[package.manifest_path] = package.manifest_path.read_text(encoding="utf-8")
        except OSError:
            pass

    evidence: list[str] = []
    restrictions: set[str] = set()
    for path, raw_text in sorted(candidates.items(), key=lambda item: item[0].as_posix()):
        text = iframe_scan_text(path, raw_text)
        matched_lines: set[int] = set()
        for label, pattern in IFRAME_RESTRICTION_PATTERNS:
            for match in pattern.finditer(text):
                restrictions.add(label)
                matched_lines.add(text.count("\n", 0, match.start()) + 1)
        relative = relative_to_root(path, root)
        evidence.extend(f"{relative}:{line}" for line in sorted(matched_lines))

    if evidence:
        add_finding(
            findings,
            "E_IFRAME_EMBEDDING_FORBIDDEN",
            "error",
            "project",
            evidence,
            "知乎 AI Works 支持部署的项目需要可以被 iframe 内嵌。当前项目的有效响应头配置会阻止产品宿主内嵌部署页面："
            + "; ".join(sorted(restrictions))
            + "。",
            "This finding is a hard packaging gate. Ask only whether the user explicitly authorizes removal of every matched iframe restriction; do not offer a partial-removal option that preserves an effective blocker. Decline, skip, silence, or ambiguous consent keeps the plan blocked. Authorization permits only the minimal source/configuration edits and does not itself unlock artifact generation. Remove every matched frame-ancestors directive, X-Frame-Options/frameguard setting, and JavaScript frame-busting behavior; preserve every unrelated CSP directive and security middleware, run relevant tests or a start probe, then re-detect from scratch. Runtime inputs, descriptors, and the archive may be generated only from a fresh non-blocked plan in which E_IFRAME_EMBEDDING_FORBIDDEN is absent.",
        )


def node_http_candidate(package: Package) -> bool:
    """Require both a declared runtime entry and source-level HTTP evidence."""
    entry, _ = infer_backend_entry(package, None)
    if not entry:
        return False
    sources = server_source_texts(package) or read_small_sources(package.directory)
    return any(
        re.search(r"\.(?:listen)\s*\(|\b(?:createServer|serve)\s*\(", text)
        for _, text in sources
    )


def load_framework_contracts() -> dict[str, dict[str, Any]]:
    value = load_manifest(FRAMEWORK_CONTRACTS_PATH)
    contracts = value.get("Contracts")
    if not isinstance(contracts, list):
        raise SystemExit("error: node framework contracts must contain a Contracts array")
    result: dict[str, dict[str, Any]] = {}
    for contract in contracts:
        if isinstance(contract, dict) and isinstance(contract.get("Framework"), str):
            if contract.get("LaunchKind") is not None and contract.get("LaunchKind") not in {"node-entry", "npm-script"}:
                raise SystemExit(
                    f"error: framework contract for {contract['Framework']!r} must declare a valid LaunchKind"
                )
            result[contract["Framework"]] = contract
    return result


def locked_package_version(root: Path, package: Package, package_name: str) -> str | None:
    lockfile = root / "package-lock.json"
    if not lockfile.is_file():
        return None
    try:
        value = json.loads(lockfile.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    packages = value.get("packages") if isinstance(value, dict) else None
    if not isinstance(packages, dict):
        return None
    directory = PurePosixPath() if package.relative == "." else PurePosixPath(package.relative)
    while True:
        metadata = packages.get((directory / "node_modules" / package_name).as_posix())
        version = metadata.get("version") if isinstance(metadata, dict) else None
        if isinstance(version, str):
            return version
        if not directory.parts:
            return None
        directory = directory.parent


def framework_contract(
    framework: str,
    package: Package,
    root: Path,
    findings: list[dict[str, Any]],
    validation: dict[str, Any] | None,
    evidence: list[str],
) -> dict[str, Any] | None:
    contract = load_framework_contracts().get(framework)
    if contract is None:
        return None
    package_name = contract.get("Package")
    version = locked_package_version(root, package, package_name) if isinstance(package_name, str) else None
    major_match = re.match(r"^(\d+)(?:\.|$)", version or "")
    major = int(major_match.group(1)) if major_match else None
    minimum = contract.get("MinMajor")
    maximum = contract.get("MaxMajorExclusive")
    supported = isinstance(major, int) and isinstance(minimum, int) and isinstance(maximum, int) and minimum <= major < maximum
    if not supported and validation is None:
        add_finding(
            findings,
            "E_FRAMEWORK_CONTRACT_UNSUPPORTED",
            "error",
            "backend",
            [*evidence, "package-lock.json"],
            f"No versioned static {framework} output contract covers locked version {version or 'unknown'}.",
            "Run the authorized Agent install/build verification, record BuildValidation and exact artifacts, then rerun detection; do not guess from an unversioned framework convention.",
        )
    resolved = {
        "Id": contract.get("Id"),
        "Package": package_name,
        "Version": version or "unknown",
        "Match": "agent-build-verified" if not supported and validation is not None else "version-range",
    }
    if contract.get("LaunchKind") in {"node-entry", "npm-script"}:
        resolved["LaunchKind"] = contract["LaunchKind"]
    return resolved


def server_serves_frontend(package: Package) -> bool:
    """Recognize a hand-written SSR monolith whose server serves the built frontend."""
    return any(
        re.search(pattern, text, re.I)
        for pattern in SERVER_FRONTEND_PATTERNS
        for _, text in server_source_texts(package)
    )


def resolve_relative_source(importer: Path, specifier: str, package: Package) -> Path | None:
    """Resolve one project-local JS/TS module without executing package resolution."""
    normalized = re.split(r"[?#]", specifier, maxsplit=1)[0]
    base = (importer.parent / normalized).resolve(strict=False)
    package_root = package.directory.resolve()
    try:
        base.relative_to(package_root)
    except ValueError:
        return None
    candidates = [base]
    if base.suffix:
        if base.suffix in {".js", ".jsx", ".mjs", ".cjs"}:
            candidates.extend(base.with_suffix(suffix) for suffix in (".ts", ".tsx"))
    else:
        candidates.extend(base.with_suffix(suffix) for suffix in sorted(SOURCE_SUFFIXES))
        candidates.extend(base / f"index{suffix}" for suffix in sorted(SOURCE_SUFFIXES))
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink() and candidate.suffix.lower() in SOURCE_SUFFIXES:
            return candidate
    return None


def server_source_texts(package: Package) -> list[tuple[Path, str]]:
    """Return the source entry and its statically resolvable relative import closure."""
    entry, _ = infer_backend_entry(package, None)
    if not entry:
        return []
    entry_path = (package.directory / entry).resolve(strict=False)
    try:
        entry_path.relative_to(package.directory.resolve())
    except ValueError:
        return []
    if not entry_path.is_file() or entry_path.is_symlink() or entry_path.suffix.lower() not in SOURCE_SUFFIXES:
        return []
    pending = [entry_path]
    seen: set[Path] = set()
    sources: list[tuple[Path, str]] = []
    while pending:
        path = pending.pop()
        if path in seen or path.stat().st_size > 512 * 1024:
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sources.append((path, text))
        specifiers = {
            match
            for pattern in RELATIVE_MODULE_PATTERNS
            for match in re.findall(pattern, text)
        }
        for specifier in sorted(specifiers):
            resolved = resolve_relative_source(path, specifier, package)
            if resolved is not None and resolved not in seen:
                pending.append(resolved)
    return sorted(sources, key=lambda item: item[0].as_posix())


def server_source_files(package: Package) -> list[Path]:
    return [path for path, _ in server_source_texts(package)]


def config_text(package: Package, names: tuple[str, ...]) -> tuple[str, list[str]]:
    chunks: list[str] = []
    evidence: list[str] = []
    for name in names:
        path = package.directory / name
        if path.is_file() and path.stat().st_size <= 512 * 1024:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            evidence.append(name)
    return "\n".join(chunks), evidence


def strip_js_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(^|\s)//[^\n]*", r"\1", text)


def parse_jsonc(text: str) -> Any:
    """Parse JSON-with-comments and trailing commas without altering string literals."""
    uncommented: list[str] = []
    index = 0
    quote = False
    escaped = False
    while index < len(text):
        character = text[index]
        if quote:
            uncommented.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quote = False
            index += 1
            continue
        if character == '"':
            quote = True
            uncommented.append(character)
            index += 1
            continue
        if character == "/" and index + 1 < len(text) and text[index + 1] == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if character == "/" and index + 1 < len(text) and text[index + 1] == "*":
            index += 2
            while index + 1 < len(text) and text[index:index + 2] != "*/":
                if text[index] in "\r\n":
                    uncommented.append(text[index])
                index += 1
            index = min(index + 2, len(text))
            continue
        uncommented.append(character)
        index += 1

    cleaned = "".join(uncommented)
    without_trailing_commas: list[str] = []
    index = 0
    quote = False
    escaped = False
    while index < len(cleaned):
        character = cleaned[index]
        if quote:
            without_trailing_commas.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quote = False
            index += 1
            continue
        if character == '"':
            quote = True
        elif character == ",":
            lookahead = index + 1
            while lookahead < len(cleaned) and cleaned[lookahead].isspace():
                lookahead += 1
            if lookahead < len(cleaned) and cleaned[lookahead] in "}]":
                index += 1
                continue
        without_trailing_commas.append(character)
        index += 1
    return json.loads("".join(without_trailing_commas))


def component_evidence(package: Package, root: Path, selector: str) -> str:
    return f"{relative_to_root(package.manifest_path, root)}#{selector}"


def resolution_fact(fact: str, source: str, value: str, method: str) -> dict[str, str]:
    return {"Fact": fact, "Source": source, "Value": value, "Method": method}


def runtime_resolution(
    resolver: str,
    output_source: str,
    entry_source: str,
    facts: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "Resolver": resolver,
        "OutputPathSource": output_source,
        "RuntimeEntrySource": entry_source,
        "Evidence": facts,
    }


def literal_config_value(text: str, name: str) -> str | None:
    values = set(re.findall(rf"\b{re.escape(name)}\s*:\s*['\"]([^'\"]+)['\"]", strip_js_comments(text)))
    return values.pop() if len(values) == 1 else None


def config_has_dynamic_property(text: str, name: str) -> bool:
    uncommented = strip_js_comments(text)
    return bool(re.search(rf"\b{re.escape(name)}\s*:", uncommented)) and literal_config_value(uncommented, name) is None


def literal_object_body(text: str, name: str) -> str | None:
    """Return one statically delimited object-literal body for a named property."""
    uncommented = strip_js_comments(text)
    matches = list(re.finditer(rf"\b{re.escape(name)}\s*:\s*\{{", uncommented))
    if len(matches) != 1:
        return None
    start = matches[0].end() - 1
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(start, len(uncommented)):
        character = uncommented[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"', "`"}:
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return uncommented[start + 1:index]
    return None


def require_explicit_output_configuration(
    findings: list[dict[str, Any]],
    evidence: list[str],
    framework: str,
    target: str,
    instruction: str,
) -> None:
    add_finding(
        findings,
        "E_BACKEND_OUTPUT_CONFIGURATION_REQUIRED",
        "error",
        "backend",
        evidence,
        f"{framework} has no statically proven explicit server output directory; a framework default is not persisted project evidence.",
        f"Directly configure the isolated delivery source to emit {target!r}: {instruction} Rerun detection from scratch and disclose the changed config and output path in the final ZIP handoff; no separate authorization pause is required for this delivery-standard edit.",
    )


def require_agent_build_resolution(
    findings: list[dict[str, Any]],
    evidence: list[str],
    framework: str,
) -> None:
    add_finding(
        findings,
        "E_BACKEND_OUTPUT_AMBIGUOUS",
        "error",
        "backend",
        evidence,
        f"{framework} output configuration exists but cannot be reduced to one literal server output path without executing the trusted project build.",
        "In the Agent's authorized validation environment, install dependencies, run the real backend build, inspect the emitted server entry, and start-probe that entry with PORT=9000 and host 0.0.0.0. Then rerun detection with reviewed --backend-output-dir and --backend-entry values. Do not include the local build output in the ZIP; disclose the validation commands and evidence at handoff.",
    )


def require_agent_build_for_tool(
    findings: list[dict[str, Any]],
    package: Package,
    root: Path,
    command: str,
) -> None:
    add_finding(
        findings,
        "E_AGENT_BUILD_REQUIRED",
        "error",
        "backend",
        [component_evidence(package, root, "scripts.build")],
        f"Build command {command!r} is outside the closed static resolver set.",
        "Run the real npm build in the authorized Agent environment, verify fresh RuntimeEntry and BuildArtifacts, conditionally HTTP start-probe the entry, record BuildValidation, and rerun detection.",
    )


def framework_server_runtime_evidence(package: Package, framework: str, root: Path) -> list[str]:
    """Find framework-conventional files and source patterns that require a runtime server."""
    evidence: set[str] = set()
    for path, text in read_small_sources(package.directory):
        relative = path.relative_to(package.directory).as_posix()
        normalized = f"/{relative}"
        if framework in {"next", "vinext"}:
            path_match = (
                normalized.startswith("/pages/api/")
                or bool(re.search(r"/app/.+/route\.(?:js|jsx|ts|tsx|mjs|cjs)$", normalized))
                or bool(re.fullmatch(r"/(?:src/)?middleware\.(?:js|jsx|ts|tsx|mjs|cjs)", normalized))
            )
            source_match = bool(re.search(
                r"['\"]use server['\"]|\bgetServerSideProps\b|from\s+['\"]next/(?:headers|server)['\"]|\bdynamic\s*=\s*['\"]force-dynamic['\"]",
                text,
            ))
        elif framework == "nuxt":
            path_match = normalized.startswith("/server/")
            source_match = bool(re.search(r"\bdefineEventHandler\s*\(|\buseRequestHeaders\s*\(|\bgetCookie\s*\(", text))
        elif framework == "sveltekit":
            path_match = bool(re.search(r"/\+(?:server|page\.server|layout\.server)\.(?:js|ts)$", normalized))
            source_match = bool(re.search(r"\bexport\s+const\s+actions\b|\bRequestHandler\b", text))
        else:
            path_match = False
            source_match = False
        if path_match or source_match:
            evidence.add(relative_to_root(path, root))
    return sorted(evidence)


def resolve_next_backend(
    package: Package,
    text: str,
    configs: list[str],
    evidence: list[str],
    findings: list[dict[str, Any]],
    entry_override: str | None,
    output_override: str | None,
) -> dict[str, Any]:
    config_paths = [f"{package.relative}/{name}" if package.relative != "." else name for name in configs]
    tracing_root_present = bool(re.search(r"\boutputFileTracingRoot\s*:", strip_js_comments(text)))
    if package.relative != "." and tracing_root_present and not entry_override:
        add_finding(findings, "E_SSR_RUNTIME_ENTRY_UNRESOLVED", "error", "backend", evidence, "Next.js outputFileTracingRoot changes the nested standalone server layout, so the actual server.js path is not statically proven.", "Run the authorized Agent-side build, locate and start-probe the generated standalone server.js, then provide its path relative to the configured standalone directory through --backend-entry.")
    if output_override:
        output, source = output_override, "agent-build-verified"
        output_fact = resolution_fact("output-path", "reviewed-override:backendOutputDir", output, "agent-build-verified")
    else:
        dist_dir = literal_config_value(text, "distDir")
        if dist_dir:
            output, source = f"{dist_dir.rstrip('/')}/standalone", "framework-config"
            output_fact = resolution_fact("output-path", f"{config_paths[0]}#distDir" if config_paths else "next.config#distDir", output, "configured")
        elif config_has_dynamic_property(text, "distDir"):
            require_agent_build_resolution(findings, config_paths or evidence, "Next.js")
            output, source = ".next/standalone", "unresolved-dynamic-config"
            output_fact = resolution_fact("output-path", f"{config_paths[0]}#distDir" if config_paths else "next.config#distDir", output, "unresolved")
        else:
            require_explicit_output_configuration(findings, config_paths or evidence, "Next.js", ".cloudbase-next/standalone", "set next.config distDir to '.cloudbase-next' while retaining output: 'standalone'.")
            output, source = ".cloudbase-next/standalone", "pending-agent-configuration"
            output_fact = resolution_fact("output-path", "required next.config#distDir", output, "pending-configuration")
    entry = entry_override or "server.js"
    entry_fact = resolution_fact("runtime-entry", "reviewed-override:backendEntry" if entry_override else "Next.js standalone server contract", entry, "agent-build-verified" if entry_override else "framework-fixed")
    return {"DeliveryMode": "ssr-node", "OutputPath": output, "Entry": entry, "RuntimeResolution": runtime_resolution("next-resolver", source, entry_fact["Method"], [output_fact, entry_fact])}


def resolve_vinext_backend(entry_override: str | None, output_override: str | None) -> dict[str, Any]:
    output = output_override or "dist/standalone"
    source = "agent-build-verified" if output_override else "framework-fixed"
    output_fact = resolution_fact("output-path", "reviewed-override:backendOutputDir" if output_override else "vinext standalone build contract", output, "agent-build-verified" if output_override else "framework-fixed")
    entry = entry_override or "server.js"
    entry_fact = resolution_fact("runtime-entry", "reviewed-override:backendEntry" if entry_override else "vinext standalone server contract", entry, "agent-build-verified" if entry_override else "framework-fixed")
    return {"DeliveryMode": "ssr-node", "OutputPath": output, "Entry": entry, "RuntimeResolution": runtime_resolution("vinext-resolver", source, entry_fact["Method"], [output_fact, entry_fact])}


def resolve_nuxt_backend(
    package: Package,
    text: str,
    configs: list[str],
    evidence: list[str],
    findings: list[dict[str, Any]],
    entry_override: str | None,
    output_override: str | None,
) -> dict[str, Any]:
    config_paths = [f"{package.relative}/{name}" if package.relative != "." else name for name in configs]
    nitro_body = literal_object_body(text, "nitro")
    output_body = literal_object_body(nitro_body, "output") if nitro_body is not None else None
    if output_override:
        output, source = output_override, "agent-build-verified"
        output_fact = resolution_fact("output-path", "reviewed-override:backendOutputDir", output, "agent-build-verified")
    else:
        server_dir = literal_config_value(output_body, "serverDir") if output_body is not None else None
        output_dir = literal_config_value(output_body, "dir") if output_body is not None else None
        if server_dir:
            output, source = server_dir, "framework-config"
            output_fact = resolution_fact("output-path", f"{config_paths[0]}#nitro.output.serverDir" if config_paths else "nuxt.config#nitro.output.serverDir", output, "configured")
        elif output_dir:
            output, source = f"{output_dir.rstrip('/')}/server", "framework-config"
            output_fact = resolution_fact("output-path", f"{config_paths[0]}#nitro.output.dir" if config_paths else "nuxt.config#nitro.output.dir", output, "configured")
        elif (
            (bool(re.search(r"\bnitro\s*:", text)) and nitro_body is None)
            or (nitro_body is not None and bool(re.search(r"\boutput\s*:", nitro_body)) and output_body is None)
            or (output_body is not None and (config_has_dynamic_property(output_body, "serverDir") or config_has_dynamic_property(output_body, "dir")))
        ):
            require_agent_build_resolution(findings, config_paths or evidence, "Nuxt/Nitro")
            output, source = ".output/server", "unresolved-dynamic-config"
            output_fact = resolution_fact("output-path", f"{config_paths[0]}#nitro.output" if config_paths else "nuxt.config#nitro.output", output, "unresolved")
        else:
            require_explicit_output_configuration(findings, config_paths or evidence, "Nuxt/Nitro", ".cloudbase-nitro/server", "set nitro.preset to 'node-server' and nitro.output.serverDir to '.cloudbase-nitro/server'.")
            output, source = ".cloudbase-nitro/server", "pending-agent-configuration"
            output_fact = resolution_fact("output-path", "required nuxt.config#nitro.output.serverDir", output, "pending-configuration")
    entry = entry_override or "index.mjs"
    entry_fact = resolution_fact("runtime-entry", "reviewed-override:backendEntry" if entry_override else "Nitro node-server contract", entry, "agent-build-verified" if entry_override else "framework-fixed")
    return {"DeliveryMode": "ssr-node", "OutputPath": output, "Entry": entry, "RuntimeResolution": runtime_resolution("nuxt-nitro-resolver", source, entry_fact["Method"], [output_fact, entry_fact])}


def resolve_sveltekit_backend(
    package: Package,
    text: str,
    configs: list[str],
    evidence: list[str],
    findings: list[dict[str, Any]],
    entry_override: str | None,
    output_override: str | None,
) -> dict[str, Any]:
    config_paths = [f"{package.relative}/{name}" if package.relative != "." else name for name in configs]
    if output_override:
        output, source = output_override, "agent-build-verified"
        output_fact = resolution_fact("output-path", "reviewed-override:backendOutputDir", output, "agent-build-verified")
    else:
        adapter_match = re.search(r"\badapter\s*:\s*[A-Za-z_$][\w$]*\s*\(\s*\{(?P<body>.*?)\}\s*\)", text, re.S)
        adapter_body = adapter_match.group("body") if adapter_match else ""
        adapter_out = literal_config_value(adapter_body, "out")
        if adapter_out:
            output, source = adapter_out, "framework-config"
            output_fact = resolution_fact("output-path", f"{config_paths[0]}#kit.adapter.out" if config_paths else "svelte.config#kit.adapter.out", output, "configured")
        elif adapter_match and config_has_dynamic_property(adapter_body, "out"):
            require_agent_build_resolution(findings, config_paths or evidence, "SvelteKit adapter-node")
            output, source = "build", "unresolved-dynamic-config"
            output_fact = resolution_fact("output-path", f"{config_paths[0]}#kit.adapter.out" if config_paths else "svelte.config#kit.adapter.out", output, "unresolved")
        else:
            require_explicit_output_configuration(findings, config_paths or evidence, "SvelteKit adapter-node", ".cloudbase-sveltekit", "set adapter({ out: '.cloudbase-sveltekit' }) in svelte.config.")
            output, source = ".cloudbase-sveltekit", "pending-agent-configuration"
            output_fact = resolution_fact("output-path", "required svelte.config#kit.adapter.out", output, "pending-configuration")
    entry = entry_override or "index.js"
    entry_fact = resolution_fact("runtime-entry", "reviewed-override:backendEntry" if entry_override else "adapter-node server contract", entry, "agent-build-verified" if entry_override else "framework-fixed")
    return {"DeliveryMode": "ssr-node", "OutputPath": output, "Entry": entry, "RuntimeResolution": runtime_resolution("sveltekit-adapter-node-resolver", source, entry_fact["Method"], [output_fact, entry_fact])}


def classify_web_candidate(
    package: Package,
    framework: str,
    findings: list[dict[str, Any]],
    root: Path,
    ssr_entry_override: str | None = None,
    backend_output_override: str | None = None,
) -> tuple[str, list[str], dict[str, Any] | None]:
    """Classify a web package and resolve its server output through a framework resolver."""
    evidence = [relative_to_root(package.manifest_path, root)]
    scripts = package.manifest.get("scripts", {}) if isinstance(package.manifest.get("scripts"), dict) else {}
    runtime_evidence = framework_server_runtime_evidence(package, framework, root)
    if ssr_entry_override:
        override = PurePosixPath(ssr_entry_override.replace("\\", "/"))
        if override.is_absolute() or not override.parts or any(part in ("", ".", "..") for part in override.parts):
            raise SystemExit("error: backend entry must be a safe path relative to the framework output directory")
    if backend_output_override:
        override = PurePosixPath(backend_output_override.replace("\\", "/"))
        if override.is_absolute() or not override.parts or any(part in ("", ".", "..") for part in override.parts):
            raise SystemExit("error: backend output directory must be a safe path relative to the backend component")
    if framework in {"next", "vinext"}:
        text, configs = config_text(package, ("next.config.js", "next.config.mjs", "next.config.cjs", "next.config.ts"))
        evidence.extend(f"{package.relative}/{name}" if package.relative != "." else name for name in configs)
        output_mode = literal_config_value(text, "output")
        is_export = output_mode == "export"
        is_standalone = output_mode == "standalone"
        if is_export and not runtime_evidence:
            return "static", sorted(set(evidence)), None
        if is_export and runtime_evidence:
            add_finding(
                findings,
                "E_SSR_BUILD_CONFIG_CONFLICT",
                "error",
                "backend",
                [*evidence, *runtime_evidence],
                f"{framework} declares output: 'export' but still contains request-time server features.",
                "Choose one delivery model: remove the server features for a static export, or change the reviewed config to output: 'standalone' for SSR, then rerun detection.",
            )
        elif not is_standalone:
            add_finding(
                findings,
                "E_SSR_BUILD_CONFIG_UNSUPPORTED",
                "error",
                "backend",
                evidence,
                f"{framework} SSR was detected but output: 'standalone' is not proven.",
                f"Set output: 'standalone' in the reviewed {framework} config so CloudBase can build the traced Node server from source.",
            )
        profile = (
            resolve_vinext_backend(ssr_entry_override, backend_output_override)
            if framework == "vinext"
            else resolve_next_backend(package, text, configs, evidence, findings, ssr_entry_override, backend_output_override)
        )
        return "ssr", sorted(set([*evidence, *runtime_evidence])), profile
    elif framework == "nuxt":
        build_values = " ".join(str(value) for value in scripts.values())
        if "generate" in build_values and not runtime_evidence:
            return "static", sorted(set(evidence)), None
        text, configs = config_text(package, ("nuxt.config.js", "nuxt.config.mjs", "nuxt.config.cjs", "nuxt.config.ts"))
        evidence.extend(f"{package.relative}/{name}" if package.relative != "." else name for name in configs)
        uncommented = strip_js_comments(text)
        nitro_body = literal_object_body(uncommented, "nitro")
        preset_match = re.search(r"\bpreset\s*:\s*['\"]([^'\"]+)['\"]", nitro_body or "")
        if preset_match and preset_match.group(1) not in {"node", "node-server", "node_server"}:
            add_finding(
                findings,
                "E_SSR_BUILD_CONFIG_UNSUPPORTED",
                "error",
                "backend",
                evidence,
                f"Nuxt SSR uses Nitro preset {preset_match.group(1)!r}, which does not prove the required Node server output.",
                "Use the default Node server preset or set nitro.preset to 'node-server', then verify .output/server/index.mjs in the CloudBase source build.",
            )
        return "ssr", sorted(set([*evidence, *runtime_evidence])), resolve_nuxt_backend(package, uncommented, configs, evidence, findings, ssr_entry_override, backend_output_override)
    elif framework == "sveltekit":
        text, configs = config_text(package, ("svelte.config.js", "svelte.config.ts"))
        evidence.extend(f"{package.relative}/{name}" if package.relative != "." else name for name in configs)
        uncommented = strip_js_comments(text)
        if "adapter-static" in uncommented and not runtime_evidence:
            return "static", sorted(set(evidence)), None
        has_adapter_import = bool(re.search(r"(?:from\s*|require\s*\(\s*)['\"]@sveltejs/adapter-node['\"]", uncommented))
        has_adapter_call = bool(re.search(r"\badapter\s*:\s*[A-Za-z_$][\w$]*\s*\(", uncommented))
        if not (has_adapter_import and has_adapter_call) or "@sveltejs/adapter-node" not in package.dependencies:
            add_finding(
                findings,
                "E_SSR_BUILD_CONFIG_UNSUPPORTED",
                "error",
                "backend",
                [*evidence, *runtime_evidence],
                "SvelteKit SSR was detected but @sveltejs/adapter-node is not proven in both config and dependencies.",
                "Configure the reviewed project with @sveltejs/adapter-node so the CloudBase source build produces a Node server in build/, then rerun detection.",
            )
        return "ssr", sorted(set([*evidence, *runtime_evidence])), resolve_sveltekit_backend(package, uncommented, configs, evidence, findings, ssr_entry_override, backend_output_override)
    return "static", sorted(set(evidence)), None


def infer_node_major(package: Package, root_package: Package | None, explicit: str | None) -> tuple[str | None, list[str]]:
    evidence: list[str] = []
    if explicit:
        match = re.fullmatch(r"v?(\d+)(?:\.\d+(?:\.\d+)?)?", explicit.strip())
        return (match.group(1), evidence) if match else (None, evidence)
    for candidate in (package.directory / ".nvmrc", package.directory / ".node-version"):
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8", errors="replace").strip()
            match = re.search(r"(?<!\d)(\d+)(?:\.\d+){0,2}", text)
            if match:
                evidence.append(candidate.name)
                return match.group(1), evidence
    for current in (package, root_package):
        if current is None:
            continue
        engines = current.manifest.get("engines", {})
        value = engines.get("node") if isinstance(engines, dict) else None
        if isinstance(value, str):
            majors = set(re.findall(r"(?<!\d)(\d+)(?:\.\d+){0,2}", value))
            if len(majors) == 1:
                evidence.append(relative_to_root(current.manifest_path, current.directory if current is package else root_package.directory))
                return majors.pop(), evidence
    return None, evidence


def attach_cloud_function_runtime(
    component: dict[str, Any],
    reviewed_override: str | None,
    findings: list[dict[str, Any]],
) -> None:
    node_version = component.get("NodeVersion")
    if not isinstance(node_version, str) or not node_version.isdigit():
        return
    if int(node_version) > 24 and reviewed_override not in {None, "24"}:
        raise SystemExit(
            "error: backend Node versions above 24 only accept the reviewed CloudBase function Node 24 override"
        )
    selected = cloud_function_runtime(node_version, reviewed_override)
    if selected is not None:
        component["CloudFunctionRuntime"] = selected
        return
    evidence = component.get("Evidence")
    component["CloudFunctionRuntime"] = None
    add_finding(
        findings,
        "E_CLOUDBASERC_RUNTIME_UNSUPPORTED",
        "error",
        "backend",
        evidence if isinstance(evidence, list) and evidence else ["backend NodeVersion"],
        f"Detected Node {node_version} is above the fixed cloudbaserc runtime table, whose highest target is Nodejs24.11.",
        "Ask the user to explicitly authorize a CloudBase function runtime downgrade to Node 24, then rerun detection with --backend-cloud-function-node-version 24. The reviewed override changes only CloudFunctionRuntime and must not replace the detected backend NodeVersion.",
    )


def infer_output(package: Package, framework: str, root: Path) -> tuple[str | None, list[str]]:
    """Infer the static output path relative to the downstream build root."""
    component_output = {
        "vite": "dist",
        "vitepress": ".vitepress/dist",
        "astro": "dist",
        "create-react-app": "build",
        "next": "out",
        "vinext": "dist/client",
        "nuxt": ".output/public",
        "sveltekit": "build",
        "angular": "dist",
        "vue": "dist",
        "react": "dist",
    }.get(framework)
    evidence: list[str] = []

    if framework in {"vite", "vitepress", "react", "vue"} and "vite" in package.dependencies:
        text, configs = config_text(package, ("vite.config.js", "vite.config.mjs", "vite.config.cjs", "vite.config.ts"))
        match = re.search(r"\boutDir\s*:\s*['\"]([^'\"]+)['\"]", strip_js_comments(text))
        if match:
            component_output = match.group(1)
            evidence.extend(f"{package.relative}/{name}" if package.relative != "." else name for name in configs)
    elif framework == "vue":
        text, configs = config_text(package, ("vue.config.js", "vue.config.cjs"))
        match = re.search(r"\boutputDir\s*:\s*['\"]([^'\"]+)['\"]", strip_js_comments(text))
        if match:
            component_output = match.group(1)
            evidence.extend(f"{package.relative}/{name}" if package.relative != "." else name for name in configs)
    elif framework == "angular":
        angular_json = package.directory / "angular.json"
        if angular_json.is_file():
            try:
                config = json.loads(angular_json.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                config = {}
            projects = config.get("projects", {}) if isinstance(config, dict) else {}
            output_paths: set[str] = set()
            if isinstance(projects, dict):
                for project in projects.values():
                    if not isinstance(project, dict):
                        continue
                    architect = project.get("architect", project.get("targets", {}))
                    build = architect.get("build", {}) if isinstance(architect, dict) else {}
                    options = build.get("options", {}) if isinstance(build, dict) else {}
                    value = options.get("outputPath") if isinstance(options, dict) else None
                    if isinstance(value, str):
                        output_paths.add(value)
                    elif isinstance(value, dict) and isinstance(value.get("base"), str):
                        output_paths.add(value["base"])
            if len(output_paths) == 1:
                component_output = output_paths.pop()
                evidence.append(relative_to_root(angular_json, root))

    if component_output is None:
        return None, evidence
    pure = PurePosixPath(component_output.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        return None, evidence
    prefix = PurePosixPath() if package.relative == "." else PurePosixPath(package.relative)
    return (prefix / pure).as_posix(), evidence


def infer_build_command(package: Package, explicit: str | None, root_package: Package | None = None) -> str | None:
    if explicit:
        return explicit
    scripts = package.manifest.get("scripts", {})
    if not (isinstance(scripts, dict) and isinstance(scripts.get("build"), str)):
        return None
    if root_package and package is not root_package and package.workspace_member:
        workspace = package.manifest.get("name")
        if isinstance(workspace, str) and workspace:
            return f"npm run build --workspace {workspace}"
    if root_package and package is not root_package:
        return f"npm run build --prefix {package.relative}"
    return "npm run build"


def build_command_fact(package: Package, root: Path, command: str | None, explicit: bool) -> dict[str, str] | None:
    if not command:
        return None
    source = "reviewed-override:backendBuildCommand" if explicit else component_evidence(package, root, "scripts.build")
    return resolution_fact("build-command", source, command, "explicit" if explicit else "manifest")


def infer_backend_entry(package: Package, explicit: str | None, root: Path | None = None) -> tuple[str | None, dict[str, str] | None]:
    if explicit:
        value = explicit.replace("\\", "/").removeprefix("./")
        return value, resolution_fact("runtime-entry", "reviewed-override:backendEntry", value, "explicit")
    scripts = package.manifest.get("scripts", {})
    start = scripts.get("start") if isinstance(scripts, dict) else None
    if isinstance(start, str):
        match = re.search(r"(?:^|\s)node\s+(?:--[^\s]+\s+)*([^\s;&|]+)", start)
        if match:
            value = match.group(1).replace("\\", "/").removeprefix("./")
            source = component_evidence(package, root, "scripts.start") if root else "package.json#scripts.start"
            return value, resolution_fact("runtime-entry", source, value, "manifest")
    main = package.manifest.get("main")
    if isinstance(main, str) and main:
        value = main.replace("\\", "/").removeprefix("./")
        source = component_evidence(package, root, "main") if root else "package.json#main"
        return value, resolution_fact("runtime-entry", source, value, "manifest")
    return None, None


def build_script(package: Package) -> str | None:
    scripts = package.manifest.get("scripts", {})
    value = scripts.get("build") if isinstance(scripts, dict) else None
    return value if isinstance(value, str) else None


def static_backend_build_supported(
    package: Package,
    framework: str,
    entry: str | None,
    command: str | None = None,
) -> bool:
    script = command or build_script(package)
    if script is None:
        return True
    normalized = strip_js_comments(script).strip()
    if framework == "nestjs":
        return bool(re.fullmatch(r"(?:npx\s+)?nest\s+build(?:\s+[^;&|]+)*", normalized))
    if framework in {"next", "vinext", "nuxt", "sveltekit"}:
        expected = {"next": "next", "vinext": "vinext", "nuxt": "nuxt", "sveltekit": "vite"}[framework]
        return bool(re.fullmatch(rf"(?:npx\s+)?{expected}\s+build(?:\s+[^;&|]+)*", normalized))
    if re.search(r"(?:^|\s)(?:npx\s+)?tsc(?:\s|$)", normalized):
        return selected_typescript_config(package, framework, normalized) is not None and not any(token in normalized for token in ("&&", "||", ";"))
    entry_is_source = bool(entry) and package.directory.joinpath(*PurePosixPath(entry).parts).is_file()
    return entry_is_source and bool(re.fullmatch(r"(?:npx\s+)?vite\s+build(?:\s+[^;&|]+)*", normalized))


def selected_typescript_config(package: Package, framework: str, build_override: str | None = None) -> Path | None:
    script = build_override if build_override is not None else build_script(package) or ""
    match = re.search(r"(?:^|\s)(?:npx\s+)?tsc(?:\s+[^;&|]*?)?\s(?:-p|--project)(?:\s+|=)([^\s;&|]+)", script)
    if not match:
        match = re.search(r"(?:^|\s)(?:npx\s+)?tsc\s+(?:-b|--build)(?:\s+([^\s;&|]+))?", script)
    if match:
        selected = match.group(1) or "tsconfig.json"
        candidate = package.directory / selected.strip("'\"")
        if candidate.is_dir():
            candidate /= "tsconfig.json"
        elif candidate.suffix != ".json" and not candidate.exists():
            candidate = candidate.with_suffix(".json")
        return candidate
    if framework == "nestjs" and (package.directory / "nest-cli.json").is_file():
        try:
            nest = parse_jsonc((package.directory / "nest-cli.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            nest = {}
        compiler = nest.get("compilerOptions", {}) if isinstance(nest, dict) else {}
        configured = compiler.get("tsConfigPath") if isinstance(compiler, dict) else None
        if isinstance(configured, str) and configured:
            return package.directory / configured
        if (package.directory / "tsconfig.build.json").is_file():
            return package.directory / "tsconfig.build.json"
    path = package.directory / "tsconfig.json"
    return path if path.is_file() else None


def typescript_config_closure(path: Path, root: Path, seen: set[Path] | None = None) -> list[Path]:
    resolved = path.resolve(strict=False)
    seen = seen or set()
    if resolved in seen or not resolved.is_file():
        return []
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return []
    seen.add(resolved)
    try:
        config = parse_jsonc(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [resolved]
    result = [resolved]
    references = config.get("references", []) if isinstance(config, dict) else []
    if isinstance(references, list):
        for reference in references:
            value = reference.get("path") if isinstance(reference, dict) else None
            if not isinstance(value, str) or not value:
                continue
            candidate = (resolved.parent / value).resolve(strict=False)
            if candidate.is_dir():
                candidate /= "tsconfig.json"
            elif candidate.suffix != ".json" and not candidate.exists():
                candidate = candidate.with_suffix(".json")
            result.extend(typescript_config_closure(candidate, root, seen))
    return result


def load_tsconfig_chain(path: Path, root: Path, seen: set[Path] | None = None) -> tuple[dict[str, Any], list[str], Path | None]:
    resolved = path.resolve(strict=False)
    seen = seen or set()
    if resolved in seen or not resolved.is_file() or resolved.stat().st_size > 512 * 1024:
        return {}, [], None
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return {}, [], None
    seen.add(resolved)
    try:
        config = parse_jsonc(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, [relative_to_root(resolved, root)], None
    if not isinstance(config, dict):
        return {}, [relative_to_root(resolved, root)], None
    merged: dict[str, Any] = {}
    evidence: list[str] = []
    origin: Path | None = None
    extends = config.get("extends")
    if isinstance(extends, str) and extends.startswith("."):
        base = (resolved.parent / extends)
        if base.suffix != ".json":
            base = base.with_suffix(".json")
        base_config, base_evidence, origin = load_tsconfig_chain(base, root, seen)
        merged.update(base_config)
        evidence.extend(base_evidence)
    current_options = config.get("compilerOptions", {})
    base_options = merged.get("compilerOptions", {})
    options = dict(base_options) if isinstance(base_options, dict) else {}
    if isinstance(current_options, dict):
        options.update(current_options)
        if isinstance(current_options.get("outDir"), str):
            origin = resolved
    merged.update(config)
    merged["compilerOptions"] = options
    evidence.append(relative_to_root(resolved, root))
    return merged, evidence, origin


def infer_backend_output_path(
    package: Package,
    framework: str,
    root: Path,
    build_override: str | None = None,
    entry: str | None = None,
) -> tuple[str | None, list[str], dict[str, str] | None]:
    """Resolve the outDir from the TypeScript config actually selected by the build command."""
    path = selected_typescript_config(package, framework, build_override)
    if path is None:
        return None, [], None
    candidates: list[tuple[str, Path]] = []
    evidence: list[str] = []
    for config_path in typescript_config_closure(path, root):
        config, current_evidence, origin = load_tsconfig_chain(config_path, root)
        evidence.extend(current_evidence)
        compiler_options = config.get("compilerOptions", {}) if isinstance(config, dict) else {}
        value = compiler_options.get("outDir") if isinstance(compiler_options, dict) else None
        if not isinstance(value, str) or not value.strip() or origin is None:
            continue
        absolute = (origin.parent / value).resolve(strict=False)
        try:
            absolute.relative_to(root.resolve())
        except ValueError:
            continue
        relative_component = os.path.relpath(absolute, package.directory.resolve()).replace(os.sep, "/")
        candidates.append((relative_component, origin))
    unique = {(value, origin) for value, origin in candidates}
    if entry:
        matching = [(value, origin) for value, origin in unique if entry == value or entry.startswith(value.rstrip("/") + "/")]
        if len(matching) == 1:
            unique = set(matching)
    if len(unique) != 1:
        return None, sorted(set(evidence)), None
    relative_component, origin = unique.pop()
    source = f"{relative_to_root(origin, root)}#compilerOptions.outDir"
    return relative_component, sorted(set(evidence)), resolution_fact("output-path", source, relative_component, "configured")


def typescript_build_artifact_paths(package: Package, framework: str, root: Path) -> list[str]:
    selected = selected_typescript_config(package, framework)
    if selected is None:
        return []
    result: set[str] = set()
    for config_path in typescript_config_closure(selected, root):
        config, _, origin = load_tsconfig_chain(config_path, root)
        options = config.get("compilerOptions", {}) if isinstance(config, dict) else {}
        value = options.get("outDir") if isinstance(options, dict) else None
        if not isinstance(value, str) or origin is None:
            continue
        absolute = (origin.parent / value).resolve(strict=False)
        try:
            result.add(relative_to_root(absolute, root))
        except ValueError:
            continue
    return sorted(result)


def _resolve_node_backend(
    package: Package,
    framework: str,
    root: Path,
    findings: list[dict[str, Any]],
    build_command: str | None,
    explicit_entry: str | None,
    explicit_output: str | None,
    explicit_build: bool,
) -> tuple[str | None, str | None, list[str], dict[str, Any]]:
    build_override = build_command if explicit_build else None
    resolver = "nestjs-resolver" if framework == "nestjs" else "typescript-node-resolver" if selected_typescript_config(package, framework, build_override) else f"{framework}-manifest-resolver"
    entry, entry_fact = infer_backend_entry(package, explicit_entry, root)
    entry_is_source = bool(entry) and (package.directory.joinpath(*PurePosixPath(entry).parts)).is_file()
    evidence: list[str] = []
    if explicit_output:
        output = explicit_output.replace("\\", "/").removeprefix("./")
        output_fact = resolution_fact("output-path", "reviewed-override:backendOutputDir", output, "agent-build-verified")
        output_source = "agent-build-verified"
    else:
        output, evidence, output_fact = infer_backend_output_path(package, framework, root, build_override, entry)
        output_source = "build-config" if output_fact else "source-entry"
    if build_command and output is None and not entry_is_source:
        require_explicit_output_configuration(
            findings,
            evidence or [relative_to_root(package.manifest_path, root)],
            framework,
            "dist/cloudbase",
            "configure the build tool actually invoked by scripts.build with one literal output directory and align scripts.start/package main with its emitted server entry. If the build configuration is dynamic or tool-specific, use the Agent build-verification flow instead.",
        )
        output = "dist/cloudbase"
        output_fact = resolution_fact("output-path", "required backend build config", output, "pending-configuration")
        output_source = "pending-agent-configuration"
    if output is None and entry:
        entry_parent = str(PurePosixPath(entry).parent) or "."
        output_fact = resolution_fact("output-path", entry_fact["Source"] if entry_fact else "runtime-entry", entry_parent, "source-entry")
    facts = [fact for fact in (build_command_fact(package, root, build_command, explicit_build), output_fact, entry_fact) if fact is not None]
    return entry, output, evidence, runtime_resolution(
        resolver,
        output_source,
        entry_fact["Method"] if entry_fact else "unresolved",
        facts,
    )


def resolve_nest_backend(
    package: Package,
    root: Path,
    findings: list[dict[str, Any]],
    build_command: str | None,
    explicit_entry: str | None,
    explicit_output: str | None,
    explicit_build: bool,
) -> tuple[str | None, str | None, list[str], dict[str, Any]]:
    return _resolve_node_backend(package, "nestjs", root, findings, build_command, explicit_entry, explicit_output, explicit_build)


def resolve_plain_node_backend(
    package: Package,
    framework: str,
    root: Path,
    findings: list[dict[str, Any]],
    build_command: str | None,
    explicit_entry: str | None,
    explicit_output: str | None,
    explicit_build: bool,
) -> tuple[str | None, str | None, list[str], dict[str, Any]]:
    return _resolve_node_backend(package, framework, root, findings, build_command, explicit_entry, explicit_output, explicit_build)


def scan_workspace_hazards(root: Path, findings: list[dict[str, Any]]) -> None:
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept: list[str] = []
        for name in dirs:
            path = current_path / name
            if path.is_symlink():
                try:
                    path.resolve().relative_to(root)
                except (OSError, ValueError):
                    add_finding(findings, "E_SYMLINK_ESCAPE", "error", "project", [relative_to_root(path, root)], "A directory symlink resolves outside the source root.", "Remove the link or replace it with an in-repository dependency before staging.")
            elif name not in SKIP_DIRS:
                kept.append(name)
        dirs[:] = kept
        for name in names:
            path = current_path / name
            relative = relative_to_root(path, root)
            if path.is_symlink():
                try:
                    path.resolve().relative_to(root)
                except (OSError, ValueError):
                    add_finding(findings, "E_SYMLINK_ESCAPE", "error", "project", [relative], "A file symlink resolves outside the source root.", "Remove the link or copy the required file into the repository before staging.")
                continue
            lowered = name.lower()
            if lowered == ".env" or lowered.startswith(".env.") or lowered in SENSITIVE_NAMES:
                add_finding(findings, "W_SENSITIVE_SOURCE_FILE", "warning", "project", [relative], "A sensitive or environment-specific source file requires explicit exclusion from every upload context.", "Exclude this file from the archive. When runtime source depends on one of its values, follow E_USER_ENVIRONMENT_VARIABLE_UNSUPPORTED: disclose that the value will become plaintext in project source and the ZIP, obtain explicit user authorization, rewrite the reference in the isolated delivery source, and re-detect.")


def inspect_user_environment_accesses(
    sources: list[tuple[Path, str]],
    root: Path,
    unit: str,
    findings: list[dict[str, Any]],
) -> None:
    accesses: dict[str, set[str]] = {}
    for path, raw_text in sources:
        text = iframe_scan_text(path, raw_text)
        matches: list[tuple[str, int]] = []
        recognized_spans: list[tuple[int, int]] = []
        for match in PROCESS_ENV_ACCESS_PATTERN.finditer(text):
            name = match.group("dot") or match.group("bracket")
            matches.append((name, match.start()))
            recognized_spans.append(match.span())
        for match in PROCESS_ENV_DESTRUCTURE_PATTERN.finditer(text):
            recognized_spans.append(match.span())
            for item in match.group("body").split(","):
                name = item.split(":", 1)[0].split("=", 1)[0].strip()
                if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
                    matches.append((name, match.start()))
        for match in PROCESS_ENV_REFERENCE_PATTERN.finditer(text):
            if not any(start <= match.start() < end for start, end in recognized_spans):
                matches.append(("<dynamic process.env access>", match.start()))
        for name, offset in matches:
            if name in MANAGED_RUNTIME_ENV_NAMES:
                continue
            evidence = f"{relative_to_root(path, root)}:{text.count(chr(10), 0, offset) + 1} ({name})"
            accesses.setdefault(name, set()).add(evidence)

    if not accesses:
        return
    names = sorted(accesses)
    evidence = sorted({item for values in accesses.values() for item in values})
    add_finding(
        findings,
        "E_USER_ENVIRONMENT_VARIABLE_UNSUPPORTED",
        "error",
        unit,
        evidence,
        f"Project runtime source reads user-defined or dynamic environment variables that this delivery cannot provide: {', '.join(names)}.",
        "Do not classify the variables as sensitive or non-sensitive. Tell the user that replacing them with project-local literals will place their plaintext values in project source and the ZIP, readable by anyone with access. Ask for explicit authorization to rewrite every reported access. Without clear authorization, remain blocked. After authorization, obtain the intended values without repeating them in the handoff, rewrite only the isolated delivery source, and re-detect from scratch.",
    )


def inspect_backend_sources(
    package: Package,
    root: Path,
    prefixes: list[str],
    fullstack: bool,
    findings: list[dict[str, Any]],
    require_source_port_contract: bool = True,
    source_scope: list[Path] | None = None,
) -> tuple[bool, bool, list[str], list[str]]:
    sources = read_small_sources(package.directory)
    if source_scope is not None:
        allowed = set(source_scope)
        sources = [(path, text) for path, text in sources if path in allowed]
    joined = "\n".join(text for _, text in sources)
    evidence = [relative_to_root(path, root) for path, _ in sources]
    inspect_user_environment_accesses(sources, root, "backend", findings)
    has_sse = bool(re.search(r"text/event-stream|EventSource|\bres\.write\s*\(", joined, re.I))
    has_websocket = bool(re.search(r"\bWebSocket\b|\bws\b|socket\.io|upgrade\s*\(", joined, re.I))
    if has_sse:
        add_finding(findings, "W_SSE_LIMITS", "warning", "backend", evidence[:10], "SSE evidence was found; each connection is constrained by function duration and concurrency.", "Review current timeout, concurrency, and cost limits in the downstream deployment.")
    if has_websocket:
        add_finding(findings, "W_WEBSOCKET_ENABLEMENT", "warning", "backend", evidence[:10], "WebSocket evidence was found and requires downstream protocol enablement.", "Enable WebSocket and configure a suitable timeout after verifying current platform limits.")
    persistent_process_pattern = re.compile(
        r"\bsetInterval\s*\(|node-cron|agenda\s*\(|bull(?:mq)?|new\s+Worker\s*\(",
        re.I,
    )
    persistent_process_evidence = [
        relative_to_root(path, root)
        for path, text in sources
        if persistent_process_pattern.search(text)
    ]
    if persistent_process_evidence:
        add_finding(
            findings,
            "W_PERSISTENT_PROCESS_REVIEW",
            "warning",
            "backend",
            persistent_process_evidence[:10],
            "Timer, worker, scheduler, or queue-consumer syntax was found, but source text alone does not prove that it runs as a resident server task.",
            "Do not rewrite source merely to silence this warning. Review it only when the runtime boundary proves that the matching code is registered from the deployed server startup path.",
        )
    if re.search(r"sqlite|writeFile(?:Sync)?\s*\(|createWriteStream\s*\(", joined, re.I) and "/tmp" not in joined:
        add_finding(findings, "E_LOCAL_PERSISTENCE", "error", "backend", evidence[:10], "Potential persistent local filesystem use was found outside an explicit /tmp path.", "Remove persistent local state. Keep request-scoped or process-scoped state in memory, or deploy the service to a stateful platform.")

    # Unconditional disk-write detection — SCF filesystem is read-only except /tmp.
    # Block any fs write operation regardless of /tmp usage.
    disk_write_patterns = [
        (r"\bfs\.writeFile(?:Sync)?\s*\(", "fs.writeFile"),
        (r"\bfs\.appendFile(?:Sync)?\s*\(", "fs.appendFile"),
        (r"\bfs\.createWriteStream\s*\(", "fs.createWriteStream"),
        (r"\bfs\.write(?:Sync)?\s*\(", "fs.write"),
        (r"\bfs\.mkdir(?:Sync)?\s*\(", "fs.mkdir"),
        (r"\bfs\.rm(?:Sync)?\s*\(", "fs.rm"),
        (r"\bfs\.unlink(?:Sync)?\s*\(", "fs.unlink"),
        (r"\bfs\.rmdir(?:Sync)?\s*\(", "fs.rmdir"),
        (r"\bfs\.rename(?:Sync)?\s*\(", "fs.rename"),
        (r"\bfs\.copyFile(?:Sync)?\s*\(", "fs.copyFile"),
        (r"\bfs\.truncate(?:Sync)?\s*\(", "fs.truncate"),
        (r"\bfs\.chmod(?:Sync)?\s*\(", "fs.chmod"),
        (r"\bfs\.chown(?:Sync)?\s*\(", "fs.chown"),
        (r"\bfs\.link(?:Sync)?\s*\(", "fs.link"),
        (r"\bfs\.symlink(?:Sync)?\s*\(", "fs.symlink"),
        (r"\bfs\.mkdtemp(?:Sync)?\s*\(", "fs.mkdtemp"),
        (r"\bfs\.open\s*\([^)]*['\"][wa]\+?['\"]", "fs.open (write/append mode)"),
        (r"\bfs\.fdatasync(?:Sync)?\s*\(", "fs.fdatasync"),
        (r"\bfs\.utimes(?:Sync)?\s*\(", "fs.utimes"),
        (r"\bmulter\s*\(\s*\{", "multer (disk storage)"),
        (r"\bmulter\.diskStorage\s*\(", "multer.diskStorage"),
    ]
    disk_write_hits: list[str] = []
    for pattern, label in disk_write_patterns:
        if re.search(pattern, joined, re.I):
            disk_write_hits.append(label)
    if disk_write_hits:
        add_finding(
            findings,
            "E_DISK_WRITE_FORBIDDEN",
            "error",
            "backend",
            evidence[:10],
            f"Disk write operations detected: {', '.join(sorted(set(disk_write_hits)))}. SCF 云函数文件系统只读（/tmp 除外），写入操作在运行时必然失败。",
            "Remove all disk write operations. Keep request-scoped or process-scoped state in memory, or deploy the service to a stateful platform. Do not rely on /tmp for durable data.",
        )

    if require_source_port_contract and not re.search(r"process\.env\.PORT|process\.env\[['\"]PORT['\"]\]", joined):
        if re.search(r"\.listen\s*\(\s*\d{4,5}\s*[,)]", joined):
            add_finding(findings, "E_PORT_HARDCODED", "error", "backend", evidence[:10], "The service appears to use a hardcoded port number without reading process.env.PORT.", "Directly update the uniquely identified source listener to use process.env.PORT || 9000 and bind to 0.0.0.0, then re-detect. This delivery-standard edit needs no separate authorization, but must be disclosed at handoff.")
        else:
            add_finding(findings, "E_PORT_CONTRACT_UNSAFE", "error", "backend", evidence[:10], "No process.env.PORT evidence was found for the HTTP service.", "Directly update the uniquely identified source listener to consume process.env.PORT with a 9000 fallback and bind to 0.0.0.0, then re-detect. Disclose the edit at handoff.")
    if require_source_port_contract and re.search(r"\.listen\s*\(\s*[^,\n]+\s*,\s*['\"](?:127\.0\.0\.1|localhost)['\"]", joined):
        add_finding(findings, "E_PORT_CONTRACT_UNSAFE", "error", "backend", evidence[:10], "The service appears to bind only to a loopback address.", "Directly change the uniquely identified source/runtime configuration to bind to 0.0.0.0, then re-detect. This delivery-standard edit needs no separate authorization and must be disclosed at handoff.")

    literal_routes = []
    for path, text in sources:
        for match in re.finditer(r"\bapp\.(?:use|get|post|put|patch|delete|all)\s*\(\s*['\"](/[^'\"]*)['\"]", text):
            literal_routes.append((match.group(1), relative_to_root(path, root)))
        for match in re.finditer(r"\bapp\.(?:use|get|post|put|patch|delete|all)\s*\(\s*\[([^\]]+)\]", text):
            literal_routes.extend((route, relative_to_root(path, root)) for route in re.findall(r"['\"](/[^'\"]*)['\"]", match.group(1)))
        if re.search(r"\b(?:router|app)\s*\[[^\]]+\]|\bapp\.(?:use|get|post|put|patch|delete|all)\s*\(\s*[^'\"\s]", text):
            add_finding(findings, "W_DYNAMIC_ROUTES", "warning", "backend", [relative_to_root(path, root)], "Dynamic route registration prevents a complete static route inventory.", "Treat the detected literal routes as partial and verify deployed routes with smoke tests.")
    all_route_paths: list[str] = sorted({route for route, _ in literal_routes})
    for route, source in literal_routes:
        normalized = route.rstrip("/") or "/"
        if normalized in {"/*", "/{*path}"} or re.fullmatch(r"/\{[^}]*\*[^}]*\}", normalized):
            if fullstack:
                add_finding(findings, "W_BACKEND_FALLBACK_ROUTE", "warning", "backend", [source], f"Catch-all route {route!r} is treated as a frontend/monolith fallback rather than a backend gateway prefix.", "Ensure the split deployment sends only declared backend prefixes to the function and verify SPA fallback at the static host.")
            continue
        if fullstack and not any(normalized == prefix.rstrip("/") or normalized.startswith(prefix.rstrip("/") + "/") for prefix in prefixes):
            add_finding(findings, "W_ROUTE_PREFIX_CONFLICT", "warning", "backend", [source], f"Known backend route {route!r} is outside configured gateway prefixes.", "Add an explicit backendRoutePrefix or move the route under an existing backend prefix.")
    return has_sse, has_websocket, sorted({source for _, source in literal_routes}), all_route_paths


def backend_runtime_packages(packages: list[Package], backend_package: Package) -> list[Package]:
    """Return the backend package plus its production workspace dependency closure."""
    name_to_package = {
        str(package.manifest["name"]): package
        for package in packages
        if isinstance(package.manifest.get("name"), str) and package.manifest.get("name")
    }
    backend_name = backend_package.manifest.get("name")
    if not isinstance(backend_name, str) or backend_name not in name_to_package:
        return [backend_package]

    result: list[Package] = []
    visited: set[str] = set()
    queue = [backend_name]
    while queue:
        name = queue.pop(0)
        if name in visited:
            continue
        package = name_to_package.get(name)
        if package is None:
            continue
        visited.add(name)
        result.append(package)
        for section in ("dependencies", "optionalDependencies"):
            dependencies = package.manifest.get(section, {})
            if isinstance(dependencies, dict):
                queue.extend(
                    dependency
                    for dependency in dependencies
                    if dependency in name_to_package and dependency not in visited
                )
    return result


def inspect_transitive_workspace_protocol(
    runtime_packages: list[Package],
    backend_package: Package,
    all_packages: list[Package],
    root: Path,
    findings: list[dict[str, Any]],
) -> None:
    workspace_names = {
        str(package.manifest["name"])
        for package in all_packages
        if package.workspace_member and isinstance(package.manifest.get("name"), str)
    }
    evidence: list[str] = []
    for package in runtime_packages:
        if package is backend_package:
            continue
        for section in ("dependencies", "optionalDependencies"):
            dependencies = package.manifest.get(section, {})
            if not isinstance(dependencies, dict):
                continue
            if any(name in workspace_names and str(version).startswith("workspace:") for name, version in dependencies.items()):
                evidence.append(relative_to_root(package.manifest_path, root))
    if evidence:
        add_finding(
            findings,
            "E_RUNTIME_WORKSPACE_PROTOCOL_UNSUPPORTED",
            "error",
            "backend",
            evidence,
            "A transitive runtime workspace package contains workspace: dependencies that a root-only overlay cannot rewrite.",
            "Publish/version the transitive package dependency or replace its workspace: range with a reviewed installable range before preparing the source build.",
        )


def is_database_dependency(name: str) -> bool:
    lowered = name.lower()
    return lowered in DATABASE_DEPENDENCIES or any(lowered.startswith(prefix) for prefix in DATABASE_DEPENDENCY_PREFIXES)


def inspect_backend_state_constraints(
    packages: list[Package],
    root: Path,
    findings: list[dict[str, Any]],
    source_scope: list[Path] | None = None,
    scoped_package: Package | None = None,
) -> None:
    """Block database-backed or durable-state backend capabilities before execution."""
    dependency_hits: set[str] = set()
    source_hits: set[str] = set()
    evidence: set[str] = set()

    for package in packages:
        for section in ("dependencies", "optionalDependencies"):
            dependencies = package.manifest.get(section, {})
            if not isinstance(dependencies, dict):
                continue
            matches = {str(name) for name in dependencies if is_database_dependency(str(name))}
            if matches:
                dependency_hits.update(matches)
                evidence.add(relative_to_root(package.manifest_path, root))

        sources = read_small_sources(package.directory)
        if source_scope is not None and scoped_package is not None and package.manifest_path == scoped_package.manifest_path:
            allowed = set(source_scope)
            sources = [(path, text) for path, text in sources if path in allowed]
        for path, text in sources:
            labels = {label for pattern, label in DATABASE_SOURCE_PATTERNS if re.search(pattern, text, re.I)}
            if labels:
                source_hits.update(labels)
                evidence.add(relative_to_root(path, root))

    if dependency_hits or source_hits:
        details: list[str] = []
        if dependency_hits:
            details.append(f"database dependencies: {', '.join(sorted(dependency_hits))}")
        if source_hits:
            details.append(f"database usage evidence: {', '.join(sorted(source_hits))}")
        add_finding(
            findings,
            "E_DATABASE_FORBIDDEN",
            "error",
            "backend",
            sorted(evidence)[:20],
            f"The deployment target only supports in-memory Node.js services; {'; '.join(details)}.",
            "Trace the database evidence to its owning feature and data semantics. Remove it only if unused; otherwise split or move the feature, or use a database-capable platform. Propose memory only after proving the data is non-authoritative and explicitly accepting restart loss, no cross-instance sharing, concurrency changes, and memory bounds.",
        )


def inspect_backend_lock_database_constraints(
    runtime_packages: list[Package],
    all_packages: list[Package],
    root: Path,
    findings: list[dict[str, Any]],
) -> None:
    """Inspect the backend's complete external production dependency closure in package-lock.json."""
    lockfile = root / "package-lock.json"
    if not lockfile.is_file():
        return
    try:
        data = json.loads(lockfile.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    locked_packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(locked_packages, dict):
        return

    workspace_names = {
        str(package.manifest["name"])
        for package in all_packages
        if isinstance(package.manifest.get("name"), str) and package.manifest.get("name")
    }
    queue: list[str] = []
    for package in runtime_packages:
        for section in ("dependencies", "optionalDependencies"):
            dependencies = package.manifest.get(section, {})
            if isinstance(dependencies, dict):
                queue.extend(str(name) for name in dependencies if str(name) not in workspace_names)

    visited: set[str] = set()
    database_hits: set[str] = set()
    while queue:
        dependency = queue.pop(0)
        if dependency in visited:
            continue
        visited.add(dependency)
        if is_database_dependency(dependency):
            database_hits.add(dependency)

        exact_key = f"node_modules/{dependency}"
        candidate_keys = [exact_key] if exact_key in locked_packages else sorted(
            key for key in locked_packages if key.endswith(f"/node_modules/{dependency}")
        )
        for key in candidate_keys:
            metadata = locked_packages.get(key)
            if not isinstance(metadata, dict) or metadata.get("dev") is True:
                continue
            for section in ("dependencies", "optionalDependencies"):
                children = metadata.get(section, {})
                if isinstance(children, dict):
                    queue.extend(str(name) for name in children)

    if database_hits and not any(
        finding["Code"] == "E_DATABASE_FORBIDDEN" and finding["Unit"] == "backend"
        for finding in findings
    ):
        add_finding(
            findings,
            "E_DATABASE_FORBIDDEN",
            "error",
            "backend",
            ["package-lock.json"],
            f"The deployment target only supports in-memory Node.js services; transitive database dependencies: {', '.join(sorted(database_hits))}.",
            "Trace the transitive database package to its owning runtime feature. Remove or replace it only when behavior is understood and preserved; otherwise split or move the feature, or use a database-capable platform. Do not substitute process memory for unknown or durable data.",
        )


def inspect_lock_consistency(root: Path, packages: list[Package], findings: list[dict[str, Any]]) -> None:
    lockfile = root / "package-lock.json"
    if not lockfile.is_file():
        return
    try:
        data = json.loads(lockfile.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        add_finding(findings, "E_LOCKFILE_INCONSISTENT", "error", "project", ["package-lock.json"], "package-lock.json is unreadable or invalid JSON.", "Regenerate the npm lockfile from the reviewed manifests and commit it.")
        return
    locked_packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(locked_packages, dict):
        add_finding(findings, "E_LOCKFILE_INCONSISTENT", "error", "project", ["package-lock.json"], "The lockfile has no inspectable packages map.", "Use a current npm lockfile and verify it with npm ci in an isolated copy.")
        return

    workspace_names = {package.manifest.get("name") for package in packages if isinstance(package.manifest.get("name"), str)}
    for package in packages:
        key = "" if package.relative == "." else package.relative
        locked = locked_packages.get(key)
        manifest_evidence = relative_to_root(package.manifest_path, root)
        if not isinstance(locked, dict):
            add_finding(findings, "E_LOCKFILE_INCONSISTENT", "error", "project", ["package-lock.json", manifest_evidence], f"The lockfile has no package entry for {package.relative!r}.", "Run npm install only in a reviewed maintenance workflow, commit the resulting lockfile, then rerun Detect.")
            continue
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            declared = package.manifest.get(section, {})
            recorded = locked.get(section, {})
            if not isinstance(declared, dict):
                continue
            if not isinstance(recorded, dict):
                recorded = {}
            missing = sorted(set(declared) - set(recorded))
            if missing:
                add_finding(findings, "E_LOCKFILE_INCONSISTENT", "error", "project", ["package-lock.json", manifest_evidence], f"The lockfile package entry omits {section}: {', '.join(missing)}.", "Regenerate and commit package-lock.json from the current manifests, then prove npm ci succeeds in isolation.")
            for dependency in declared:
                dependency_key = f"node_modules/{dependency}"
                if dependency not in workspace_names and dependency_key not in locked_packages:
                    add_finding(findings, "E_LOCKFILE_INCONSISTENT", "error", "project", ["package-lock.json", manifest_evidence], f"The lockfile has no resolved package entry for {dependency!r}.", "Regenerate and commit package-lock.json from the current manifests, then prove npm ci succeeds in isolation.")


def verify_frontend_entry(package: Package, framework: str, findings: list[dict[str, Any]], root: Path) -> None:
    if "vite" not in package.dependencies or framework not in {"vite", "vue", "react"}:
        return
    if (package.directory / "index.html").is_file():
        return
    text, configs = config_text(package, ("vite.config.js", "vite.config.mjs", "vite.config.cjs", "vite.config.ts"))
    if re.search(r"\binput\s*:", text):
        return
    evidence = [relative_to_root(package.manifest_path, root)]
    evidence.extend(f"{package.relative}/{name}" if package.relative != "." else name for name in configs)
    add_finding(findings, "E_FRONTEND_ENTRY_UNRESOLVED", "error", "frontend", evidence, "Vite has neither index.html nor an explicit Rollup input in its inspected configuration.", "Add a valid static build entry or provide the correct frontend directory/configuration.")


def verify_backend_build_candidate(
    package: Package,
    root_package: Package | None,
    framework: str,
    build_command: str | None,
    entry: str | None,
    findings: list[dict[str, Any]],
    root: Path,
    explicit_build: bool = False,
) -> None:
    evidence = [relative_to_root(package.manifest_path, root)]
    scripts = package.manifest.get("scripts", {})
    manifest_build = scripts.get("build") if isinstance(scripts, dict) else None
    inspected_build = build_command if explicit_build else manifest_build
    uses_tsc = isinstance(inspected_build, str) and bool(re.search(r"(?:^|\s|&&)tsc(?:\s|$)", inspected_build))
    if uses_tsc:
        deps = package.dependencies
        if root_package and root_package is not package:
            deps = {**root_package.dependencies, **deps}
        selected = selected_typescript_config(package, framework, inspected_build if explicit_build else None)
        tsconfigs = [selected] if selected else []
        if root_package and root_package is not package and selected is None:
            tsconfigs.append(root_package.directory / "tsconfig.json")
        existing_configs = [path for path in tsconfigs if path.is_file()]
        evidence.extend(relative_to_root(path, root) for path in existing_configs)
        if "typescript" not in deps or not existing_configs:
            add_finding(findings, "E_BUILD_TOOL_UNRESOLVED", "error", "backend", evidence, "The backend build invokes tsc without both a declared TypeScript compiler and an inspectable tsconfig.json.", "Declare TypeScript in the relevant npm build closure and add a reviewed tsconfig.json, or provide a different verified build command.")
    if entry:
        entry_path = package.directory.joinpath(*PurePosixPath(entry).parts)
        if not entry_path.is_file() and build_command is None:
            add_finding(findings, "E_BACKEND_ENTRY_UNRESOLVED", "error", "backend", evidence, f"The backend entry {entry!r} does not exist and no build command is available to create it.", "Provide a valid existing JavaScript entry or a verified build command that produces it.")


def build_workspace_dep_closure(
    packages: list[Package],
    backend_package: Package,
    root: Path,
    findings: list[dict[str, Any]],
    validation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build separate build-time and production-runtime workspace graphs."""
    name_to_pkg = {
        str(pkg.manifest["name"]): pkg
        for pkg in packages
        if isinstance(pkg.manifest.get("name"), str) and pkg.manifest.get("name")
    }
    workspace_names = {name for name, pkg in name_to_pkg.items() if pkg.workspace_member}
    backend_name = backend_package.manifest.get("name")
    if not isinstance(backend_name, str) or backend_name not in name_to_pkg:
        backend_name = f"@component/{backend_package.relative}"
        name_to_pkg[backend_name] = backend_package

    def graph(sections: tuple[str, ...]) -> dict[str, Any]:
        visited: set[str] = set()
        pending = [backend_name]
        while pending:
            current = pending.pop(0)
            if current in visited:
                continue
            visited.add(current)
            pkg = name_to_pkg[current]
            for section in sections:
                deps = pkg.manifest.get(section, {})
                if isinstance(deps, dict):
                    pending.extend(name for name in deps if name in workspace_names and name not in visited)
        edges = sorted({
            (dependency, name)
            for name in visited
            for section in sections
            for dependency in (
                name_to_pkg[name].manifest.get(section, {}).keys()
                if isinstance(name_to_pkg[name].manifest.get(section), dict) else []
            )
            if dependency in visited
        })
        in_degree = {name: 0 for name in visited}
        dependents = {name: [] for name in visited}
        for dependency, dependent in edges:
            dependents[dependency].append(dependent)
            in_degree[dependent] += 1
        ready = sorted(name for name, degree in in_degree.items() if degree == 0)
        order: list[str] = []
        while ready:
            name = ready.pop(0)
            order.append(name)
            for dependent in sorted(dependents[name]):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    ready.append(dependent)
                    ready.sort()
        return {
            "Nodes": sorted(visited),
            "Edges": [{"From": dependency, "To": dependent} for dependency, dependent in edges],
            "Order": order,
            "Cyclic": len(order) != len(visited),
        }

    build_graph = graph(("dependencies", "optionalDependencies", "devDependencies"))
    runtime_graph = graph(("dependencies", "optionalDependencies"))
    root_package = next((package for package in packages if package.relative == "."), None)
    root_script = build_script(root_package) if root_package is not None else None
    validation_steps = validation.get("Steps", []) if isinstance(validation, dict) else []
    validation_builds = [
        step.get("Command") for step in validation_steps
        if isinstance(step, dict) and step.get("Kind") == "build"
    ]
    verified_orchestrator = (
        build_graph["Cyclic"]
        and root_package is not None
        and isinstance(root_script, str)
        and bool(validation_builds)
        and validation_builds[0] == "npm run build"
    )
    if verified_orchestrator:
        build_graph["Orchestrator"] = {
            "Command": "npm run build",
            "Source": component_evidence(root_package, root, "scripts.build"),
            "Verification": "agent-build-verified",
        }
    elif build_graph["Cyclic"]:
        add_finding(
            findings,
            "E_WORKSPACE_BUILD_CYCLE",
            "error",
            "backend",
            [relative_to_root(name_to_pkg[name].manifest_path, root) for name in build_graph["Nodes"]],
            "The npm workspace build graph contains a dependency cycle, so a deterministic package build order cannot be produced.",
            "Use a reviewed root build orchestrator and verify it with Agent build evidence, or remove the workspace dependency cycle, then rerun detection.",
        )

    build_order: list[dict[str, Any]] = []
    packages_info: dict[str, dict[str, Any]] = {}
    recipe: list[dict[str, Any]] = []
    if verified_orchestrator and root_package is not None:
        recipe.append({
            "Kind": "orchestrator",
            "Package": root_package.manifest.get("name") or "@workspace/root",
            "Directory": ".",
            "DeclaredScript": root_script,
            "Execute": "npm run build",
            "Source": component_evidence(root_package, root, "scripts.build"),
            "Produces": [],
        })
    for name in build_graph["Order"]:
        pkg = name_to_pkg[name]
        scripts = pkg.manifest.get("scripts", {})
        declared_script = scripts.get("build") if isinstance(scripts, dict) else None
        if declared_script and pkg.workspace_member:
            build_cmd = f"npm run build --workspace {name}"
        elif declared_script and pkg is not backend_package:
            build_cmd = f"npm run build --prefix {pkg.relative}"
        elif declared_script:
            build_cmd = "npm run build"
        else:
            build_cmd = None
        packages_info[name] = {
            "Directory": pkg.relative,
            "BuildCommand": build_cmd,
        }
        if build_cmd and not verified_orchestrator:
            recipe.append({
                "Kind": "package-build",
                "Package": name,
                "Directory": pkg.relative,
                "DeclaredScript": declared_script,
                "Execute": build_cmd,
                "Source": component_evidence(pkg, root, "scripts.build"),
                "Produces": [],
            })
        if name != backend_name and not verified_orchestrator:
            build_order.append({
                "Name": name,
                "Directory": pkg.relative,
                "BuildCommand": build_cmd,
            })
    return {
        "BuildOrder": build_order,
        "Packages": packages_info,
        "BuildGraph": build_graph,
        "RuntimeGraph": runtime_graph,
        "BuildRecipe": recipe,
    }


def component_path_from_root(root: Path, directory: str, value: str, label: str) -> str:
    if any(character in value for character in "\r\n\x00") or "\\" in value:
        raise ValueError(f"{label} must use POSIX separators without control characters")
    relative = PurePosixPath(value)
    component = PurePosixPath(directory)
    if relative.is_absolute() or component.is_absolute() or not relative.parts or (directory != "." and not component.parts):
        raise ValueError(f"{label} must be component-relative")
    base = root if directory == "." else root.joinpath(*component.parts)
    candidate = base.joinpath(*relative.parts).resolve(strict=False)
    try:
        normalized = candidate.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} escapes the project root") from error
    return normalized.as_posix() or "."


def build_artifact(role: str, path: str, source: str, verification: str) -> dict[str, Any]:
    return {
        "Role": role,
        "Path": path,
        "Required": True,
        "Source": source,
        "Verification": verification,
    }


def attach_component_build_contract(
    component: dict[str, Any],
    package: Package,
    workspace_model: dict[str, Any],
    root: Path,
    validation: dict[str, Any] | None,
) -> None:
    recipe = [dict(step) for step in workspace_model.get("BuildRecipe", []) if isinstance(step, dict)]
    command = component.get("BuildCommand")
    orchestrated = isinstance(workspace_model.get("BuildGraph", {}).get("Orchestrator"), dict)
    if orchestrated:
        component["BuildCommand"] = None
        command = None
        resolution = component.get("RuntimeResolution")
        if isinstance(resolution, dict) and isinstance(resolution.get("Evidence"), list):
            resolution["Evidence"] = [
                fact for fact in resolution["Evidence"]
                if not isinstance(fact, dict) or fact.get("Fact") != "build-command"
            ]
    elif isinstance(command, str):
        own_steps = [index for index, step in enumerate(recipe) if step.get("Directory") == package.relative]
        source = component_evidence(package, root, "scripts.build")
        declared = build_script(package) or command
        replacement = {
            "Kind": "package-build",
            "Package": package.manifest.get("name") or f"@component/{package.relative}",
            "Directory": package.relative,
            "DeclaredScript": declared,
            "Execute": command,
            "Source": source,
            "Produces": [],
        }
        if own_steps:
            recipe[own_steps[-1]] = replacement
        elif not any(step.get("Execute") == command for step in recipe):
            recipe.append(replacement)

    output = component.get("OutputPath")
    next_asset_paths: list[str] = []
    if component.get("Framework") == "next" and recipe and isinstance(output, str):
        package_prefix = PurePosixPath() if package.relative == "." else PurePosixPath(package.relative)
        try:
            component_output = PurePosixPath(output).relative_to(package_prefix)
        except ValueError:
            component_output = PurePosixPath(output)
        dist_dir = component_output.parent
        static_source = (package_prefix / dist_dir / "static").as_posix()
        static_target = (PurePosixPath(output) / dist_dir / "static").as_posix()
        commands = [
            f"mkdir -p {shlex.quote(str(PurePosixPath(static_target).parent))}",
            f"cp -R {shlex.quote(static_source)} {shlex.quote(static_target)}",
        ]
        next_asset_paths.append(static_target)
        public_source = (package.directory / "public")
        if public_source.is_dir():
            public_relative = (package_prefix / "public").as_posix()
            public_target = (PurePosixPath(output) / "public").as_posix()
            commands.append(f"cp -R {shlex.quote(public_relative)} {shlex.quote(public_target)}")
            next_asset_paths.append(public_target)
        recipe.append({
            "Kind": "runtime-prepare",
            "Package": package.manifest.get("name") or f"@component/{package.relative}",
            "Directory": package.relative,
            "DeclaredScript": "Next standalone runtime asset preparation",
            "Execute": " && ".join(commands),
            "Source": "next-standalone-v1#runtime-assets",
            "Produces": next_asset_paths,
        })

    if validation is not None:
        artifacts = [dict(item) for item in validation.get("Artifacts", []) if isinstance(item, dict)]
        verification = "agent-build-verified"
    else:
        artifacts: list[dict[str, Any]] = []
        verification = "static-evidence"
        if recipe and isinstance(output, str):
            resolution = component.get("RuntimeResolution", {})
            source = resolution.get("OutputPathSource", "build-config") if isinstance(resolution, dict) else "build-config"
            artifacts.append(build_artifact("server-runtime", output, str(source), verification))
            if component.get("Framework") in {"node", "express", "koa", "fastify", "hapi", "nestjs"}:
                for path in typescript_build_artifact_paths(package, str(component.get("Framework")), root):
                    if path != output:
                        artifacts.append(build_artifact("server-runtime", path, "typescript-project-reference", verification))
            if component.get("Framework") == "next":
                artifacts.extend(
                    build_artifact("runtime-assets", path, "next-standalone-v1#runtime-assets", verification)
                    for path in next_asset_paths
                )
            elif component.get("Framework") == "vinext":
                artifacts.append(build_artifact("runtime-assets", component_path_from_root(root, package.relative, "dist/client", "vinext assets"), "vinext-standalone-v1", verification))
        elif recipe:
            framework = frontend_framework(package)
            if framework and "vite" in package.dependencies:
                asset_path, asset_evidence = infer_output(package, framework, root)
                if asset_path:
                    source = asset_evidence[0] if asset_evidence else component_evidence(package, root, "scripts.build")
                    artifacts.append(build_artifact("runtime-assets", asset_path, source, verification))

    artifact_paths = [item["Path"] for item in artifacts if isinstance(item.get("Path"), str)]
    for step in recipe:
        if step.get("Kind") == "runtime-prepare":
            step["Produces"] = next_asset_paths
        elif step.get("Directory") == package.relative:
            step["Produces"] = artifact_paths
    if orchestrated:
        for step in recipe:
            if step.get("Kind") == "orchestrator":
                step["Produces"] = artifact_paths
    component["BuildRecipe"] = recipe
    component["BuildArtifacts"] = artifacts
    if validation is not None:
        component["BuildValidation"] = validation


def attach_frontend_build_contract(component: dict[str, Any], package: Package, root: Path) -> None:
    command = component.get("BuildCommand")
    output = component.get("OutputPath")
    if not isinstance(command, str):
        component["BuildRecipe"] = []
        component["BuildArtifacts"] = []
        return
    artifact = build_artifact("runtime-assets", output, component_evidence(package, root, "scripts.build"), "static-evidence") if isinstance(output, str) else None
    component["BuildRecipe"] = [{
        "Kind": "package-build",
        "Package": package.manifest.get("name") or f"@component/{package.relative}",
        "Directory": package.relative,
        "DeclaredScript": build_script(package) or command,
        "Execute": command,
        "Source": component_evidence(package, root, "scripts.build"),
        "Produces": [output] if isinstance(output, str) else [],
    }]
    component["BuildArtifacts"] = [artifact] if artifact else []


def inspect_workspace_recipe_support(
    workspace_model: dict[str, Any],
    packages: list[Package],
    backend_package: Package,
    root: Path,
    findings: list[dict[str, Any]],
    validation: dict[str, Any] | None,
) -> None:
    if validation is not None:
        return
    by_directory = {package.relative: package for package in packages}
    for step in workspace_model.get("BuildRecipe", []):
        if not isinstance(step, dict) or step.get("Directory") == backend_package.relative:
            continue
        package = by_directory.get(step.get("Directory"))
        if package is None or static_backend_build_supported(package, "node", None):
            continue
        require_agent_build_for_tool(findings, package, root, str(step.get("Execute")))


def add_remote_runtime_contract(
    components: list[dict[str, Any]],
    project_type: str,
    root: Path,
    findings: list[dict[str, Any]],
) -> None:
    """Attach the source-build runtime contract only to the Node backend component."""
    for component in components:
        if component.get("Unit") != "backend":
            continue
        directory = component.get("Directory")
        entry = component.get("Entry")
        framework = component.get("Framework")
        if not isinstance(directory, str) or not isinstance(entry, str):
            continue
        raw_output = component.get("OutputPath")
        try:
            if isinstance(raw_output, str):
                component["OutputPath"] = component_path_from_root(root, directory, raw_output, "backend OutputPath")
            runtime_source = (
                (PurePosixPath(raw_output) / PurePosixPath(entry)).as_posix()
                if component.get("DeliveryMode") == "ssr-node" and isinstance(raw_output, str)
                else entry
            )
            runtime_entry = component_path_from_root(root, directory, runtime_source, "backend RuntimeEntry")
        except ValueError as error:
            add_finding(
                findings,
                "E_BACKEND_OUTPUT_UNRESOLVED",
                "error",
                "backend",
                component.get("Evidence", [])[:10] if isinstance(component.get("Evidence"), list) else [],
                str(error),
                "Make tsconfig outDir and the production start/main entry resolve to paths inside the project root, then rerun detection.",
            )
            continue
        output = component.get("OutputPath")
        if (
            isinstance(output, str)
            and component.get("BuildCommand")
            and runtime_entry != output
            and not runtime_entry.startswith(output.rstrip("/") + "/")
        ):
            add_finding(
                findings,
                "E_BACKEND_OUTPUT_UNRESOLVED",
                "error",
                "backend",
                component.get("Evidence", [])[:10] if isinstance(component.get("Evidence"), list) else [],
                f"Runtime entry {runtime_entry!r} is outside configured build output {output!r}.",
                "Align tsconfig outDir with the production start/main entry, or provide reviewed matching build and entry overrides, then rerun detection.",
            )
        component["RuntimeManifestMode"] = (
            "root" if directory == "." and project_type in {"backend-http", "ssr-node"} else "overlay"
        )
        component["RuntimeEntry"] = runtime_entry
        component["RuntimePackagePath"] = "package.json" if directory == "." else f"{directory}/package.json"
        resolution = component.get("RuntimeResolution")
        facts = resolution.get("Evidence", []) if isinstance(resolution, dict) else []
        for fact in facts if isinstance(facts, list) else []:
            if not isinstance(fact, dict):
                continue
            if fact.get("Fact") == "runtime-entry":
                fact["Value"] = runtime_entry
            elif fact.get("Fact") == "output-path" and isinstance(component.get("OutputPath"), str):
                fact["Value"] = component["OutputPath"]
        entry_facts = [
            fact for fact in facts
            if isinstance(fact, dict) and fact.get("Fact") == "runtime-entry"
        ]
        entry_source = (
            entry_facts[0].get("Source")
            if len(entry_facts) == 1 and isinstance(entry_facts[0].get("Source"), str)
            else "RuntimeEntry"
        )
        framework_contract_value = resolution.get("FrameworkContract") if isinstance(resolution, dict) else None
        framework_launch_kind = (
            framework_contract_value.get("LaunchKind")
            if isinstance(framework_contract_value, dict)
            else None
        )
        if component["RuntimeManifestMode"] == "overlay":
            component["RuntimeLaunch"] = {
                "Kind": "npm-script",
                "Script": "start",
                "Source": "_tmp/backend.runtime.package.json#scripts.start",
            }
        elif component.get("DeliveryMode") == "ssr-node" and framework_launch_kind == "node-entry":
            component["RuntimeLaunch"] = {
                "Kind": "node-entry",
                "Entry": runtime_entry,
                "Source": entry_source,
            }
        else:
            manifest = load_manifest(root / component["RuntimePackagePath"])
            scripts = manifest.get("scripts", {})
            start = scripts.get("start") if isinstance(scripts, dict) else None
            if component.get("DeliveryMode") == "ssr-node" and framework_launch_kind != "npm-script":
                raise SystemExit(
                    f"error: framework contract for {framework!r} must declare LaunchKind"
                )
            component["RuntimeLaunch"] = (
                {
                    "Kind": "npm-script",
                    "Script": "start",
                    "Source": f"{component['RuntimePackagePath']}#scripts.start",
                }
                if isinstance(start, str) and start.strip()
                else {
                    "Kind": "node-entry",
                    "Entry": runtime_entry,
                    "Source": entry_source,
                }
            )


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    output = args.output.resolve(strict=False)
    if not root.is_dir():
        raise SystemExit(f"error: root is not a directory: {root}")
    build_validation = load_build_validation(args.build_validation, root)

    findings: list[dict[str, Any]] = []
    packages = discover_packages(root)
    build_free_static = inspect_build_free_static(root, findings) if not packages else None
    if not packages and build_free_static is None and not any(item["Code"] == "E_STATIC_TREE_UNSAFE" for item in findings):
        add_finding(findings, "E_PROJECT_AMBIGUOUS", "error", "project", [], "No package.json was found at the project root.", "Provide a Node.js project root or prepare a build-free static directory through an explicit workflow.")
    package_manager = {"Name": "none", "Lockfile": None} if build_free_static else detect_package_manager(root, findings)
    scan_workspace_hazards(root, findings)
    if package_manager["Name"] == "npm":
        inspect_lock_consistency(root, packages, findings)

    root_package = next((package for package in packages if package.directory == root), None)
    frontend_package: Package | None = None
    backend_package: Package | None = None
    if args.frontend_dir:
        frontend_package = package_for_dir(packages, normalize_component_dir(args.frontend_dir, root), root)
    if args.backend_dir:
        backend_package = package_for_dir(packages, normalize_component_dir(args.backend_dir, root), root)
    if not args.frontend_dir:
        frontend_package = next((package for package in packages if frontend_framework(package)), None)
    if not args.backend_dir:
        backend_candidates = [package for package in packages if node_http_candidate(package)]
        if len(backend_candidates) == 1:
            backend_package = backend_candidates[0]
        elif len(backend_candidates) > 1:
            add_finding(
                findings,
                "E_MULTIPLE_BACKEND_CANDIDATES",
                "error",
                "project",
                [relative_to_root(package.manifest_path, root) for package in backend_candidates],
                "Multiple entry-bearing Node HTTP services were found, so automatic backend selection is not unique.",
                "Rerun detection with --backend-dir naming the intended service. Do not select a backend by dependency order or score.",
            )
    monolith = (
        frontend_package is not None
        and frontend_package is backend_package
        and server_serves_frontend(frontend_package)
    )
    components: list[dict[str, Any]] = [build_free_static] if build_free_static else []
    ssr_package: Package | None = None
    if frontend_package and not monolith:
        framework = frontend_framework(frontend_package)
        if framework is None:
            add_finding(findings, "E_PROJECT_AMBIGUOUS", "error", "frontend", [relative_to_root(frontend_package.manifest_path, root)], "The explicit frontend package has no recognized static frontend framework.", "Provide verified build/output settings and establish that the output is purely static.")
            framework = "unknown"
        web_mode, evidence, ssr_profile = classify_web_candidate(
            frontend_package,
            framework,
            findings,
            root,
            args.backend_entry,
            args.backend_output_dir,
        ) if framework != "unknown" else ("static", [relative_to_root(frontend_package.manifest_path, root)], None)
        node_major, node_evidence = infer_node_major(frontend_package, root_package, args.frontend_node_version)
        evidence.extend(node_evidence)
        if node_major is None:
            add_finding(findings, "W_NODE_VERSION_FALLBACK", "warning", "backend" if web_mode == "ssr" else "frontend", [relative_to_root(frontend_package.manifest_path, root)], "No single Node major could be normalized.", "Select an explicitly supported CloudBase build/runtime Node major before execution.")
            node_major = "20"
        if web_mode == "ssr" and ssr_profile is not None:
            ssr_package = frontend_package
            ssr_build_command = infer_build_command(frontend_package, args.backend_build_command or args.frontend_build_command, root_package)
            if (
                isinstance(ssr_build_command, str)
                and build_validation is None
                and not static_backend_build_supported(
                    frontend_package,
                    framework,
                    ssr_profile.get("Entry"),
                    ssr_build_command if (args.backend_build_command or args.frontend_build_command) else None,
                )
            ):
                require_agent_build_for_tool(findings, frontend_package, root, ssr_build_command)
            build_fact = build_command_fact(
                frontend_package,
                root,
                ssr_build_command,
                bool(args.backend_build_command or args.frontend_build_command),
            )
            if build_fact:
                ssr_profile["RuntimeResolution"]["Evidence"].insert(0, build_fact)
            contract = framework_contract(framework, frontend_package, root, findings, build_validation, evidence)
            if contract:
                ssr_profile["RuntimeResolution"]["FrameworkContract"] = contract
            component = {
                "Unit": "backend",
                "Directory": frontend_package.relative,
                "Framework": framework,
                "NodeVersion": node_major,
                "BuildCommand": ssr_build_command,
                "OutputPath": ssr_profile["OutputPath"],
                "Entry": ssr_profile["Entry"],
                "Routes": ["/*"],
                "Evidence": sorted(set(evidence)),
                **ssr_profile,
            }
            components.append(component)
        else:
            verify_frontend_entry(frontend_package, framework, findings, root)
            build_command = infer_build_command(frontend_package, args.frontend_build_command, root_package)
            if (
                build_command
                and frontend_package.directory != root
                and not frontend_package.workspace_member
                and not (frontend_package.directory / "package-lock.json").is_file()
            ):
                add_finding(
                    findings,
                    "E_LOCKFILE_MISSING",
                    "error",
                    "frontend",
                    [relative_to_root(frontend_package.manifest_path, root)],
                    "The non-workspace frontend requires a build but has no component package-lock.json.",
                    "Commit the frontend component's npm package-lock.json so the remote build can run npm ci --prefix on that directory.",
                )
            if args.frontend_output_dir:
                explicit_output = PurePosixPath(args.frontend_output_dir.replace("\\", "/"))
                if explicit_output.is_absolute() or ".." in explicit_output.parts or not explicit_output.parts:
                    raise SystemExit("error: frontend output directory must be a safe component-relative path")
                component_prefix = PurePosixPath() if frontend_package.relative == "." else PurePosixPath(frontend_package.relative)
                output_path = (component_prefix / explicit_output).as_posix()
                output_evidence: list[str] = []
            else:
                output_path, output_evidence = infer_output(frontend_package, framework, root)
            evidence.extend(output_evidence)
            if build_command is None:
                add_finding(
                    findings,
                    "E_BUILD_TOOL_UNRESOLVED",
                    "error",
                    "frontend",
                    [relative_to_root(frontend_package.manifest_path, root)],
                    "No frontend build command could be resolved from an explicit override or package scripts.build.",
                    "Define a reviewed scripts.build command or provide frontendBuildCommand, then rerun detection.",
                )
            if output_path is None:
                add_finding(
                    findings,
                    "E_FRONTEND_OUTPUT_UNRESOLVED",
                    "error",
                    "frontend",
                    [relative_to_root(frontend_package.manifest_path, root)],
                    "No static frontend output directory could be resolved.",
                    "Provide frontendOutputDir or configure a recognized framework output path, then rerun detection.",
                )
            frontend_component = {
                "Unit": "frontend",
                "Directory": frontend_package.relative,
                "Framework": framework,
                "NodeVersion": node_major,
                "BuildCommand": build_command,
                "OutputPath": output_path,
                "Entry": None,
                "Evidence": sorted(set(evidence)),
            }
            attach_frontend_build_contract(frontend_component, frontend_package, root)
            components.append(frontend_component)

    if backend_package and backend_package is not ssr_package:
        framework = backend_framework(backend_package) or "node"
        node_major, node_evidence = infer_node_major(backend_package, root_package, args.backend_node_version)
        evidence = [relative_to_root(backend_package.manifest_path, root), *node_evidence]
        if node_major is None:
            add_finding(findings, "W_NODE_VERSION_FALLBACK", "warning", "backend", [relative_to_root(backend_package.manifest_path, root)], "No single backend Node major could be normalized.", "Select a current CloudBase function Node major and replay validation in that runtime.")
            node_major = "20"
        build_command = infer_build_command(backend_package, args.backend_build_command, root_package)
        if framework == "nestjs":
            entry, output_path, output_evidence, resolution = resolve_nest_backend(
                backend_package, root, findings, build_command, args.backend_entry, args.backend_output_dir, bool(args.backend_build_command)
            )
        else:
            entry, output_path, output_evidence, resolution = resolve_plain_node_backend(
                backend_package, framework, root, findings, build_command, args.backend_entry, args.backend_output_dir, bool(args.backend_build_command)
            )
        if framework == "nestjs":
            contract = framework_contract(framework, backend_package, root, findings, build_validation, evidence)
            if contract:
                resolution["FrameworkContract"] = contract
        if not entry:
            add_finding(findings, "E_BACKEND_ENTRY_UNRESOLVED", "error", "backend", [relative_to_root(backend_package.manifest_path, root)], "No built backend entry could be resolved.", "Provide backendEntry or define an unambiguous production start/main entry.")
        if (
            isinstance(build_command, str)
            and build_validation is None
            and not static_backend_build_supported(
                backend_package,
                framework,
                entry,
                build_command if args.backend_build_command else None,
            )
        ):
            require_agent_build_for_tool(findings, backend_package, root, build_command)
        evidence.extend(output_evidence)
        if (
            build_command
            and backend_package.directory != root
            and not backend_package.workspace_member
            and not (backend_package.directory / "package-lock.json").is_file()
        ):
            add_finding(
                findings,
                "E_LOCKFILE_MISSING",
                "error",
                "backend",
                [relative_to_root(backend_package.manifest_path, root)],
                "The non-workspace backend requires a build but has no component package-lock.json.",
                "Commit the backend component's npm package-lock.json so the remote build can run npm ci --prefix on that directory.",
            )
        verify_backend_build_candidate(
            backend_package,
            root_package,
            framework,
            build_command,
            entry,
            findings,
            root,
            explicit_build=bool(args.backend_build_command),
        )
        components.append({
            "Unit": "backend",
            "Directory": backend_package.relative,
            "Framework": framework,
            "NodeVersion": node_major,
            "BuildCommand": build_command,
            "OutputPath": output_path,
            "Entry": entry,
            "DeliveryMode": "node-http",
            "RuntimeResolution": resolution,
            "Evidence": sorted(set(evidence)),
        })

    runtime_candidates: list[tuple[Package, bool]] = []
    if ssr_package:
        runtime_candidates.append((ssr_package, True))
    if backend_package and backend_package is not ssr_package:
        runtime_candidates.append((backend_package, False))
    if len(runtime_candidates) > 1:
        add_finding(
            findings,
            "E_MULTIPLE_BACKEND_UNITS",
            "error",
            "project",
            [relative_to_root(package.manifest_path, root) for package, _ in runtime_candidates],
            "The project contains SSR and a separate Node backend, but the current delivery contract supports one CloudBase function runtime.",
            "Combine the HTTP units behind one reviewed Node entry, or deploy them as separate services with an explicit routing design.",
        )

    for component in components:
        if component.get("Unit") == "backend":
            attach_cloud_function_runtime(
                component,
                args.backend_cloud_function_node_version,
                findings,
            )

    has_frontend = any(component["Unit"] == "frontend" for component in components)
    has_backend = any(component["Unit"] == "backend" for component in components)
    project_type = "unsupported"
    has_ssr = any(component.get("DeliveryMode") == "ssr-node" for component in components)
    if has_ssr and not has_frontend:
        project_type = "ssr-node"
    elif has_frontend and has_backend:
        project_type = "fullstack-split"
    elif has_frontend:
        project_type = "frontend-static"
    elif has_backend:
        project_type = "backend-http"
    else:
        add_finding(findings, "E_PROJECT_AMBIGUOUS", "error", "project", [relative_to_root(package.manifest_path, root) for package in packages], "No supported static frontend or Node.js HTTP backend candidate was recognized.", "Provide explicit component directories and build/runtime settings, or use another deployment target.")

    if project_type == "fullstack-split" and frontend_package is not None and frontend_package is backend_package:
        add_finding(
            findings,
            "E_RUNTIME_DEPENDENCY_CLOSURE_UNRESOLVED",
            "error",
            "backend",
            [relative_to_root(frontend_package.manifest_path, root)],
            "The frontend and backend share one package manifest, so a backend-only production dependency closure cannot be proven.",
            "Split the backend into its own npm package/workspace, or provide a reviewed backend package boundary before generating an overlay runtime manifest.",
        )

    inspect_iframe_embedding_constraints(
        root,
        [
            (package, server_source_files(package) if monolith else None)
            for package, _ in runtime_candidates
        ],
        findings,
    )

    prefixes = args.backend_route_prefixes or (["/api"] if project_type == "fullstack-split" else ["/*"] if project_type in {"backend-http", "ssr-node"} else [])
    normalized_prefixes: list[str] = []
    for prefix in prefixes:
        if not prefix.startswith("/"):
            raise SystemExit(f"error: backend route prefix must start with '/': {prefix}")
        normalized_prefixes.append(prefix.rstrip("*").rstrip("/") or "/")
    has_sse = False
    has_websocket = False
    backend_routes: list[str] = []
    workspace_deps: dict[str, Any] = {"BuildOrder": [], "Packages": {}}
    if runtime_candidates:
        route_evidence: list[str] = []
        for runtime_package, is_ssr in runtime_candidates:
            backend_source_scope = server_source_files(runtime_package) if monolith else None
            candidate_sse, candidate_websocket, candidate_evidence, candidate_routes = inspect_backend_sources(
                runtime_package,
                root,
                normalized_prefixes,
                project_type == "fullstack-split",
                findings,
                require_source_port_contract=not is_ssr,
                source_scope=backend_source_scope,
            )
            has_sse = has_sse or candidate_sse
            has_websocket = has_websocket or candidate_websocket
            route_evidence.extend(candidate_evidence)
            backend_routes.extend(candidate_routes)
            runtime_packages = backend_runtime_packages(packages, runtime_package)
            for dependency_package in runtime_packages:
                if dependency_package is runtime_package:
                    continue
                inspect_user_environment_accesses(
                    read_small_sources(dependency_package.directory),
                    root,
                    "backend",
                    findings,
                )
            inspect_transitive_workspace_protocol(runtime_packages, runtime_package, packages, root, findings)
            inspect_backend_state_constraints(
                runtime_packages,
                root,
                findings,
                source_scope=backend_source_scope,
                scoped_package=runtime_package if monolith else None,
            )
            inspect_backend_lock_database_constraints(runtime_packages, packages, root, findings)
        for component in components:
            if component["Unit"] == "backend":
                component["Evidence"] = sorted(set(component["Evidence"] + route_evidence))
                if component.get("DeliveryMode") != "ssr-node":
                    component["Routes"] = ["/*"] if monolith else sorted(set(backend_routes))
        if not args.health_check_path:
            add_finding(findings, "W_HEALTHCHECK_ABSENT", "warning", "backend", [], "The detector cannot infer whether a business health endpoint exists.", "Supply healthCheckPath only when the application already implements it; otherwise perform a startup probe.")

    add_remote_runtime_contract(components, project_type, root, findings)

    workspace_graphs: dict[str, Any] | None = None
    if runtime_candidates:
        workspace_model = build_workspace_dep_closure(packages, runtime_candidates[0][0], root, findings, build_validation)
        inspect_workspace_recipe_support(
            workspace_model,
            packages,
            runtime_candidates[0][0],
            root,
            findings,
            build_validation,
        )
        workspace_deps = {
            "BuildOrder": workspace_model["BuildOrder"],
            "Packages": workspace_model["Packages"],
        }
        workspace_graphs = {
            "BuildGraph": workspace_model["BuildGraph"],
            "RuntimeGraph": workspace_model["RuntimeGraph"],
        }
        for component in components:
            if component.get("Unit") == "backend":
                attach_component_build_contract(component, runtime_candidates[0][0], workspace_model, root, build_validation)
                validation_mismatch = False
                if build_validation is not None:
                    actual_builds = [
                        step.get("Command") for step in build_validation.get("Steps", [])
                        if isinstance(step, dict) and step.get("Kind") == "build"
                    ]
                    expected_builds = [
                        step.get("Execute") for step in component.get("BuildRecipe", [])
                        if isinstance(step, dict)
                    ]
                    produced_paths = {
                        path
                        for step in component.get("BuildRecipe", [])
                        if isinstance(step, dict) and isinstance(step.get("Produces"), list)
                        for path in step["Produces"]
                        if isinstance(path, str)
                    }
                    artifact_paths = {
                        artifact.get("Path")
                        for artifact in component.get("BuildArtifacts", [])
                        if isinstance(artifact, dict) and isinstance(artifact.get("Path"), str)
                    }
                    validation_mismatch = (
                        build_validation.get("RuntimeEntry") != component.get("RuntimeEntry")
                        or actual_builds != expected_builds
                        or build_validation.get("Artifacts") != component.get("BuildArtifacts")
                        or produced_paths != artifact_paths
                    )
                if validation_mismatch:
                    add_finding(
                        findings,
                        "E_AGENT_BUILD_EVIDENCE_MISMATCH",
                        "error",
                        "backend",
                        [str(args.build_validation)] if args.build_validation else [],
                        "BuildValidation commands, artifacts, or RuntimeEntry do not match the normalized BuildRecipe and backend runtime contract.",
                        "Regenerate validation evidence from the same ordered recipe, output and entry values, then rerun detection.",
                    )
                if build_validation is not None and (args.backend_output_dir or args.backend_entry):
                    probes = [
                        step for step in build_validation.get("Steps", [])
                        if isinstance(step, dict) and step.get("Kind") == "start-probe"
                    ]
                    if len(probes) != 1 or str(component.get("RuntimeEntry")) not in str(probes[0].get("Command", "")):
                        add_finding(
                            findings,
                            "E_AGENT_BUILD_EVIDENCE_MISMATCH",
                            "error",
                            "backend",
                            [str(args.build_validation)] if args.build_validation else [],
                            "A dynamic output/entry override requires one HTTP start probe of the normalized RuntimeEntry.",
                            "Probe the exact RuntimeEntry on 0.0.0.0:9000 for at most 30 seconds, record the HTTP result, and rerun detection.",
                        )
        if (args.backend_output_dir or args.backend_entry) and build_validation is None:
            add_finding(
                findings,
                "E_AGENT_BUILD_EVIDENCE_REQUIRED",
                "error",
                "backend",
                [relative_to_root(runtime_candidates[0][0].manifest_path, root)],
                "Agent-verified output or entry overrides were supplied without structured build evidence.",
                "Run install/build and the conditional 30-second HTTP start probe, record the successful commands and fresh artifacts in BuildValidation, then rerun with --build-validation.",
            )

    findings.sort(key=lambda item: (0 if item["Severity"] == "error" else 1, item["Code"], item["Unit"], item["Evidence"]))
    status = "blocked" if any(item["Severity"] == "error" for item in findings) else "review-required"
    plan = {
        "SchemaVersion": "tcb.deploy/v1alpha1",
        "Kind": "deploy-plan",
        "Status": status,
        "ProjectType": project_type,
        "PackageManager": package_manager,
        "Components": components,
        "Routes": {"BackendPrefixes": normalized_prefixes, "PreservePath": True},
        "Capabilities": {"SSE": has_sse, "WebSocket": has_websocket},
        "Findings": findings,
    }
    if has_backend:
        plan["WorkspaceDeps"] = workspace_deps
        plan["WorkspaceGraphs"] = workspace_graphs
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(output)
    return 1 if status == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
