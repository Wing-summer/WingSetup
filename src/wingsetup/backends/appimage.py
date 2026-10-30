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


def deploy_qt_platforms(ctx: BuildContext, opts: AppImageOptions) -> None:
    """Stage requested Qt QPA backends and Wayland client integration plugins.

    Args:
        ctx: AppDir context using the same Qt SDK as the compiled application.
        opts: Requested Qt platforms and QMAKE override.

    Raises:
        SetupError: The selected Qt SDK lacks a requested platform backend.
    """
    if not opts.qt_platforms:
        return
    qmake = dict(opts.environment).get("QMAKE", "qmake")
    root = Path(ctx.run([qmake, "-query", "QT_INSTALL_PLUGINS"]).strip())
    if not root.is_absolute() or not root.is_dir():
        raise SetupError("QMAKE returned an invalid QT_INSTALL_PLUGINS directory")
    names = {"wayland": "libqwayland*.so", "xcb": "libqxcb.so", "offscreen": "libqoffscreen.so"}
    for platform in opts.qt_platforms:
        plugins = sorted((root / "platforms").glob(names[platform]))
        if not plugins:
            raise SetupError(f"Qt SDK is missing {platform} plugins under {root}; prepare the matching Qt module")
        for plugin in plugins:
            ctx.copy(plugin, f"usr/plugins/platforms/{plugin.name}")
    if "wayland" in opts.qt_platforms:
        for name in ("wayland-decoration-client", "wayland-graphics-integration-client", "wayland-shell-integration"):
            directory = root / name
            if directory.is_dir():
                ctx.copy(directory, f"usr/plugins/{name}")


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
        if opts.update_information:
            errors.extend(tool_missing("zsyncmake"))
        for plugin in opts.plugins:
            errors.extend(tool_missing(f"linuxdeploy-plugin-{plugin}"))
        if opts.runtime_file is not None and not ctx.resolve_path(opts.runtime_file).is_file():
            errors.append(f"AppImage runtime file: {opts.runtime_file}")
        if opts.qt_platforms:
            errors.extend(tool_missing(dict(opts.environment).get("QMAKE", "qmake")))
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
        deploy_qt_platforms(ctx, opts)
        desktop = ctx.deploy_dir / f"usr/share/applications/{app.id}.desktop"
        desktop_check(desktop, ctx.executable_name, app.id)
        ctx.run(["desktop-file-validate", str(desktop)])
        args = [opts.linuxdeploy, "--appdir", str(ctx.deploy_dir),
                "--executable", str(ctx.deploy_dir / "usr/bin" / ctx.executable_name),
                "--desktop-file", str(desktop), "--icon-file", str(app.icon)]
        for pattern in opts.exclude_libraries:
            args.extend(["--exclude-library", pattern])
        if opts.qt_platforms:
            args.extend(["--deploy-deps-only", str(ctx.prefix_dir / "plugins")])
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
        filename = opts.filename or f"{app.name}-{app.version}-{ctx.target.arch}.AppImage"
        for key, value in {"name": app.name, "version": app.version, "arch": ctx.target.arch, "platform": "linux"}.items():
            filename = filename.replace("{" + key + "}", value)
        output = ctx.config.output / ctx.target.name / filename
        validate_elf(ctx.deploy_dir / "usr/bin" / ctx.executable_name, ctx.target.arch)
        if output.exists():
            raise SetupError(f"Output already exists: {output}")
        if opts.update_information and output.with_name(output.name + ".zsync").exists():
            raise SetupError("Requested zsync output already exists")
        args = [opts.appimagetool]
        if opts.update_information:
            args.extend(["--updateinformation", opts.update_information])
        if opts.runtime_file is not None:
            args.extend(["--runtime-file", str(ctx.resolve_path(opts.runtime_file))])
        ctx.run([*args, str(ctx.deploy_dir), str(output)],
                env={"ARCH": ctx.target.arch, "VERSION": app.version})
        result = [artifact(ctx, output, "appimage")]
        if opts.update_information:
            companion = output.with_name(output.name + ".zsync")
            if not companion.is_file():
                raise SetupError("appimagetool did not generate the requested .zsync companion")
            result.append(artifact(ctx, companion, "appimage.zsync"))
        return tuple(result)




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
    fields(opts, "linuxdeploy appimagetool plugins libraries environment dependency_dirs runtime_file qt_platforms exclude_libraries update_information filename", "options")
    environment = mapping(opts.get("environment", {}), "environment")
    dependency_dirs = strings(opts.get("dependency_dirs", []), "dependency_dirs")
    if any(Path(p).is_absolute() or ".." in Path(p).parts for p in dependency_dirs):
        raise SetupError("dependency_dirs must be relative to deployment root")
    platforms = strings(opts.get("qt_platforms", []), "qt_platforms")
    if set(platforms) - {"wayland", "xcb", "offscreen"}:
        raise SetupError("qt_platforms must contain wayland, xcb, or offscreen")
    if platforms and "qt" not in strings(opts.get("plugins", []), "plugins"):
        raise SetupError("qt_platforms requires plugins: [qt]")
    filename = "" if "filename" not in opts else string(opts["filename"], "filename")
    checked = filename
    for key in ("name", "version", "arch", "platform"):
        checked = checked.replace("{" + key + "}", "value")
    if filename and (not filename.endswith(".AppImage") or any(char in checked for char in '/\\{}\r\n\0')):
        raise SetupError("AppImage filename must be a .AppImage basename with only name/version/arch/platform placeholders")
    options = AppImageOptions(
        paths.tool(opts.get("linuxdeploy", "linuxdeploy"), "linuxdeploy"),
        paths.tool(opts.get("appimagetool", "appimagetool"), "appimagetool"),
        strings(opts.get("plugins", []), "plugins"),
        tuple(paths.resolve(p, "library") for p in sequence(opts.get("libraries", []), "libraries")),
        tuple((key, string(value, f"environment.{key}")) for key, value in environment.items()),
        dependency_dirs,
        None if opts.get("runtime_file") is None else paths.resolve(opts["runtime_file"], "runtime_file"),
        platforms, strings(opts.get("exclude_libraries", []), "exclude_libraries"),
        "" if "update_information" not in opts else string(opts["update_information"], "update_information"),
        filename,
    )
    return options
