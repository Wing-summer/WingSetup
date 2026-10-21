# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Deploy private application trees and generate rootless Debian packages."""

from __future__ import annotations

import hashlib
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from ..core import BuildContext, PackageBackend, ProjectHooks, artifact, deploy_resources
from ..model import Artifact, BackendOptions, SetupError
from ..validation import ConfigPaths, fields, string, strings
from .common import deploy_linux_metadata, desktop_check, validate_elf
from .native import native_check, output_path, safe_line


@dataclass(frozen=True)
class DebOptions(BackendOptions):
    """Debian control metadata and optional maintainer-script directory."""

    #: Debian-compliant package name written to the control file.
    package_name: str
    #: Maintainer identity written to the control file.
    maintainer: str
    #: Explicit Debian dependency expressions; dependencies are not inferred.
    depends: tuple[str, ...] = ()
    #: Debian package section.
    section: str = "utils"
    #: Debian packaging revision appended to the upstream version.
    revision: str = "1"
    #: Optional directory containing additional control files or maintainer scripts.
    control_files: Path | None = None


def parse_options(data: dict[str, object], paths: ConfigPaths) -> DebOptions:
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
    fields(data, "package_name maintainer depends section revision control_files", "deb")
    name = string(data.get("package_name"), "deb.package_name")
    if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", name):
        raise SetupError("Invalid Debian package name")
    revision = string(data.get("revision", "1"), "revision")
    if not re.fullmatch(r"[A-Za-z0-9+.~]+", revision):
        raise SetupError("Invalid Debian revision")
    control = data.get("control_files")
    return DebOptions(name, safe_line(string(data.get("maintainer"), "maintainer"), "maintainer"),
                      tuple(safe_line(value, "depends") for value in strings(data.get("depends", []), "depends")),
                      safe_line(string(data.get("section", "utils"), "section"), "section"), revision,
                      None if control is None else paths.resolve(control, "control_files"))


class DebBackend(PackageBackend):
    """Deploy a private application tree and generate a root-owned Debian archive."""

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Report native Linux and Debian packaging tool requirements.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Unmet requirements as messages; an empty tuple means all checked
            requirements are satisfied.
        """
        return native_check(ctx, "Linux", ("dpkg-deb", "desktop-file-validate"))

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Stage the application or recipe contents.

        Stage private application files, Linux metadata, and the public executable launcher.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            hooks: Trusted host project callbacks invoked at the backend-defined
                extension points.
        """
        ctx.copy_app(ctx.executable, ctx.executable_name)
        deploy_linux_metadata(ctx, "usr/")
        deploy_resources(ctx)
        hooks.deploy(ctx)
        validate_elf(ctx.app_dir / ctx.executable_name, ctx.target.arch)
        desktop = ctx.deploy_dir / "usr/share/applications" / f"{ctx.config.application.id}.desktop"
        desktop_check(desktop, ctx.executable_name, ctx.config.application.id)
        ctx.run(["desktop-file-validate", str(desktop)])
        launcher = ctx.prefix_dir / "bin" / ctx.executable_name
        launcher.parent.mkdir(parents=True, exist_ok=True)
        installed = "/" + (ctx.app_dir / ctx.executable_name).relative_to(ctx.deploy_dir).as_posix()
        launcher.write_text(f'#!/bin/sh\nexec {shlex.quote(installed)} "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Create final packaging artifacts.

        Write Debian control metadata and per-file checksums, then build without root privileges.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Completed output artifacts in the requested generation order.

        Raises:
            SetupError: The upstream version is invalid or Debian package generation
                fails.
        """
        opts = ctx.target.options
        assert isinstance(opts, DebOptions)
        app = ctx.config.application
        if not re.fullmatch(r"[0-9][A-Za-z0-9.+:~\-]*", app.version):
            raise SetupError("Invalid Debian upstream version")
        control = ctx.deploy_dir / "DEBIAN"
        control.mkdir(exist_ok=True)
        if opts.control_files:
            ctx.copy(opts.control_files, "DEBIAN")
        arch = {"x86_64": "amd64", "aarch64": "arm64"}[ctx.target.arch]
        lines = [f"Package: {opts.package_name}", f"Version: {app.version}-{opts.revision}",
                 f"Architecture: {arch}", f"Maintainer: {opts.maintainer}",
                 f"Section: {opts.section}", "Priority: optional",
                 f"Description: {safe_line(app.summary, 'summary')}"]
        if opts.depends:
            lines.append("Depends: " + ", ".join(opts.depends))
        (control / "control").write_text("\n".join(lines) + "\n", encoding="utf-8")
        sums: list[str] = []
        for path in sorted(ctx.deploy_dir.rglob("*")):
            if path.is_file() and not path.is_symlink() and not path.is_relative_to(control):
                with path.open("rb") as stream:
                    sums.append(f"{hashlib.file_digest(stream, 'md5').hexdigest()}  {path.relative_to(ctx.deploy_dir).as_posix()}")
        (control / "md5sums").write_text("\n".join(sums) + "\n", encoding="utf-8")
        for name in ("preinst", "postinst", "prerm", "postrm", "config"):
            script = control / name
            if script.exists():
                script.chmod(0o755)
        output = output_path(ctx, "deb")
        # dpkg-deb records root ownership without fakeroot or privilege escalation.
        ctx.run(["dpkg-deb", "--root-owner-group", "--build", str(ctx.deploy_dir), str(output)])
        return (artifact(ctx, output, "deb"),)
