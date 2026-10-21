# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Deploy relocatable AppDirs and generate AppImage packages."""

from __future__ import annotations

import shlex
from pathlib import Path

from ..core import BuildContext, PackageBackend, ProjectHooks, artifact, tool_missing
from ..model import AppImageOptions, Artifact, SetupError
from ..validation import ConfigPaths, fields, mapping, sequence, string, strings
from .common import binary_deploy, common_check, desktop_check, validate_elf


def appimage_options(ctx: BuildContext) -> AppImageOptions:
    """Return typed AppImage options or reject a mismatched target.

    Args:
        ctx: Target-local configuration, paths, and command execution services.

    Returns:
        Validated options of the backend-specific type.

    Raises:
        SetupError: The target does not contain AppImageOptions.
    """
    options = ctx.target.options
    if not isinstance(options, AppImageOptions):
        raise SetupError("AppImage options required")
    return options


class AppImageBackend(PackageBackend):
    """Deploy a relocatable AppDir, then convert it to an AppImage."""

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Report unmet packaging requirements.

        Report AppImage tools, plugins, runtime, metadata, and library requirements.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Unmet requirements as messages; an empty tuple means all checked
            requirements are satisfied.
        """
        opts = appimage_options(ctx)
        errors = list(common_check(ctx))
        for tool in (opts.linuxdeploy, opts.appimagetool, "desktop-file-validate"):
            errors.extend(tool_missing(tool))
        for plugin in opts.plugins:
            errors.extend(tool_missing(f"linuxdeploy-plugin-{plugin}"))
        if opts.runtime_file is not None and not ctx.resolve_path(opts.runtime_file).is_file():
            errors.append(f"AppImage runtime file: {opts.runtime_file}")
        for library in opts.libraries:
            if "{build}" not in str(library) and not ctx.resolve_path(library).is_file():
                errors.append(f"Library: {library}")
        return tuple(errors)

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Stage the application or recipe contents.

        Stage an AppDir, collect dependencies with linuxdeploy, and validate its launcher.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            hooks: Trusted host project callbacks invoked at the backend-defined
                extension points.

        Raises:
            SetupError: A dependency directory is unsafe or linuxdeploy does not produce
                AppRun.
        """
        opts = appimage_options(ctx)
        app = ctx.config.application
        binary_deploy(ctx, hooks, "usr/")
        desktop = ctx.deploy_dir / f"usr/share/applications/{app.id}.desktop"
        desktop_check(desktop, ctx.executable_name, app.id)
        ctx.run(["desktop-file-validate", str(desktop)])
        args = [opts.linuxdeploy, "--appdir", str(ctx.deploy_dir),
                "--executable", str(ctx.deploy_dir / "usr/bin" / ctx.executable_name),
                "--desktop-file", str(desktop), "--icon-file", str(app.icon)]
        for plugin in opts.plugins:
            args.extend(["--plugin", plugin])
        for library in opts.libraries:
            args.extend(["--library", str(ctx.resolve_path(library))])
        for directory in opts.dependency_dirs:
            path = ctx.deploy_dir / directory
            if not path.resolve().is_relative_to(ctx.deploy_dir.resolve()) or not path.is_dir():
                raise SetupError(f"Invalid deployed dependency directory: {directory}")
            args.extend(["--deploy-deps-only", str(path)])
        ctx.run(args, env={**dict(opts.environment), "ARCH": ctx.target.arch})
        if not (ctx.deploy_dir / "AppRun").is_file():
            raise SetupError("linuxdeploy did not generate AppRun")
        apprun = ctx.deploy_dir / "AppRun"
        executable = ctx.app_dir / ctx.executable_name
        # Some extract-and-run runtimes materialize symlinks. Qt then sees the
        # root AppRun as its executable and misses bin/qt.conf and bin resources.
        # Preserve custom launchers, replacing only the direct binary symlink.
        if apprun.is_symlink() and apprun.resolve() == executable.resolve():
            apprun.unlink()
            apprun.write_text(
                '#!/bin/sh\n'
                'appdir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1\n'
                f'exec "$appdir"/usr/bin/{shlex.quote(ctx.executable_name)} "$@"\n'
            )
            apprun.chmod(0o755)

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Validate the AppDir and invoke appimagetool to generate the final package.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Completed output artifacts in the requested generation order.

        Raises:
            SetupError: The launcher or entry is invalid, output exists, or package
                generation fails.
        """
        opts = appimage_options(ctx)
        app = ctx.config.application
        if not (ctx.deploy_dir / "AppRun").is_file():
            raise SetupError("AppDir is missing AppRun")
        output = ctx.config.output / ctx.target.name / f"{app.name}-{app.version}-{ctx.target.arch}.AppImage"
        validate_elf(ctx.deploy_dir / "usr/bin" / ctx.executable_name, ctx.target.arch)
        if output.exists():
            raise SetupError(f"Output already exists: {output}")
        args = [opts.appimagetool]
        if opts.runtime_file is not None:
            args.extend(["--runtime-file", str(ctx.resolve_path(opts.runtime_file))])
        ctx.run([*args, str(ctx.deploy_dir), str(output)],
                env={"ARCH": ctx.target.arch, "VERSION": app.version})
        return (artifact(ctx, output, "appimage"),)




def parse_options(opts: dict[str, object], paths: ConfigPaths) -> AppImageOptions:
    """Validate and resolve backend options.

    Validate backend option fields and resolve paths into an immutable options object.

    Args:
        opts: Raw backend option mapping validated before constructing typed options.
        paths: Resolver for configuration-relative paths and executable names.

    Returns:
        Validated options of the backend-specific type.

    Raises:
        SetupError: An option is unknown, has an invalid type, or violates backend
            constraints.
    """
    fields(opts, "linuxdeploy appimagetool plugins libraries environment dependency_dirs runtime_file", "options")
    environment = mapping(opts.get("environment", {}), "environment")
    dependency_dirs = strings(opts.get("dependency_dirs", []), "dependency_dirs")
    if any(Path(p).is_absolute() or ".." in Path(p).parts for p in dependency_dirs):
        raise SetupError("dependency_dirs must be relative to deployment root")
    options = AppImageOptions(
        paths.tool(opts.get("linuxdeploy", "linuxdeploy"), "linuxdeploy"),
        paths.tool(opts.get("appimagetool", "appimagetool"), "appimagetool"),
        strings(opts.get("plugins", []), "plugins"),
        tuple(paths.resolve(p, "library") for p in sequence(opts.get("libraries", []), "libraries")),
        tuple((key, string(value, f"environment.{key}")) for key, value in environment.items()),
        dependency_dirs,
        None if opts.get("runtime_file") is None else paths.resolve(opts["runtime_file"], "runtime_file"),
    )
    return options
