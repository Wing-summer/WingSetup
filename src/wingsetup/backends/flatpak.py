# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Build Flatpak applications from host binaries or SDK manifests."""

from __future__ import annotations

import re

from ..validation import read_yaml
from ..core import BuildContext, PackageBackend, ProjectHooks, artifact, deploy_resources, tool_missing
from ..model import Artifact, FlatpakOptions, SetupError
from ..validation import ConfigPaths, fields, string, strings
from .common import binary_deploy, common_check, desktop_check, validate_elf


def flatpak_options(ctx: BuildContext) -> FlatpakOptions:
    """Return typed Flatpak options or reject a mismatched target.

    Args:
        ctx: Target-local configuration, paths, and command execution services.

    Returns:
        Validated options of the backend-specific type.

    Raises:
        SetupError: The target does not contain FlatpakOptions.
    """
    options = ctx.target.options
    if not isinstance(options, FlatpakOptions):
        raise SetupError("Flatpak options required")
    return options


class FlatpakBackend(PackageBackend):
    """Keep host binary imports separate from manifest-driven SDK builds."""

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Report unmet packaging requirements.

        Report Flatpak tools and installed runtime requirements, validating SDK manifests.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Unmet requirements as messages; an empty tuple means all checked
            requirements are satisfied.
        """
        opts = flatpak_options(ctx)
        errors = list(common_check(ctx))
        errors.extend(tool_missing("flatpak"))
        if opts.mode == "sdk":
            errors.extend(tool_missing("flatpak-builder"))
            self.validate_manifest(ctx)
        errors.extend(tool_missing("desktop-file-validate"))
        if not tool_missing("flatpak"):
            for runtime in (opts.runtime, opts.sdk):
                ref = f"{runtime}/{ctx.target.arch}/{opts.runtime_version}"
                try:
                    ctx.run(["flatpak", "info", f"--{opts.installation}", ref])
                except SetupError:
                    errors.append(f"Flatpak {opts.installation} ref: {ref} (install manually)")
        return tuple(errors)

    def validate_manifest(self, ctx: BuildContext) -> None:
        """Check manifest consistency with the target configuration.

        Reject manifest identity, runtime, command, or architecture drift from YAML.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Raises:
            SetupError: The manifest is missing or its identity, runtime, command, or
                architecture differs.
        """
        opts = flatpak_options(ctx)
        if opts.manifest is None:
            raise SetupError("Manifest required")
        manifest = read_yaml(opts.manifest)
        actual_id = manifest.get("app-id", manifest.get("id"))
        expected: dict[str, object] = {
            "runtime": opts.runtime, "sdk": opts.sdk,
            "runtime-version": opts.runtime_version,
            "command": ctx.executable_name,
        }
        if actual_id != ctx.config.application.id:
            raise SetupError("Manifest application ID does not match YAML")
        for key, value in expected.items():
            if manifest.get(key) != value:
                raise SetupError(f"Manifest {key} must equal {value!r}")
        if "arch" in manifest and manifest["arch"] != ctx.target.arch:
            raise SetupError("Manifest architecture does not match target")

    def prepare(self, ctx: BuildContext) -> None:
        """Check requirements and initialize a binary-mode Flatpak build directory.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
        """
        super().prepare(ctx)
        opts = flatpak_options(ctx)
        if opts.mode == "binary":
            ctx.run(["flatpak", "build-init",
                     f"--arch={ctx.target.arch}", str(ctx.deploy_dir),
                     ctx.config.application.id, opts.sdk, opts.runtime, opts.runtime_version])

    def builder_args(self, ctx: BuildContext) -> list[str]:
        """Compose shared flatpak-builder arguments for this isolated SDK run.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Argument prefix shared by SDK build and finish commands.

        Raises:
            SetupError: SDK mode has no manifest path.
        """
        opts = flatpak_options(ctx)
        if opts.manifest is None:
            raise SetupError("Manifest required")
        return ["flatpak-builder", "--disable-rofiles-fuse", f"--{opts.installation}", f"--arch={ctx.target.arch}",
                f"--default-branch={opts.branch}",
                f"--state-dir={ctx.work / 'builder-state'}"]

    def build(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Perform the backend or project build extension.

        Build through the SDK manifest or run the host project build for binary mode.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            hooks: Trusted host project callbacks invoked at the backend-defined
                extension points.
        """
        opts = flatpak_options(ctx)
        if opts.mode == "binary":
            super().build(ctx, hooks)
        else:
            # Compilation belongs to the SDK; never run the host build callback.
            ctx.run([*self.builder_args(ctx), "--build-only", str(ctx.deploy_dir),
                     str(opts.manifest)])

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Stage the application or recipe contents.

        Apply project resources and finish the Flatpak tree with explicit permissions.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            hooks: Trusted host project callbacks invoked at the backend-defined
                extension points.
        """
        opts = flatpak_options(ctx)
        app = ctx.config.application
        if opts.mode == "binary":
            binary_deploy(ctx, hooks, "files/")
        else:
            deploy_resources(ctx)
            hooks.deploy(ctx)
        desktop = ctx.deploy_dir / f"files/share/applications/{app.id}.desktop"
        desktop_check(desktop, ctx.executable_name, app.id)
        ctx.run(["desktop-file-validate", str(desktop)])
        validate_elf(ctx.deploy_dir / "files/bin" / ctx.executable_name, ctx.target.arch)
        if opts.mode == "binary":
            ctx.run(["flatpak", "build-finish", f"--command={ctx.executable_name}",
                     *opts.finish_args, str(ctx.deploy_dir)])
        else:
            ctx.run([*self.builder_args(ctx), "--finish-only", str(ctx.deploy_dir),
                     str(opts.manifest)])

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Create final packaging artifacts.

        Export the application to a local repository and generate a Flatpak bundle.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Completed output artifacts in the requested generation order.

        Raises:
            SetupError: The output already exists or executable validation or package
                generation fails.
        """
        opts = flatpak_options(ctx)
        app = ctx.config.application
        output = ctx.config.output / ctx.target.name / f"{app.name}-{app.version}-{ctx.target.arch}.flatpak"
        if output.exists():
            raise SetupError(f"Output already exists: {output}")
        validate_elf(ctx.deploy_dir / "files/bin" / ctx.executable_name, ctx.target.arch)
        repo = ctx.work / "repository"
        ctx.run(["flatpak", "build-export", f"--arch={ctx.target.arch}",
                 str(repo), str(ctx.deploy_dir), opts.branch])
        ctx.run(["flatpak", "build-bundle", f"--arch={ctx.target.arch}", str(repo),
                 str(output), app.id, opts.branch])
        return (artifact(ctx, output, "flatpak"),)


def parse_options(opts: dict[str, object], paths: ConfigPaths) -> FlatpakOptions:
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
    fields(opts, "mode runtime sdk runtime_version branch finish_args manifest installation", "options")
    mode = opts.get("mode", "binary")
    installation = opts.get("installation", "user")
    if mode not in ("binary", "sdk") or installation not in ("user", "system"):
        raise SetupError("Invalid Flatpak mode or installation")
    manifest = opts.get("manifest")
    options = FlatpakOptions(
        mode, string(opts.get("runtime"), "runtime"),
        string(opts.get("sdk"), "sdk"), string(opts.get("runtime_version"), "runtime_version"),
        string(opts.get("branch", "stable"), "branch"),
        strings(opts.get("finish_args", []), "finish_args"),
        None if manifest is None else paths.resolve(manifest, "manifest"),
        installation,
    )
    if mode == "sdk" and options.manifest is None:
        raise SetupError("Flatpak sdk mode requires manifest")
    if mode == "sdk" and options.finish_args:
        raise SetupError("SDK mode: configure finish-args in the manifest")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", options.branch):
        raise SetupError("Invalid Flatpak branch")
    return options
