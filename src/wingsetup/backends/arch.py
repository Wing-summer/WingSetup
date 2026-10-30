# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Build installable Arch packages from staged binaries using makepkg and fakeroot."""

from __future__ import annotations

import hashlib
import os
import sys
import re
import shlex
import shutil
import tarfile
from dataclasses import dataclass

from ..core import Artifact, BuildContext, PackageBackend, ProjectHooks, artifact
from ..model import BackendOptions, SetupError
from ..validation import ConfigPaths, fields, string, strings
from .common import binary_deploy, desktop_check
from .native import native_check, output_path, safe_line


@dataclass(frozen=True)
class ArchOptions(BackendOptions):
    """Arch package identity and explicit binary-package dependencies."""

    #: Pacman package name written into PKGBUILD and .PKGINFO.
    package_name: str
    #: Arch package release number.
    release: str = "1"
    #: Explicit pacman dependency expressions, not automatically installed.
    depends: tuple[str, ...] = ()
    #: Project home page for package metadata.
    url: str = ""


def parse_options(data: dict[str, object], paths: ConfigPaths) -> ArchOptions:
    """Validate Arch metadata before constructing a package backend.

    Args:
        data: Untrusted YAML backend options.
        paths: Resolver reserved for future configuration-relative file options.

    Returns:
        Immutable Arch binary packaging options.

    Raises:
        SetupError: Options contain unknown fields or invalid package metadata.
    """
    fields(data, "package_name release depends url", "arch")
    name = string(data.get("package_name"), "arch.package_name")
    release = string(data.get("release", "1"), "arch.release")
    if not re.fullmatch(r"[a-z0-9@_+][a-z0-9@._+-]*", name):
        raise SetupError("Invalid Arch package name")
    if not re.fullmatch(r"[1-9][0-9]*(?:\.[0-9]+)?", release):
        raise SetupError("Invalid Arch package release")
    return ArchOptions(name, release,
                       tuple(safe_line(item, "arch.depends") for item in strings(data.get("depends", []), "arch.depends")),
                       safe_line((string(data["url"], "arch.url") if "url" in data else ""), "arch.url"))


class ArchBackend(PackageBackend):
    """Create a real .pkg.tar.zst binary package, distinct from an AUR recipe."""

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Report makepkg requirements and reject privileged package assembly.

        Args:
            ctx: Native Linux target and dependency inspection context.

        Returns:
            Missing requirements, including root execution where applicable.
        """
        errors = list(native_check(ctx, "Linux", ("makepkg", "fakeroot", "bsdtar", "zstd", "desktop-file-validate")))
        # Pyright narrows platform-specific os APIs using sys.platform guards.
        if sys.platform == "linux" and os.geteuid() == 0:
            errors.append("makepkg must run as an unprivileged user")
        return tuple(errors)

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Stage Linux application files and project deployment extensions.

        Args:
            ctx: Target-local /usr layout and application metadata.
            hooks: Trusted project deployment extensions.
        """
        binary_deploy(ctx, hooks, "usr/")
        desktop = ctx.deploy_dir / "usr/share/applications" / f"{ctx.config.application.id}.desktop"
        desktop_check(desktop, ctx.executable_name, ctx.config.application.id)
        ctx.run(["desktop-file-validate", str(desktop)])

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Generate a local PKGBUILD and assemble the staged binary without network use.

        Args:
            ctx: Completed staged payload and validated metadata.

        Returns:
            One .pkg.tar.zst artifact and its checksum.

        Raises:
            SetupError: The version is invalid or makepkg omits the expected package.
        """
        opts = ctx.target.options
        assert isinstance(opts, ArchOptions)
        app = ctx.config.application
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+]*", app.version):
            raise SetupError("Invalid Arch upstream version")
        work = ctx.work / "makepkg"
        work.mkdir()
        payload = work / "payload.tar"
        with tarfile.open(payload, "w") as archive:
            archive.add(ctx.deploy_dir, arcname="payload")
        with payload.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        quote = shlex.quote
        lines = [f"pkgname={quote(opts.package_name)}", f"pkgver={quote(app.version)}", f"pkgrel={opts.release}",
                 f"pkgdesc={quote(safe_line(app.summary, 'summary'))}", f"arch=({quote(ctx.target.arch)})",
                 f"license=({quote(safe_line(app.license, 'license'))})", f"url={quote(opts.url)}",
                 "depends=(" + " ".join(quote(item) for item in opts.depends) + ")",
                 "options=('!strip' '!debug' 'libtool' 'staticlibs' 'emptydirs' '!zipman' '!purge')", "source=('payload.tar')", f"sha256sums=('{digest}')",
                 "package() {", '    cp -a "$srcdir/payload/." "$pkgdir/"', "}", ""]
        (work / "PKGBUILD").write_text("\n".join(lines), encoding="utf-8")
        packages = work / "packages"
        packages.mkdir()
        config = work / "makepkg.conf"
        config.write_text("source /etc/makepkg.conf\nPKGEXT='.pkg.tar.zst'\nPKGDEST=" + quote(str(packages)) + "\n", encoding="utf-8")
        # No --syncdeps or --install: package creation never mutates the host.
        ctx.run(["makepkg", "--config", str(config), "--nodeps", "--noconfirm", "--cleanbuild"], cwd=work)
        outputs = tuple(packages.glob("*.pkg.tar.zst"))
        if len(outputs) != 1:
            raise SetupError(f"Expected one Arch package, found {len(outputs)}")
        output = output_path(ctx, "pkg.tar.zst")
        shutil.copy2(outputs[0], output)
        return (artifact(ctx, output, "pkg.tar.zst"),)
