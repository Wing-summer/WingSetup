# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Deploy Windows Qt applications and generate Inno Setup or ZIP packages."""

from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..core import BuildContext, PackageBackend, ProjectHooks, artifact
from ..model import Artifact, BackendOptions, SetupError
from ..validation import ConfigPaths, fields, strings
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
    fields(data, "formats windeployqt iscc script qt_args", "inno")
    formats = strings(data.get("formats", ["inno"]), "formats")
    if not formats or len(set(formats)) != len(formats) or set(formats) - {"inno", "zip"}:
        raise SetupError("Windows formats must be a unique nonempty subset of inno, zip")
    script = data.get("script")
    return InnoOptions(formats, paths.tool(data.get("windeployqt", "windeployqt"), "windeployqt"),
                       paths.tool(data.get("iscc", "ISCC.exe"), "iscc"),
                       None if script is None else paths.resolve(script, "script"),
                       strings(data.get("qt_args", ["--release"]), "qt_args"))


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
        return native_check(ctx, "Windows", tools)

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
                for key, value in {"@PAYLOAD@": str(ctx.deploy_dir), "@APP_ID@": app.id,
                                   "@APP_NAME@": app.name, "@VERSION@": app.version,
                                   "@EXECUTABLE@": ctx.executable_name}.items():
                    content = content.replace(key, safe_line(value, key).replace('"', '""'))
            else:
                architecture = "arm64" if ctx.target.arch == "aarch64" else "x64compatible"
                content = (
                    '[Setup]\n' + f'AppId={app.id}\nAppName={app.name}\nAppVersion={app.version}\n'
                    f'DefaultDirName={{localappdata}}\\Programs\\{app.name}\nPrivilegesRequired=lowest\n'
                    f'ArchitecturesAllowed={architecture}\nArchitecturesInstallIn64BitMode={architecture}\n'
                    '[Files]\n' + f'Source: "{ctx.deploy_dir}\\*"; DestDir: "{{app}}"; Flags: recursesubdirs createallsubdirs\n'
                    '[Icons]\n' + f'Name: "{{group}}\\{app.name}"; Filename: "{{app}}\\{ctx.executable_name}"\n'
                )
            script.write_text(content, encoding="utf-8-sig")
            ctx.run([opts.iscc, f"/O{output.parent}", f"/F{output.stem}", str(script)])
            result.append(artifact(ctx, output, "inno"))
        return tuple(result)
