from __future__ import annotations

from typing import Any


CLOUD_FUNCTION_RUNTIMES: dict[int, tuple[str, bool]] = {
    16: ("Nodejs16.13", True),
    18: ("Nodejs18.15", True),
    20: ("Nodejs20.19", True),
    22: ("Nodejs22.21", False),
    24: ("Nodejs24.11", False),
}


def cloud_function_runtime(
    detected_node_major: str,
    reviewed_override: str | None = None,
) -> dict[str, Any] | None:
    if not detected_node_major.isdigit():
        raise ValueError("detected backend Node version must be a major number")
    detected = int(detected_node_major)
    if reviewed_override is not None:
        if not reviewed_override.isdigit() or int(reviewed_override) not in CLOUD_FUNCTION_RUNTIMES:
            raise ValueError("reviewed CloudBase function Node version must be one of 16, 18, 20, 22, or 24")
        target = int(reviewed_override)
        source = "reviewed-override"
    else:
        target = next((major for major in CLOUD_FUNCTION_RUNTIMES if detected <= major), 0)
        if target == 0:
            return None
        source = "auto-map"
    runtime, install_dependency = CLOUD_FUNCTION_RUNTIMES[target]
    return {
        "Runtime": runtime,
        "InstallDependency": install_dependency,
        "Source": source,
    }


def validate_cloud_function_runtime(node_version: Any, value: Any) -> None:
    if not isinstance(node_version, str) or not node_version.isdigit():
        raise ValueError("backend NodeVersion must be a detected Node major")
    if not isinstance(value, dict):
        raise ValueError("CloudFunctionRuntime must be an object")
    if set(value) != {"Runtime", "InstallDependency", "Source"}:
        raise ValueError("CloudFunctionRuntime must contain only Runtime, InstallDependency, and Source")
    source = value.get("Source")
    if source not in {"auto-map", "reviewed-override"}:
        raise ValueError("CloudFunctionRuntime.Source must be auto-map or reviewed-override")
    if source == "auto-map":
        expected = cloud_function_runtime(node_version)
        if expected is None:
            raise ValueError("Node versions above 24 require a reviewed CloudBase function runtime override")
        if value != expected:
            raise ValueError("auto-mapped CloudFunctionRuntime does not match NodeVersion")
        return
    allowed_values = {
        (runtime, install_dependency)
        for runtime, install_dependency in CLOUD_FUNCTION_RUNTIMES.values()
    }
    if (value.get("Runtime"), value.get("InstallDependency")) not in allowed_values:
        raise ValueError("reviewed CloudFunctionRuntime is not in the fixed CloudBase runtime table")
    if int(node_version) > 24 and value.get("Runtime") != "Nodejs24.11":
        raise ValueError("Node versions above 24 only accept the reviewed Nodejs24.11 downgrade")


def cloudbaserc_descriptor(component: dict[str, Any]) -> dict[str, Any]:
    runtime = component.get("CloudFunctionRuntime")
    validate_cloud_function_runtime(component.get("NodeVersion"), runtime)
    assert isinstance(runtime, dict)
    return {
        "envId": "{{env.CLOUDBASE_ENV_ID}}",
        "functionRoot": ".",
        "functions": [{
            "name": "{{env.CLOUDBASE_SERVICE_NAME}}",
            "type": "HTTP",
            "installDependency": runtime["InstallDependency"],
            "runtime": runtime["Runtime"],
        }],
    }
