# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Create portable native payload archives without claiming automatic dependency discovery."""

from __future__ import annotations

import tarfile
from dataclasses import dataclass
from pathlib import Path

from ..core import BuildContext, PackageBackend, ProjectHooks, artifact, deploy_resources
from ..model import Artifact, BackendOptions, SetupError
from ..platforms import normalize_arch
from .common import validate_elf
from ..validation import ConfigPaths, fields, string
from .native import native_check, output_path


@dataclass(frozen=True)
class ArchiveOptions(BackendOptions):
    """Optional preassembled application tree copied before project deployment."""

    #: Repository-relative or generated directory containing the relocatable payload.
    payload: Path | None = None
    #: Portable archive format; zip uses macOS ditto to preserve resource forks and links.
    format: str = "tar.gz"


def parse_options(data: dict[str, object], paths: ConfigPaths) -> ArchiveOptions:
    """Validate portable archive options.

    Args:
        data: Raw YAML option mapping.
        paths: Configuration-relative path resolver.

    Returns:
        Immutable payload selection.
    """
    fields(data, 'payload format', 'archive')
    format_name = string(data.get('format', 'tar.gz'), 'format')
    if format_name not in {'tar.gz', 'zip'}:
        raise SetupError('Archive format must be tar.gz or zip')
    return ArchiveOptions(None if 'payload' not in data else paths.resolve(data['payload'], 'payload'), format_name)


class ArchiveBackend(PackageBackend):
    """Archive a native application with project-owned dependency deployment."""

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Require the declared native host and architecture.

        Args:
            ctx: Target-local configuration and paths.

        Returns:
            Missing native host or toolchain requirements.
        """
        options = ctx.target.options
        assert isinstance(options, ArchiveOptions)
        errors = list(native_check(ctx, ctx.target.platform, ("lipo", "ditto") if ctx.target.platform == "Darwin" else ()))
        if options.format == "zip" and ctx.target.platform != "Darwin":
            errors.append("Portable ZIP currently requires macOS; use Inno ZIP on Windows")
        return tuple(errors)

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Stage a payload or entry executable, resources, and project extensions.

        Args:
            ctx: Target-local configuration and paths.
            hooks: Project deployment callback responsible for dependency closure.
        """
        options = ctx.target.options
        assert isinstance(options, ArchiveOptions)
        if options.payload is None:
            ctx.copy_app(ctx.executable, ctx.executable_name)
        else:
            ctx.copy(options.payload, '.')
        deploy_resources(ctx)
        hooks.deploy(ctx)
        entry = ctx.app_dir / ctx.executable_name
        if ctx.target.platform in {"Linux", "FreeBSD"}:
            validate_elf(entry, ctx.target.arch)
        elif ctx.target.platform == "Darwin":
            slices = {normalize_arch(item) for item in ctx.run(["lipo", "-archs", str(entry)]).split()}
            required = {"aarch64", "x86_64"} if ctx.target.arch == "universal2" else {ctx.target.arch}
            if not required.issubset(slices):
                raise SetupError("Archive Mach-O architectures do not match the target")

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Write a portable tar archive or a resource-preserving macOS ZIP.

        Args:
            ctx: Fully deployed native payload and output directory.

        Returns:
            File artifact with the final SHA-256 digest.
        """
        options = ctx.target.options
        assert isinstance(options, ArchiveOptions)
        path = output_path(ctx, options.format)
        if options.format == "zip":
            ctx.run(["ditto", "-c", "-k", "--sequesterRsrc", str(ctx.deploy_dir), str(path)])
        else:
            with tarfile.open(path, 'w:gz') as stream:
                stream.add(ctx.deploy_dir, arcname='.')
        return (artifact(ctx, path, options.format),)
