#!/usr/bin/env python3
"""Validate CloudBase source-build plans, descriptors, and Agent-generated inputs."""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from cloudbase_runtime import cloudbaserc_descriptor, validate_cloud_function_runtime
from delivery_paths import delivery_directory_name
from skill_config import DEPLOY_SCHEMA_VERSION
from write_backend_runtime import bootstrap_start_script, helper_source, runtime_manifest
from write_deploy_descriptors import backend_descriptor, frontend_descriptor
from write_scf_bootstrap import bootstrap_content


def load_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(f"{path.name}: invalid JSON: {error}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{path.name}: top level must be an object")
        return None
    return value


def resolve_ref(root: dict[str, Any], reference: str) -> dict[str, Any]:
    current: Any = root
    for token in reference[2:].split("/"):
        current = current[token.replace("~1", "/").replace("~0", "~")]
    return current


def schema_errors(instance: Any, schema: dict[str, Any], root: dict[str, Any], location: str = "$") -> list[str]:
    errors: list[str] = []
    if "$ref" in schema:
        return schema_errors(instance, resolve_ref(root, schema["$ref"]), root, location)
    for subschema in schema.get("allOf", []):
        errors.extend(schema_errors(instance, subschema, root, location))
    if "if" in schema:
        branch = "then" if not schema_errors(instance, schema["if"], root, location) else "else"
        if branch in schema:
            errors.extend(schema_errors(instance, schema[branch], root, location))
    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        checks = {
            "null": lambda value: value is None,
            "object": lambda value: isinstance(value, dict),
            "array": lambda value: isinstance(value, list),
            "string": lambda value: isinstance(value, str),
            "boolean": lambda value: isinstance(value, bool),
            "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
            "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
        }
        if not any(checks[name](instance) for name in names):
            return [*errors, f"{location}: expected {' or '.join(names)}"]
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{location}: expected constant {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{location}: expected one of {schema['enum']!r}")
    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{location}: missing required property {key!r}")
        if schema.get("additionalProperties") is False:
            for key in instance.keys() - properties.keys():
                errors.append(f"{location}: unexpected property {key!r}")
        for key, value in instance.items():
            if key in properties:
                errors.extend(schema_errors(value, properties[key], root, f"{location}.{key}"))
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errors.append(f"{location}: too few items")
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in instance}) != len(instance):
            errors.append(f"{location}: items must be unique")
        if "items" in schema:
            for index, value in enumerate(instance):
                errors.extend(schema_errors(value, schema["items"], root, f"{location}[{index}]"))
    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            errors.append(f"{location}: string is too short")
        if schema.get("pattern") and re.search(schema["pattern"], instance) is None:
            errors.append(f"{location}: does not match {schema['pattern']!r}")
    if "not" in schema and not schema_errors(instance, schema["not"], root, location):
        errors.append(f"{location}: matches forbidden schema")
    return errors


def validate_schema(document: dict[str, Any], path: Path, label: str, errors: list[str]) -> None:
    schema = json.loads(path.read_text(encoding="utf-8"))
    errors.extend(f"{label}: {message}" for message in schema_errors(document, schema, schema))


def safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    pure = PurePosixPath(value)
    return not pure.is_absolute() and bool(pure.parts) and not any(part in ("", ".", "..") for part in pure.parts)


def backend_component(plan: dict[str, Any], errors: list[str]) -> dict[str, Any] | None:
    components = [item for item in plan.get("Components", []) if isinstance(item, dict) and item.get("Unit") == "backend"]
    if len(components) > 1:
        errors.append("deploy-plan.json: more than one backend component")
    return components[0] if len(components) == 1 else None


def validate_plan_semantics(plan: dict[str, Any], errors: list[str]) -> None:
    backend = backend_component(plan, errors)
    findings = [item for item in plan.get("Findings", []) if isinstance(item, dict)]
    error_findings = [(index, item) for index, item in enumerate(findings) if item.get("Severity") == "error"]
    if plan.get("Status") == "blocked" and not error_findings:
        errors.append("deploy-plan.json: blocked status requires at least one error finding with basis and remediation")
    if plan.get("Status") != "blocked" and error_findings:
        errors.append("deploy-plan.json: every error finding requires blocked status")
    for index, finding in error_findings:
        evidence = finding.get("Evidence")
        if not isinstance(evidence, list) or not evidence or any(not isinstance(item, str) or not item.strip() for item in evidence):
            errors.append(f"deploy-plan.json: $.Findings[{index}] error requires non-empty Evidence")
        if not isinstance(finding.get("Reason"), str) or not finding["Reason"].strip():
            errors.append(f"deploy-plan.json: $.Findings[{index}] error requires a blocking Reason")
        if not isinstance(finding.get("Remediation"), str) or not finding["Remediation"].strip():
            errors.append(f"deploy-plan.json: $.Findings[{index}] error requires actionable Remediation")
    for index, component in enumerate(plan.get("Components", [])):
        if not isinstance(component, dict):
            continue
        runtime_keys = ("RuntimeManifestMode", "RuntimeEntry", "RuntimePackagePath", "RuntimeLaunch", "RuntimeResolution")
        frontend_runtime_keys = (*runtime_keys, "CloudFunctionRuntime")
        if component.get("Unit") == "frontend":
            for key in frontend_runtime_keys:
                if key in component:
                    errors.append(f"deploy-plan.json: frontend component must not contain {key}")
        elif component.get("Unit") == "backend":
            node_version = component.get("NodeVersion")
            if not isinstance(node_version, str) or not node_version.isdigit():
                errors.append(f"deploy-plan.json: $.Components[{index}].NodeVersion must be a detected Node major")
            cloud_function_value = component.get("CloudFunctionRuntime")
            runtime_unavailable = any(
                finding.get("Code") == "E_CLOUDBASERC_RUNTIME_UNSUPPORTED"
                and finding.get("Severity") == "error"
                for finding in findings
            )
            if cloud_function_value is None and plan.get("Status") == "blocked" and runtime_unavailable:
                pass
            else:
                try:
                    validate_cloud_function_runtime(node_version, cloud_function_value)
                except ValueError as error:
                    errors.append(f"deploy-plan.json: $.Components[{index}].CloudFunctionRuntime: {error}")
            for key in runtime_keys:
                if key not in component:
                    errors.append(f"deploy-plan.json: $.Components[{index}] is missing {key}")
            if component.get("RuntimeManifestMode") not in {"root", "overlay"}:
                errors.append(f"deploy-plan.json: $.Components[{index}].RuntimeManifestMode must be root or overlay")
            for key in ("RuntimeEntry", "RuntimePackagePath"):
                if not safe_relative(component.get(key)):
                    errors.append(f"deploy-plan.json: $.Components[{index}].{key} must be a safe relative path")
            launch = component.get("RuntimeLaunch")
            resolution = component.get("RuntimeResolution")
            framework_contract = resolution.get("FrameworkContract") if isinstance(resolution, dict) else None
            framework_launch_kind = (
                framework_contract.get("LaunchKind")
                if isinstance(framework_contract, dict)
                else None
            )
            if not isinstance(launch, dict):
                errors.append(f"deploy-plan.json: $.Components[{index}].RuntimeLaunch must select a launch strategy")
            elif launch.get("Kind") == "node-entry":
                if launch.get("Entry") != component.get("RuntimeEntry"):
                    errors.append(f"deploy-plan.json: $.Components[{index}].RuntimeLaunch.Entry must match RuntimeEntry")
                if component.get("RuntimeManifestMode") == "overlay":
                    errors.append(f"deploy-plan.json: $.Components[{index}] overlay runtime must launch its generated npm start script")
            elif launch.get("Kind") == "npm-script":
                script = launch.get("Script")
                if not isinstance(script, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", script) is None:
                    errors.append(f"deploy-plan.json: $.Components[{index}].RuntimeLaunch.Script must be a safe npm script name")
                if component.get("RuntimeManifestMode") == "overlay" and script != "start":
                    errors.append(f"deploy-plan.json: $.Components[{index}] overlay runtime must use its generated start script")
            else:
                errors.append(f"deploy-plan.json: $.Components[{index}].RuntimeLaunch.Kind must be node-entry or npm-script")
            if (
                component.get("DeliveryMode") == "ssr-node"
                and component.get("RuntimeManifestMode") == "root"
                and isinstance(launch, dict)
                and launch.get("Kind") != framework_launch_kind
            ):
                errors.append(f"deploy-plan.json: $.Components[{index}].RuntimeLaunch.Kind must match FrameworkContract.LaunchKind")
            output = component.get("OutputPath")
            if isinstance(output, str) and output != "." and not safe_relative(output):
                errors.append(f"deploy-plan.json: $.Components[{index}].OutputPath must be project-root-relative")
            recipe = component.get("BuildRecipe")
            artifacts = component.get("BuildArtifacts")
            if not isinstance(recipe, list) or not isinstance(artifacts, list):
                errors.append(f"deploy-plan.json: $.Components[{index}] requires BuildRecipe and BuildArtifacts arrays")
                recipe, artifacts = [], []
            for step_index, step in enumerate(recipe):
                if not isinstance(step, dict):
                    continue
                if not safe_relative(step.get("Directory")) and step.get("Directory") != ".":
                    errors.append(f"deploy-plan.json: $.Components[{index}].BuildRecipe[{step_index}].Directory must be project-root-relative")
                command = step.get("Execute")
                if not isinstance(command, str) or not command.strip() or any(char in command for char in "\r\n\x00"):
                    errors.append(f"deploy-plan.json: $.Components[{index}].BuildRecipe[{step_index}].Execute must be one command line")
                for produced in step.get("Produces", []) if isinstance(step.get("Produces"), list) else []:
                    if not safe_relative(produced):
                        errors.append(f"deploy-plan.json: $.Components[{index}].BuildRecipe[{step_index}].Produces contains an unsafe path")
            artifact_paths: list[str] = []
            for artifact_index, artifact in enumerate(artifacts):
                path = artifact.get("Path") if isinstance(artifact, dict) else None
                if not safe_relative(path):
                    errors.append(f"deploy-plan.json: $.Components[{index}].BuildArtifacts[{artifact_index}].Path must be project-root-relative")
                elif path in artifact_paths:
                    errors.append(f"deploy-plan.json: $.Components[{index}].BuildArtifacts contains duplicate path {path!r}")
                else:
                    artifact_paths.append(path)
            produced_paths = {
                produced
                for step in recipe
                if isinstance(step, dict) and isinstance(step.get("Produces"), list)
                for produced in step["Produces"]
                if isinstance(produced, str)
            }
            if recipe and produced_paths != set(artifact_paths):
                errors.append(f"deploy-plan.json: $.Components[{index}] BuildRecipe outputs must match BuildArtifacts")
            own_commands = [
                step.get("Execute") for step in recipe
                if (
                    isinstance(step, dict)
                    and step.get("Kind") == "package-build"
                    and step.get("Directory") == component.get("Directory")
                )
            ]
            if component.get("BuildCommand") != (own_commands[-1] if own_commands else None):
                errors.append(f"deploy-plan.json: $.Components[{index}].BuildCommand is not the BuildRecipe compatibility projection")
            server_artifacts = [
                artifact.get("Path") for artifact in artifacts
                if isinstance(artifact, dict) and artifact.get("Role") == "server-runtime"
            ]
            if isinstance(output, str) and recipe and server_artifacts.count(output) != 1:
                errors.append(f"deploy-plan.json: $.Components[{index}].OutputPath must project the primary server-runtime artifact")
            resolution = component.get("RuntimeResolution")
            if not isinstance(resolution, dict):
                errors.append(f"deploy-plan.json: $.Components[{index}].RuntimeResolution must contain resolver evidence")
            else:
                facts = resolution.get("Evidence")
                if not isinstance(facts, list) or not facts:
                    errors.append(f"deploy-plan.json: $.Components[{index}].RuntimeResolution.Evidence must be non-empty")
                else:
                    output_facts = [fact for fact in facts if isinstance(fact, dict) and fact.get("Fact") == "output-path"]
                    entry_facts = [fact for fact in facts if isinstance(fact, dict) and fact.get("Fact") == "runtime-entry"]
                    if len(output_facts) != 1 or len(entry_facts) != 1:
                        errors.append(f"deploy-plan.json: $.Components[{index}].RuntimeResolution must contain one output-path and one runtime-entry fact")
                    elif entry_facts[0].get("Value") != component.get("RuntimeEntry"):
                        errors.append(f"deploy-plan.json: $.Components[{index}] runtime-entry evidence does not match RuntimeEntry")
                    elif isinstance(output, str) and output_facts[0].get("Value") != output:
                        errors.append(f"deploy-plan.json: $.Components[{index}] output-path evidence does not match OutputPath")
                    build_facts = [fact for fact in facts if isinstance(fact, dict) and fact.get("Fact") == "build-command"]
                    if component.get("BuildCommand") is None and build_facts:
                        errors.append(f"deploy-plan.json: $.Components[{index}] has build-command evidence without BuildCommand")
                    elif isinstance(component.get("BuildCommand"), str) and (
                        len(build_facts) != 1 or build_facts[0].get("Value") != component.get("BuildCommand")
                    ):
                        errors.append(f"deploy-plan.json: $.Components[{index}] build-command evidence does not match BuildCommand")
                if plan.get("Status") != "blocked" and resolution.get("OutputPathSource") in {"pending-agent-configuration", "unresolved-dynamic-config"}:
                    errors.append(f"deploy-plan.json: $.Components[{index}] unresolved output evidence cannot produce a non-blocked plan")
            validation = component.get("BuildValidation")
            if validation is not None:
                if not isinstance(validation, dict):
                    errors.append(f"deploy-plan.json: $.Components[{index}].BuildValidation must be an object")
                    continue
                steps = validation.get("Steps", [])
                actual_builds = [step.get("Command") for step in steps if isinstance(step, dict) and step.get("Kind") == "build"]
                expected_builds = [step.get("Execute") for step in recipe if isinstance(step, dict)]
                if actual_builds != expected_builds:
                    errors.append(f"deploy-plan.json: $.Components[{index}].BuildValidation build commands do not match BuildRecipe")
                if validation.get("RuntimeEntry") != component.get("RuntimeEntry"):
                    errors.append(f"deploy-plan.json: $.Components[{index}].BuildValidation RuntimeEntry mismatch")
                if validation.get("Lockfile") != "package-lock.json":
                    errors.append(f"deploy-plan.json: $.Components[{index}].BuildValidation must use package-lock.json")
                if validation.get("Artifacts") != artifacts:
                    errors.append(f"deploy-plan.json: $.Components[{index}].BuildValidation artifacts do not match BuildArtifacts")
                if not any(isinstance(step, dict) and step.get("Kind") == "install" for step in steps):
                    errors.append(f"deploy-plan.json: $.Components[{index}].BuildValidation requires an install step")
                for step in steps:
                    if not isinstance(step, dict) or step.get("Kind") != "start-probe":
                        continue
                    if (
                        step.get("Host") != "0.0.0.0"
                        or step.get("Port") != 9000
                        or step.get("TimeoutSeconds") != 30
                        or step.get("HttpResponse") is not True
                    ):
                        errors.append(f"deploy-plan.json: $.Components[{index}].BuildValidation start-probe contract mismatch")
                if any(
                    isinstance(artifact, dict) and artifact.get("Verification") not in {"fresh", "http-probed"}
                    for artifact in artifacts
                ):
                    errors.append(f"deploy-plan.json: $.Components[{index}].BuildValidation artifacts must be fresh or HTTP-probed")
    graphs = plan.get("WorkspaceGraphs")
    if backend is not None:
        if not isinstance(graphs, dict):
            errors.append("deploy-plan.json: backend plan requires WorkspaceGraphs")
        else:
            build_graph = graphs.get("BuildGraph")
            runtime_graph = graphs.get("RuntimeGraph")
            if not isinstance(build_graph, dict) or not isinstance(runtime_graph, dict):
                errors.append("deploy-plan.json: WorkspaceGraphs requires BuildGraph and RuntimeGraph")
            else:
                if (
                    build_graph.get("Cyclic") is True
                    and not isinstance(build_graph.get("Orchestrator"), dict)
                    and plan.get("Status") != "blocked"
                ):
                    errors.append("deploy-plan.json: cyclic BuildGraph must block delivery")
                orchestrator = build_graph.get("Orchestrator")
                if isinstance(orchestrator, dict) and backend is not None:
                    recipe = backend.get("BuildRecipe", [])
                    orchestrator_steps = [
                        step for step in recipe
                        if isinstance(step, dict) and step.get("Kind") == "orchestrator"
                    ]
                    if (
                        len(orchestrator_steps) != 1
                        or orchestrator_steps[0].get("Execute") != orchestrator.get("Command")
                        or orchestrator_steps[0].get("Source") != orchestrator.get("Source")
                        or any(
                            not isinstance(step, dict) or step.get("Kind") not in {"orchestrator", "runtime-prepare"}
                            for step in recipe
                        )
                        or not isinstance(backend.get("BuildValidation"), dict)
                    ):
                        errors.append("deploy-plan.json: verified BuildGraph orchestrator must own the complete validated recipe")
                build_nodes = set(build_graph.get("Nodes", []))
                runtime_nodes = set(runtime_graph.get("Nodes", []))
                if not runtime_nodes.issubset(build_nodes):
                    errors.append("deploy-plan.json: RuntimeGraph nodes must be included in BuildGraph")
    if backend is None and plan.get("ProjectType") != "frontend-static" and plan.get("Status") != "blocked":
        errors.append("deploy-plan.json: non-static ready plan has no backend component")


def validate_bootstrap(root: Path, component: dict[str, Any], entry: str, errors: list[str]) -> None:
    path = root / "scf_bootstrap"
    if not path.is_file() or path.is_symlink():
        errors.append("missing regular root scf_bootstrap")
        return
    if stat.S_IMODE(path.stat().st_mode) != 0o755:
        errors.append("scf_bootstrap mode must be 0755")
    data = path.read_bytes()
    try:
        expected = bootstrap_content(PurePosixPath(entry), bootstrap_start_script(component)).encode()
    except (OSError, ValueError) as error:
        errors.append(f"cannot reconstruct scf_bootstrap: {error}")
        return
    if data != expected:
        errors.append("scf_bootstrap content does not match the RuntimeLaunch contract")


def validate_project(root: Path, plan: dict[str, Any], schemas: Path, errors: list[str]) -> None:
    frontend_path = root / "_tmp" / "frontend.deploy.json"
    backend_path = root / "_tmp" / "backend.deploy.json"
    cloudbaserc_path = root / "cloudbaserc.json"
    backend = backend_component(plan, errors)
    has_frontend = any(item.get("Unit") == "frontend" for item in plan.get("Components", []) if isinstance(item, dict))
    if frontend_path.is_file():
        if not has_frontend:
            errors.append("project without frontend component contains frontend.deploy.json")
        frontend = load_json(frontend_path, errors)
        if frontend:
            validate_schema(frontend, schemas / "frontend.deploy.schema.json", frontend_path.name, errors)
            if frontend.get("SchemaVersion") != DEPLOY_SCHEMA_VERSION:
                errors.append(
                    "frontend.deploy.json: SchemaVersion does not match "
                    "the Skill's internal DEPLOY_SCHEMA_VERSION"
                )
            if frontend.get("BuildPath") != f"./{delivery_directory_name(root.name)}":
                errors.append("frontend.deploy.json: BuildPath does not match the space-free delivery directory")
            frontend_components = [
                item for item in plan.get("Components", [])
                if isinstance(item, dict) and item.get("Unit") == "frontend"
            ]
            if len(frontend_components) == 1:
                try:
                    expected_frontend = frontend_descriptor(
                        frontend_components[0], root, str(frontend.get("InstallCmd", "npm ci"))
                    )
                except (SystemExit, ValueError) as error:
                    errors.append(f"cannot reconstruct frontend descriptor: {error}")
                else:
                    if frontend != expected_frontend:
                        errors.append("frontend.deploy.json is not the deterministic output of deploy-plan.json")
    elif has_frontend:
        errors.append("missing _tmp/frontend.deploy.json")
    obsolete_delivery = root / "dist" / "api"
    if obsolete_delivery.exists() or obsolete_delivery.is_symlink():
        errors.append("project contains an obsolete or unowned backend delivery directory")
    if backend is None:
        forbidden = (
            backend_path,
            root / "_tmp" / "backend.runtime.package.json",
            root / "_tmp" / "prepare-backend-package.js",
            root / "scf_bootstrap",
            cloudbaserc_path,
        )
        for path in forbidden:
            if path.exists() or path.is_symlink():
                errors.append(f"static project contains forbidden backend input: {path.relative_to(root)}")
        return
    if not backend_path.is_file():
        errors.append("missing _tmp/backend.deploy.json")
        return
    if not cloudbaserc_path.is_file() or cloudbaserc_path.is_symlink():
        errors.append("missing regular root cloudbaserc.json")
    else:
        cloudbaserc = load_json(cloudbaserc_path, errors)
        if cloudbaserc:
            validate_schema(cloudbaserc, schemas / "cloudbaserc.schema.json", cloudbaserc_path.name, errors)
            try:
                expected_cloudbaserc = cloudbaserc_descriptor(backend)
            except ValueError as error:
                errors.append(f"cannot reconstruct cloudbaserc.json: {error}")
            else:
                if cloudbaserc != expected_cloudbaserc:
                    errors.append("cloudbaserc.json is not the deterministic output of deploy-plan.json")
    descriptor = load_json(backend_path, errors)
    if not descriptor:
        return
    validate_schema(descriptor, schemas / "backend.deploy.schema.json", backend_path.name, errors)
    if descriptor.get("SchemaVersion") != DEPLOY_SCHEMA_VERSION:
        errors.append(
            "backend.deploy.json: SchemaVersion does not match "
            "the Skill's internal DEPLOY_SCHEMA_VERSION"
        )
    try:
        expected_backend = backend_descriptor(plan, backend, root)
    except (SystemExit, ValueError) as error:
        errors.append(f"cannot reconstruct backend descriptor: {error}")
    else:
        if descriptor != expected_backend:
            errors.append("backend.deploy.json is not the deterministic output of deploy-plan.json")
    entry = backend.get("RuntimeEntry")
    if isinstance(entry, str):
        validate_bootstrap(root, backend, entry, errors)
    mode = backend.get("RuntimeManifestMode")
    manifest = root / "_tmp" / "backend.runtime.package.json"
    helper = root / "_tmp" / "prepare-backend-package.js"
    steps = descriptor.get("CustomSteps", [])
    commands = [step.get("Command") if isinstance(step, dict) else None for step in steps] if isinstance(steps, list) else []
    if isinstance(steps, list):
        if not commands or commands[0] != "npm ci":
            errors.append("backend CustomSteps must begin with npm ci")
        if len(commands) < 2 or not isinstance(commands[1], str) or not ("test -e " in commands[1] or commands[1].startswith("test -f ")):
            errors.append("backend second CustomStep must build/verify artifacts or validate an existing entry")
        if len(commands) < 2 or commands[-2] != "npm i @cloudbase/cli@3.8.0-beta.3 -g":
            errors.append("backend penultimate CustomStep must install the pinned CloudBase CLI")
        deploy_fragment = 'tcb fn deploy ${functionName} --dir . --force -e "$CLOUDBASE_ENV_ID" --httpFn --yes'
        if not commands or not isinstance(commands[-1], str) or deploy_fragment not in commands[-1]:
            errors.append("backend final CustomStep must deploy the project root through the ${functionName} placeholder")
    prepare_indexes = [index for index, command in enumerate(commands) if command == "node _tmp/prepare-backend-package.js"]
    if mode == "overlay":
        if not manifest.is_file() or not helper.is_file():
            errors.append("overlay mode requires runtime manifest and preparation script")
        if manifest.is_file():
            runtime = load_json(manifest, errors)
            if runtime:
                expected_start = f"node {entry}"
                if runtime.get("main") != entry or runtime.get("scripts") != {"start": expected_start}:
                    errors.append("overlay runtime manifest entry/start mismatch")
                for forbidden in ("devDependencies", "preinstall", "install", "postinstall"):
                    if forbidden in runtime:
                        errors.append(f"overlay runtime manifest contains forbidden field: {forbidden}")
                try:
                    expected_runtime = runtime_manifest(root, backend)
                except (ValueError, SystemExit) as error:
                    errors.append(f"cannot reconstruct overlay runtime manifest: {error}")
                else:
                    if runtime != expected_runtime:
                        errors.append("backend.runtime.package.json is not the deterministic output of deploy-plan.json")
        if helper.is_file() and isinstance(entry, str):
            if helper.read_text(encoding="utf-8") != helper_source(entry):
                errors.append("overlay preparation script does not match the precomputed contract")
        if prepare_indexes != [2]:
            errors.append("overlay manifest replacement must be the third CustomStep, after install and build")
        if len(commands) < 4 or commands[3] != "npm install --omit=dev --ignore-scripts":
            errors.append("overlay production install must immediately follow manifest replacement")
    else:
        if manifest.exists() or helper.exists():
            errors.append("root mode must not contain overlay runtime files")
        if prepare_indexes:
            errors.append("root mode must not run the overlay preparation script")
        if len(commands) < 3 or commands[2] != "npm install --omit=dev --ignore-scripts":
            errors.append("root production install must immediately follow the build step")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deploy_output", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    return parser.parse_args()


def finish(errors: list[str], success: str) -> int:
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        print(f"validation failed: {len(errors)} error(s)", file=sys.stderr)
        return 1
    print(success)
    return 0


def main() -> int:
    args = parse_args()
    root = args.deploy_output.resolve()
    errors: list[str] = []
    schemas = Path(__file__).resolve().parent.parent / "references" / "schemas"
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2
    plan_path = root / "deploy-plan.json" if args.plan_only else root / "_tmp" / "deploy-plan.json"
    if not plan_path.is_file():
        return finish([f"missing required plan: {plan_path.relative_to(root)}"], "")
    plan = load_json(plan_path, errors)
    if plan:
        validate_schema(plan, schemas / "deploy-plan.schema.json", "deploy-plan.json", errors)
        validate_plan_semantics(plan, errors)
        if not args.plan_only:
            validate_project(root, plan, schemas, errors)
    return finish(errors, "plan validation passed" if args.plan_only else "deployment input validation passed")


if __name__ == "__main__":
    raise SystemExit(main())
