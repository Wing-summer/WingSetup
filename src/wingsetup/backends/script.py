# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Export application-owned installation and management scripts."""

from __future__ import annotations

import tarfile
from dataclasses import dataclass, replace
import platform
from pathlib import Path

from ..core import BuildContext, PackageBackend, ProjectHooks, artifact
from ..model import Artifact, BackendOptions
from ..validation import ConfigPaths, fields, string
from .native import output_path, relative_path


@dataclass(frozen=True)
class ScriptOptions(BackendOptions):
    """Management script directory and its required entry point."""

    #: Directory containing application-owned management scripts.
    recipe: Path
    #: Relative entry-point path that must exist in the recipe directory.
    entry: str = "install.sh"


def parse_options(data: dict[str, object], paths: ConfigPaths) -> ScriptOptions:
    """Validate and resolve backend options.

    Validate backend option fields and resolve paths into an immutable options object.

    Args:
        data: Raw backend option mapping whose keys and values must be validated.
        paths: Resolver for configuration-relative paths and executable names.

    Returns:
        Validated options of the backend-specific type.
    """
    fields(data, "recipe entry", "script")
    return ScriptOptions(paths.resolve(data.get("recipe"), "recipe"),
                         relative_path(string(data.get("entry", "install.sh"), "entry")))


class ScriptBackend(PackageBackend):
    """Export project-owned shell/Python managers without running them."""

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Report a missing management-script entry point.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Unmet requirements as messages; an empty tuple means all checked
            requirements are satisfied.
        """
        opts = ctx.target.options
        assert isinstance(opts, ScriptOptions)
        return () if (ctx.resolve_path(opts.recipe) / opts.entry).is_file() else (f"Script recipe entry: {opts.recipe / opts.entry}",)

    def build(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Perform the backend or project build extension.

        Skip host compilation because the final product contains management scripts.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            hooks: Trusted host project callbacks invoked at the backend-defined
                extension points.
        """
        pass  # A recipe may be the final product; no binary build is implied.

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Stage script recipes and target resources, then invoke project extensions.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            hooks: Trusted host project callbacks invoked at the backend-defined
                extension points.
        """
        opts = ctx.target.options
        assert isinstance(opts, ScriptOptions)
        ctx.copy(opts.recipe, ".")
        for rule in ctx.target.resources:
            if not rule.platforms or (ctx.target.platform if ctx.target.platform != "any" else platform.system()) in rule.platforms:
                ctx.copy(rule.source, rule.destination, exclude=rule.exclude)
        hooks.deploy(ctx)

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Archive management scripts without executing their entry point.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Completed output artifacts in the requested generation order.
        """
        output = output_path(ctx, "scripts.tar.gz")
        with tarfile.open(output, "w:gz") as archive:
            archive.add(ctx.deploy_dir, arcname=".")
        return (replace(artifact(ctx, output, "script"), kind="recipe"),)
