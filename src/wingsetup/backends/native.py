# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Share native-platform checks and deployment path helpers."""

from __future__ import annotations

import platform
import re
from pathlib import Path

from ..core import BuildContext, ProjectHooks, deploy_resources, tool_missing
from ..model import SetupError
from ..platforms import normalize_arch


def native_check(ctx: BuildContext, system: str, tools: tuple[str, ...]) -> tuple[str, ...]:
    """Report native host, architecture, source directory, and tool requirements.

    Args:
        ctx: Target-local configuration, paths, and command execution services.
        system: Required native host platform name.
        tools: Executable names or paths required on the native host.

    Returns:
        Unmet requirements as messages; an empty tuple means all checked requirements
        are satisfied.
    """
    errors: list[str] = []
    if platform.system() != system:
        errors.append(f"{system} host required (current: {platform.system()})")
    if ctx.target.arch != "universal2" and normalize_arch(platform.machine()) != ctx.target.arch:
        errors.append(f"Native {ctx.target.arch} toolchain required")
    if not ctx.source_dir.is_dir():
        errors.append(f"Source directory: {ctx.source_dir}")
    for tool in tools:
        errors.extend(tool_missing(tool))
    return tuple(errors)


def output_path(ctx: BuildContext, suffix: str) -> Path:
    """Create the target output directory and reject an existing output filename.

    Args:
        ctx: Target-local configuration, paths, and command execution services.
        suffix: Output extension appended to the application, version, and architecture.

    Returns:
        Unused output filename under the selected target directory.

    Raises:
        SetupError: A file already exists at the generated output path.
    """
    app = ctx.config.application
    root = ctx.config.output / ctx.target.name
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{app.name}-{app.version}-{ctx.target.arch}.{suffix}"
    if path.exists():
        raise SetupError(f"Output already exists: {path}")
    return path


def deploy_entry(ctx: BuildContext, hooks: ProjectHooks) -> None:
    """Stage a native entry point and project resources.

    Copy the native entry and configured resources, then invoke project deployment.

    Args:
        ctx: Target-local configuration, paths, and command execution services.
        hooks: Trusted host project callbacks invoked at the backend-defined extension
            points.
    """
    ctx.copy(ctx.executable, str((ctx.app_dir / ctx.executable_name).relative_to(ctx.deploy_dir)))
    deploy_resources(ctx)
    hooks.deploy(ctx)


def safe_line(value: str, name: str) -> str:
    """Reject line breaks and null bytes in a package metadata value.

    Args:
        value: Untyped input value to validate or normalize.
        name: Name of the tool, backend, field, or environment variable being processed.

    Returns:
        Validated or preserved input string.

    Raises:
        SetupError: The metadata value contains a line break or null byte.
    """
    if any(char in value for char in ("\r", "\n", "\0")):
        raise SetupError(f"{name} must be a single line")
    return value


def relative_path(value: str) -> str:
    """Require a relative path without parent traversal or Windows drive syntax.

    Args:
        value: Untyped input value to validate or normalize.

    Returns:
        Validated or preserved input string.

    Raises:
        SetupError: The path is absolute, uses a drive prefix, or contains forbidden
            traversal syntax.
    """
    if Path(value).is_absolute() or ".." in Path(value).parts or "\\" in value or re.match(r"^[A-Za-z]:", value):
        raise SetupError(f"Expected safe relative path: {value}")
    return value
