# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Export trusted AUR recipes without compiling or publishing applications."""

from __future__ import annotations

import tarfile
from dataclasses import dataclass, replace
import platform
from pathlib import Path

from ..core import BuildContext, PackageBackend, ProjectHooks, artifact, tool_missing
from ..model import Artifact, BackendOptions, SetupError
from ..validation import ConfigPaths, fields, string
from .native import output_path


@dataclass(frozen=True)
class AurOptions(BackendOptions):
    """AUR recipe directory and source-information generation policy."""

    #: Directory containing the trusted PKGBUILD and supporting recipe files.
    recipe: Path
    #: Generate .SRCINFO with makepkg, or require an existing file when false.
    generate_srcinfo: bool = True


def parse_options(data: dict[str, object], paths: ConfigPaths) -> AurOptions:
    """Validate and resolve backend options.

    Validate backend option fields and resolve paths into an immutable options object.

    Args:
        data: Raw backend option mapping whose keys and values must be validated.
        paths: Resolver for configuration-relative paths and executable names.

    Returns:
        Validated options of the backend-specific type.

    Raises:
        SetupError: An option is unknown, has an invalid type, or violates backend
            constraints.
    """
    fields(data, "recipe generate_srcinfo", "aur")
    flag = data.get("generate_srcinfo", True)
    if not isinstance(flag, bool):
        raise SetupError("aur.generate_srcinfo must be boolean")
    return AurOptions(paths.resolve(string(data.get("recipe"), "recipe"), "recipe"), flag)


class AurBackend(PackageBackend):
    """Emit project-owned PKGBUILD recipes; never compile or publish them here."""

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Report shell, optional makepkg, and trusted PKGBUILD requirements.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Unmet requirements as messages; an empty tuple means all checked
            requirements are satisfied.
        """
        opts = ctx.target.options
        assert isinstance(opts, AurOptions)
        missing = list(tool_missing("bash"))
        if opts.generate_srcinfo:
            missing.extend(tool_missing("makepkg"))
        if not (ctx.resolve_path(opts.recipe) / "PKGBUILD").is_file():
            missing.append(f"AUR recipe directory containing PKGBUILD: {opts.recipe}")
        return tuple(missing)

    def build(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Skip host compilation because the final product is an AUR recipe.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            hooks: Trusted host project callbacks invoked at the backend-defined
                extension points.
        """
        pass  # Recipe output has no host or SDK compilation step.

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Stage the application or recipe contents.

        Stage recipe files and extensions, validate shell syntax, and prepare .SRCINFO.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            hooks: Trusted host project callbacks invoked at the backend-defined
                extension points.

        Raises:
            SetupError: Source information is empty or missing, or recipe validation
                fails.
        """
        opts = ctx.target.options
        assert isinstance(opts, AurOptions)
        ctx.copy(opts.recipe, ".")
        # Compiled common resources do not belong in an AUR recipe.
        for rule in ctx.target.resources:
            if not rule.platforms or (ctx.target.platform if ctx.target.platform != "any" else platform.system()) in rule.platforms:
                ctx.copy(rule.source, rule.destination, exclude=rule.exclude)
        hooks.deploy(ctx)
        ctx.run(["bash", "-n", str(ctx.deploy_dir / "PKGBUILD")])
        if opts.generate_srcinfo:
            info = ctx.run(["makepkg", "--printsrcinfo"], cwd=ctx.deploy_dir)
            if not info.strip():
                raise SetupError("makepkg produced empty .SRCINFO")
            (ctx.deploy_dir / ".SRCINFO").write_text(info, encoding="utf-8")
        elif not (ctx.deploy_dir / ".SRCINFO").is_file():
            raise SetupError("Supply .SRCINFO or enable generate_srcinfo")

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Archive the staged AUR recipe without building or publishing it.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Completed output artifacts in the requested generation order.
        """
        output = output_path(ctx, "aur.tar.gz")
        with tarfile.open(output, "w:gz") as archive:
            archive.add(ctx.deploy_dir, arcname=".")
        return (replace(artifact(ctx, output, "aur"), kind="recipe"),)
