# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Share Linux metadata deployment and executable validation helpers."""

from __future__ import annotations

import configparser
import os
import platform
import struct
from pathlib import Path

from ..core import BuildContext, ProjectHooks, deploy_resources
from ..model import SetupError
from ..platforms import normalize_arch


def common_check(ctx: BuildContext) -> tuple[str, ...]:
    """Check Linux host and desktop metadata requirements.

    Report Linux host, native architecture, source, and desktop metadata requirements.

    Args:
        ctx: Target-local configuration, paths, and command execution services.

    Returns:
        Unmet requirements as messages; an empty tuple means all checked requirements
        are satisfied.
    """
    errors: list[str] = []
    if platform.system() != "Linux":
        errors.append("Linux host required")
    if ctx.target.arch != normalize_arch(platform.machine()):
        errors.append(f"Native architecture required: host={platform.machine()}, target={ctx.target.arch}")
    if not ctx.source_dir.is_dir():
        errors.append(f"Source directory: {ctx.source_dir}")
    for path in (ctx.config.application.desktop, ctx.config.application.icon):
        if path is None or not path.is_file():
            errors.append(f"Metadata file: {path}")
    return tuple(errors)


def validate_elf(path: Path, arch: str) -> None:
    """Check ELF architecture and execute permission.

    Validate 64-bit ELF architecture and execute permission, without promising ABI compatibility.

    Args:
        path: File or directory path to inspect or process.
        arch: Normalized target architecture expected in the executable.

    Raises:
        SetupError: The file cannot be read or lacks the required ELF architecture or
            execute permission.
    """
    try:
        with path.open("rb") as stream:
            header = stream.read(20)
    except OSError as exc:
        raise SetupError(f"Cannot read executable {path}: {exc}") from exc
    if len(header) < 20 or header[:4] != b"\x7fELF" or header[4] != 2 or header[5] not in (1, 2):
        raise SetupError(f"Expected a 64-bit ELF binary: {path}")
    machine = struct.unpack("<H" if header[5] == 1 else ">H", header[18:20])[0]
    if machine != {"x86_64": 62, "aarch64": 183}[arch]:
        raise SetupError(f"Executable architecture does not match {arch}: {path}")
    if not os.access(path, os.X_OK):
        raise SetupError(f"Executable permission missing: {path}")


class DesktopParser(configparser.ConfigParser):
    """Parse desktop entries while preserving case-sensitive field names."""

    def optionxform(self, optionstr: str) -> str:
        """Preserve desktop entry key capitalization during parsing.

        Args:
            optionstr: Original configuration key whose capitalization must be
                preserved.

        Returns:
            Validated or preserved input string.
        """
        return optionstr


def desktop_check(path: Path, command: str, app_id: str) -> None:
    """Validate desktop entry identity, icon naming, and executable command.

    Args:
        path: File or directory path to inspect or process.
        command: Expected executable filename at the start of the desktop Exec field.
        app_id: Expected reverse-DNS application identifier and desktop icon name.

    Raises:
        SetupError: Required desktop fields are missing, inconsistent, or cannot be
            parsed.
    """
    parser = DesktopParser(interpolation=None, strict=True)
    try:
        parser.read_string(path.read_text())
        entry = parser["Desktop Entry"]
        if entry.get("Type") != "Application" or not entry.get("Name"):
            raise SetupError(f"Invalid Desktop Entry: {path}")
        if entry.get("Icon") != app_id:
            raise SetupError(f"{path}: Icon must equal {app_id}")
        executable = entry.get("Exec", "").split()
        if not executable or executable[0] != command:
            raise SetupError(f"{path}: Exec must start with {command}")
    except (OSError, configparser.Error, KeyError) as exc:
        raise SetupError(f"Invalid desktop file {path}: {exc}") from exc


def deploy_linux_metadata(ctx: BuildContext, prefix: str) -> None:
    """Copy desktop and icon sources into standard Linux deployment locations.

    Args:
        ctx: Target-local configuration, paths, and command execution services.
        prefix: Deployment-root-relative installation prefix, including its trailing
            separator.

    Raises:
        SetupError: Desktop metadata is missing or the icon format is unsupported.
    """
    app = ctx.config.application
    if app.desktop is None or app.icon is None:
        raise SetupError("Linux desktop packaging requires application.desktop and application.icon")
    ctx.copy(app.desktop, f"{prefix}share/applications/{app.id}.desktop")
    extension = app.icon.suffix.lower()
    if extension not in (".png", ".svg"):
        raise SetupError("Icon must be PNG or SVG")
    size = "scalable" if extension == ".svg" else "256x256"
    ctx.copy(app.icon, f"{prefix}share/icons/hicolor/{size}/apps/{app.id}{extension}")


def binary_deploy(ctx: BuildContext, hooks: ProjectHooks, prefix: str) -> None:
    """Stage and validate a Linux binary installation.

    Stage a Linux executable and metadata, apply resources and hooks, and validate ELF.

    Args:
        ctx: Target-local configuration, paths, and command execution services.
        hooks: Trusted host project callbacks invoked at the backend-defined extension
            points.
        prefix: Deployment-root-relative installation prefix, including its trailing
            separator.
    """
    ctx.deploy_dir.mkdir(parents=True, exist_ok=True)
    ctx.copy(ctx.executable, f"{prefix}bin/{ctx.executable_name}")
    deploy_linux_metadata(ctx, prefix)
    deploy_resources(ctx)
    hooks.deploy(ctx)
    validate_elf(ctx.deploy_dir / f"{prefix}bin/{ctx.executable_name}", ctx.target.arch)
