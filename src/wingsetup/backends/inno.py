# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Deploy Windows Qt applications and generate Inno Setup or ZIP packages."""

from __future__ import annotations

import struct
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..core import BuildContext, PackageBackend, ProjectHooks, artifact
from ..model import Artifact, BackendOptions, SetupError
from ..validation import ConfigPaths, fields, strings, string, mapping
from .native import deploy_entry, native_check, output_path, safe_line


@dataclass(frozen=True)
class InnoOptions(BackendOptions):
    """Windows deployment tools, output formats, and optional ISS template."""

    #: Requested Windows output formats in generation order.
    formats: tuple[str, ...] = ("inno",)
    #: Qt deployment executable name or resolved path.
    windeployqt: str = "windeployqt"
    #: Inno Setup compiler executable name or resolved path.
    iscc: str = "ISCC.exe"
    #: Optional project-owned ISS template preserving application installation behavior.
    script: Path | None = None
    #: Additional arguments passed to windeployqt before the destination and entry point.
    qt_args: tuple[str, ...] = ("--release",)
    #: Optional compiler input icon, resolved relative to YAML rather than the payload.
    setup_icon: Path | None = None
    #: Inno directory expression; empty keeps the per-user default.
    default_dir: str = ""
    #: Explicit installer privilege policy, independent of its directory expression.
    privileges: Literal["lowest", "admin"] = "lowest"
    #: Stable installer AppId override; empty uses the shared application identifier.
    app_id: str = ""
    #: Additional single-line native [Setup] directives, excluding managed values.
    setup: tuple[tuple[str, str], ...] = ()
    #: Native Inno [Files] exclusion patterns; these do not filter the portable ZIP.
    file_excludes: tuple[str, ...] = ()
    #: Whether the default template creates a desktop shortcut.
    desktop_shortcut: bool = False


def parse_options(data: dict[str, object], paths: ConfigPaths) -> InnoOptions:
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
    fields(data, "formats windeployqt iscc script qt_args setup_icon default_dir privileges app_id setup file_excludes desktop_shortcut", "inno")
    formats = strings(data.get("formats", ["inno"]), "formats")
    if not formats or len(set(formats)) != len(formats) or set(formats) - {"inno", "zip"}:
        raise SetupError("Windows formats must be a unique nonempty subset of inno, zip")
    script = data.get("script")
    icon = data.get("setup_icon")
    privileges = data.get("privileges", "lowest")
    desktop = data.get("desktop_shortcut", False)
    if privileges not in ("lowest", "admin") or not isinstance(desktop, bool):
        raise SetupError("inno.privileges must be lowest/admin and desktop_shortcut must be boolean")
    setup = mapping(data.get("setup", {}), "inno.setup")
    reserved = {"appid", "appname", "appversion", "defaultdirname", "privilegesrequired",
                "setupiconfile", "outputdir", "outputbasefilename", "architecturesallowed", "architecturesinstallin64bitmode"}
    directives: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, value in setup.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]+", key) or key.lower() in reserved:
            raise SetupError(f"Use the dedicated option or ISS template instead of setup.{key}")
        if key.lower() in seen:
            raise SetupError(f"Duplicate Inno setup directive: {key}")
        seen.add(key.lower())
        text = safe_line(string(value, f"setup.{key}"), key)
        if key.lower() in {"licensefile", "infobeforefile", "infoafterfile", "wizardimagefile", "wizardsmallimagefile"} and not text.startswith("compiler:"):
            text = str(paths.resolve(text, key))
        directives.append((key, text))
    return InnoOptions(
        formats=formats, windeployqt=paths.tool(data.get("windeployqt", "windeployqt"), "windeployqt"),
        iscc=paths.tool(data.get("iscc", "ISCC.exe"), "iscc"),
        script=None if script is None else paths.resolve(script, "script"),
        qt_args=strings(data.get("qt_args", ["--release"]), "qt_args"),
        setup_icon=None if icon is None else paths.resolve(icon, "setup_icon"),
        default_dir="" if "default_dir" not in data else safe_line(string(data["default_dir"], "default_dir"), "default_dir"),
        privileges=privileges, app_id="" if "app_id" not in data else safe_line(string(data["app_id"], "app_id"), "app_id"),
        setup=tuple(directives), file_excludes=tuple(safe_line(value, "file_excludes") for value in strings(data.get("file_excludes", []), "file_excludes")),
        desktop_shortcut=desktop)


def setup_directives(ctx: BuildContext, opts: InnoOptions) -> str:
    """Render typed installer settings for the default or an opted-in ISS template.

    Args:
        ctx: Shared application identity and resolved payload context.
        opts: Validated installer customization options.

    Returns:
        Single-line [Setup] directives, without a section heading.

    Raises:
        SetupError: A requested icon is missing or a metadata value spans lines.
    """
    app = ctx.config.application
    architecture = "arm64" if ctx.target.arch == "aarch64" else "x64compatible"
    values = [("AppId", opts.app_id or app.id), ("AppName", app.name), ("AppVersion", app.version),
              ("DefaultDirName", opts.default_dir or f"{{localappdata}}\\Programs\\{app.name}"),
              ("PrivilegesRequired", opts.privileges), ("ArchitecturesAllowed", architecture),
              ("ArchitecturesInstallIn64BitMode", architecture), *opts.setup]
    if opts.setup_icon is not None:
        icon = ctx.resolve_path(opts.setup_icon)
        if not icon.is_file():
            raise SetupError(f"Missing Inno setup_icon: {icon}")
        values.append(("SetupIconFile", str(icon)))
    lines: list[str] = []
    for key, value in values:
        if value.startswith(("{build}/", "{source}/", "{work}/")):
            value = str(ctx.resolve_path(Path(value)))
        lines.append(f"{key}={safe_line(value, key)}")
    return "\n".join(lines) + "\n"


def validate_pe(path: Path, arch: str) -> None:
    """Check PE identity and target architecture.

    Require a PE executable whose machine identifier matches the target architecture.

    Args:
        path: File or directory path to inspect or process.
        arch: Normalized target architecture expected in the executable.

    Raises:
        SetupError: The file is not a PE executable or its machine identifier differs
            from the target.
    """
    with path.open("rb") as stream:
        header = stream.read(64)
        if len(header) < 64 or header[:2] != b"MZ":
            raise SetupError(f"Expected PE executable: {path}")
        stream.seek(struct.unpack_from("<I", header, 60)[0])
        signature = stream.read(6)
    if len(signature) != 6 or signature[:4] != b"PE\0\0" or struct.unpack_from("<H", signature, 4)[0] != {"x86_64": 0x8664, "aarch64": 0xAA64}[arch]:
        raise SetupError(f"PE architecture does not match {arch}: {path}")


class InnoBackend(PackageBackend):
    """Deploy Qt dependencies and emit Windows installers or portable archives."""

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Report native Windows, Qt deployment, and requested compiler requirements.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Unmet requirements as messages; an empty tuple means all checked
            requirements are satisfied.
        """
        opts = ctx.target.options
        assert isinstance(opts, InnoOptions)
        tools = (opts.windeployqt, opts.iscc) if "inno" in opts.formats else (opts.windeployqt,)
        errors = list(native_check(ctx, "Windows", tools))
        for path in (opts.script, opts.setup_icon):
            if path is not None and not str(path).startswith(("{build}/", "{work}/")) and not ctx.resolve_path(path).is_file():
                errors.append(f"Inno compiler input: {path}")
        return tuple(errors)

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Stage the application or recipe contents.

        Stage the Windows entry and resources, validate PE architecture, and deploy Qt.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            hooks: Trusted host project callbacks invoked at the backend-defined
                extension points.
        """
        deploy_entry(ctx, hooks)
        entry = ctx.app_dir / ctx.executable_name
        validate_pe(entry, ctx.target.arch)
        opts = ctx.target.options
        assert isinstance(opts, InnoOptions)
        ctx.run([opts.windeployqt, *opts.qt_args, "--dir", str(ctx.app_dir), str(entry)])

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Archive portable files and compile requested Inno Setup installers.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Completed output artifacts in the requested generation order.
        """
        opts = ctx.target.options
        assert isinstance(opts, InnoOptions)
        app = ctx.config.application
        validate_pe(ctx.app_dir / ctx.executable_name, ctx.target.arch)
        result: list[Artifact] = []
        for format_name in opts.formats:
            if format_name == "zip":
                output = output_path(ctx, "zip")
                with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(ctx.deploy_dir.rglob("*")):
                        if path.is_file():
                            archive.write(path, path.relative_to(ctx.deploy_dir))
                result.append(artifact(ctx, output, "zip"))
                continue
            output = output_path(ctx, "exe")
            script = ctx.work / "installer.iss"
            if opts.script is not None:
                # Project-owned templates retain tasks, translations and file associations.
                content = opts.script.read_text(encoding="utf-8-sig")
                customized = bool(opts.setup_icon or opts.default_dir or opts.app_id or opts.setup or opts.privileges != "lowest")
                if customized and "@SETUP_DIRECTIVES@" not in content:
                    raise SetupError("Custom ISS must include @SETUP_DIRECTIVES@ to consume installer options")
                if opts.file_excludes or opts.desktop_shortcut:
                    raise SetupError("Custom ISS owns [Files]/[Icons]; use target.exclude or template directives")
                content = content.replace("@SETUP_DIRECTIVES@", setup_directives(ctx, opts))
                for key, value in {"@PAYLOAD@": str(ctx.deploy_dir), "@APP_ID@": app.id,
                                   "@APP_NAME@": app.name, "@VERSION@": app.version,
                                   "@EXECUTABLE@": ctx.executable_name}.items():
                    content = content.replace(key, safe_line(value, key).replace('"', '""'))
            else:
                excluded = ""
                if opts.file_excludes:
                    patterns = ",".join(opts.file_excludes).replace('"', '""')
                    excluded = f'; Excludes: "{patterns}"'
                content = (
                    '[Setup]\n' + setup_directives(ctx, opts) +
                    '[Files]\n' + f'Source: "{ctx.deploy_dir}\\*"; DestDir: "{{app}}"; Flags: recursesubdirs createallsubdirs{excluded}\n'
                    '[Icons]\n' + f'Name: "{{group}}\\{app.name}"; Filename: "{{app}}\\{ctx.executable_name}"\n'
                )
                if opts.desktop_shortcut:
                    content += f'Name: "{{autodesktop}}\\{app.name}"; Filename: "{{app}}\\{ctx.executable_name}"\n'
            script.write_text(content, encoding="utf-8-sig")
            ctx.run([opts.iscc, f"/O{output.parent}", f"/F{output.stem}", str(script)])
            result.append(artifact(ctx, output, "inno"))
        return tuple(result)
