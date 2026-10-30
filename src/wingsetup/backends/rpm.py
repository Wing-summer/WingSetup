# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Package staged Linux applications using an isolated, unprivileged rpmbuild tree."""

from __future__ import annotations

import re
import shlex
import shutil
from dataclasses import dataclass

from ..core import Artifact, BuildContext, PackageBackend, ProjectHooks, artifact
from ..model import BackendOptions, SetupError
from ..validation import ConfigPaths, fields, string, strings
from .common import binary_deploy, desktop_check
from .native import native_check, output_path, safe_line


@dataclass(frozen=True)
class RpmOptions(BackendOptions):
    """RPM identity and explicitly declared package relationships."""

    #: Distribution package name, independent of the application display name.
    package_name: str
    #: RPM release appended to the upstream version.
    release: str = "1"
    #: Optional native RPM dependency expressions.
    depends: tuple[str, ...] = ()
    #: Optional project URL written into RPM metadata.
    url: str = ""


def parse_options(data: dict[str, object], paths: ConfigPaths) -> RpmOptions:
    """Validate RPM metadata without executing tools or loading project hooks.

    Args:
        data: Untrusted YAML backend options.
        paths: Configuration-relative path resolver reserved for future file options.

    Returns:
        Immutable RPM options.

    Raises:
        SetupError: An unknown field or invalid metadata value is supplied.
    """
    fields(data, "package_name release depends url", "rpm")
    name = string(data.get("package_name"), "rpm.package_name")
    release = string(data.get("release", "1"), "rpm.release")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9+._-]*", name):
        raise SetupError("Invalid RPM package name")
    if not re.fullmatch(r"[a-zA-Z0-9+._]+", release):
        raise SetupError("Invalid RPM release")
    return RpmOptions(name, release,
                      tuple(safe_line(item, "rpm.depends") for item in strings(data.get("depends", []), "rpm.depends")),
                      safe_line((string(data["url"], "rpm.url") if "url" in data else ""), "rpm.url"))


def rpm_text(value: str) -> str:
    """Escape literal metadata so RPM cannot expand user-supplied macros.

    Args:
        value: Single-line metadata or a generated pathname.

    Returns:
        Text preserving literal percent signs in a spec file.
    """
    return safe_line(value, "RPM value").replace("%", "%%")


class RpmBackend(PackageBackend):
    """Build a binary RPM without installing it or invoking a system package manager."""

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Report Linux architecture and required packaging tools.

        Args:
            ctx: Target-local context used for dependency inspection.

        Returns:
            Missing native tools and environment requirements.
        """
        return native_check(ctx, "Linux", ("rpmbuild", "rpmdb", "desktop-file-validate"))

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Stage the executable, resources, and Linux desktop metadata under /usr.

        Args:
            ctx: Target-local staged filesystem and application metadata.
            hooks: Project deployment extensions executed after generic copying.
        """
        binary_deploy(ctx, hooks, "usr/")
        desktop = ctx.deploy_dir / "usr/share/applications" / f"{ctx.config.application.id}.desktop"
        desktop_check(desktop, ctx.executable_name, ctx.config.application.id)
        ctx.run(["desktop-file-validate", str(desktop)])

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Build one binary RPM from staging using a target-private spec and buildroot.

        Args:
            ctx: Completed staged payload and validated package configuration.

        Returns:
            RPM artifact and its SHA-256 digest.

        Raises:
            SetupError: Metadata is incompatible with RPM or the expected RPM is absent.
        """
        opts = ctx.target.options
        assert isinstance(opts, RpmOptions)
        app = ctx.config.application
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+~^]*", app.version):
            raise SetupError("Invalid RPM upstream version")
        top = ctx.work / "rpmbuild"
        for name in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
            (top / name).mkdir(parents=True, exist_ok=True)
        # Enumerate files rather than owning shared directories such as /usr/bin.
        files: list[str] = []
        for path in sorted(ctx.deploy_dir.rglob("*")):
            if path.is_file() or path.is_symlink():
                relative = "/" + path.relative_to(ctx.deploy_dir).as_posix()
                if any(char in relative for char in ('"', "\\", "\n", "\r")):
                    raise SetupError(f"Unsupported RPM payload pathname: {relative}")
                files.append('"' + rpm_text(relative) + '"')
        lines = ["%global debug_package %{nil}", "%global __os_install_post %{nil}",
                 f"Name: {opts.package_name}", f"Version: {app.version}", f"Release: {opts.release}",
                 f"Summary: {rpm_text(app.summary)}", f"License: {rpm_text(app.license)}",
                 f"BuildArch: {ctx.target.arch}"]
        if opts.url:
            lines.append(f"URL: {rpm_text(opts.url)}")
        lines += [f"Requires: {rpm_text(value)}" for value in opts.depends]
        lines += ["", "%description", rpm_text(app.summary), "", "%install",
                  "mkdir -p \"%{buildroot}\"",
                  "cp -a " + rpm_text(shlex.quote(str(ctx.deploy_dir) + "/.")) + ' "%{buildroot}/"',
                  "", "%files", "%defattr(-,root,root,-)", *files, ""]
        spec = top / "SPECS" / f"{opts.package_name}.spec"
        spec.write_text("\n".join(lines), encoding="utf-8")
        database = top / "rpmdb"
        database.mkdir()
        ctx.run(["rpmdb", "--dbpath", str(database), "--initdb"])
        # RPM 4 output remains readable by older distro RPM and libarchive releases.
        ctx.run(["rpmbuild", "-bb", "--target", ctx.target.arch,
                 "--define", f"_topdir {top}", "--define", f"_dbpath {database}",
                 "--define", "_rpmformat 4", "--define", "_build_id_links none", str(spec)])
        packages = tuple((top / "RPMS").rglob("*.rpm"))
        if len(packages) != 1:
            raise SetupError(f"Expected one RPM, found {len(packages)}")
        output = output_path(ctx, "rpm")
        shutil.copy2(packages[0], output)
        return (artifact(ctx, output, "rpm"),)
