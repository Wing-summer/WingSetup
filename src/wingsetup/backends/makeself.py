# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Archive explicit application payloads as self-extracting installers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core import BuildContext, PackageBackend, ProjectHooks, artifact, deploy_resources
from ..model import Artifact, BackendOptions, SetupError
from ..validation import ConfigPaths, fields, string
from .native import native_check, output_path


@dataclass(frozen=True)
class MakeselfOptions(BackendOptions):
    """Payload, installer entry script, and self-extracting archive settings."""

    #: Build output directory copied into the installer staging tree.
    payload: Path
    #: Application-owned installation script included without executing it.
    startup: Path
    #: Makeself executable name or resolved path.
    tool: str = "makeself"
    #: Output filename extension, either run or sh.
    suffix: str = "run"
    #: Shell used for syntax validation and installer startup.
    interpreter: str = "sh"


def parse_options(data: dict[str, object], paths: ConfigPaths) -> MakeselfOptions:
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
    fields(data, "payload startup tool suffix interpreter", "makeself")
    suffix = string(data.get("suffix", "run"), "suffix")
    if suffix not in ("run", "sh"):
        raise SetupError("Makeself suffix must be run or sh")
    interpreter = string(data.get("interpreter", "sh"), "interpreter")
    if interpreter not in ("sh", "bash"):
        raise SetupError("Makeself interpreter must be sh or bash")
    return MakeselfOptions(paths.resolve(data.get("payload"), "payload"),
                           paths.resolve(data.get("startup"), "startup"),
                           paths.tool(data.get("tool", "makeself"), "tool"), suffix, interpreter)


class MakeselfBackend(PackageBackend):
    """Package an explicit installer; never execute it during package creation."""

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Report native tools and the installer startup script requirement.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Unmet requirements as messages; an empty tuple means all checked
            requirements are satisfied.
        """
        opts = ctx.target.options
        assert isinstance(opts, MakeselfOptions)
        errors = list(native_check(ctx, ctx.target.platform or "Linux", (opts.tool, opts.interpreter)))
        if "{build}" not in str(opts.startup) and "{work}" not in str(opts.startup) and not ctx.resolve_path(opts.startup).is_file():
            errors.append(f"Installer startup script: {opts.startup}")
        return tuple(errors)

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Stage the application or recipe contents.

        Stage the payload and extensions, then syntax-check the reserved startup script.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            hooks: Trusted host project callbacks invoked at the backend-defined
                extension points.

        Raises:
            SetupError: The payload uses the reserved startup filename or staging or
                syntax validation fails.
        """
        opts = ctx.target.options
        assert isinstance(opts, MakeselfOptions)
        ctx.copy(opts.payload, ".")
        deploy_resources(ctx)
        hooks.deploy(ctx)
        startup = ctx.deploy_dir / "_wingsetup-install.sh"
        if startup.exists():
            raise SetupError("Payload contains reserved _wingsetup-install.sh")
        ctx.copy(opts.startup, startup.name)
        startup.chmod(0o755)
        ctx.run([opts.interpreter, "-n", str(startup)])

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Create final packaging artifacts.

        Generate a self-extracting archive with SHA-256 integrity checks without running it.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Completed output artifacts in the requested generation order.
        """
        opts = ctx.target.options
        assert isinstance(opts, MakeselfOptions)
        output = output_path(ctx, opts.suffix)
        ctx.run([opts.tool, "--sha256", str(ctx.deploy_dir), str(output),
                 ctx.config.application.name, opts.interpreter, "./_wingsetup-install.sh"])
        output.chmod(0o755)
        return (artifact(ctx, output, "makeself"),)
