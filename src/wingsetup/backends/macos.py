# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Deploy Qt application bundles and create signed macOS archives."""

from __future__ import annotations

import os
import json
import plistlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ..core import BuildContext, PackageBackend, ProjectHooks, artifact, deploy_resources
from ..installation import apply_installation
from ..model import Artifact, BackendOptions, SetupError
from ..platforms import normalize_arch
from ..validation import ConfigPaths, fields, strings, mapping
from .native import native_check, output_path, relative_path


@dataclass(frozen=True)
class MacOSOptions(BackendOptions):
    """macOS output formats, extra code, and optional signing credentials."""

    #: Requested macOS output formats in generation order.
    formats: tuple[str, ...] = ("zip", "dmg")
    #: Qt macOS deployment executable name or resolved path.
    macdeployqt: str = "macdeployqt"
    #: Bundle-relative private libraries or plugins requiring dependency deployment and signing.
    extra_executables: tuple[str, ...] = ()
    #: Environment variable containing the signing identity; empty selects ad-hoc signing.
    sign_identity_env: str = ""
    #: Environment variable containing a preconfigured notarytool keychain profile.
    notary_profile_env: str = ""
    #: Additional macdeployqt flags such as -no-plugins or -no-strip.
    qt_args: tuple[str, ...] = ()


def parse_options(data: dict[str, object], paths: ConfigPaths) -> MacOSOptions:
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
    fields(data, "formats macdeployqt extra_executables sign_identity_env notary_profile_env qt_args", "macos")
    formats = strings(data.get("formats", ["zip", "dmg"]), "formats")
    if not formats or len(set(formats)) != len(formats) or set(formats) - {"app", "zip", "dmg"}:
        raise SetupError("macOS formats must be a unique nonempty subset of app, zip, dmg")
    sign = data.get("sign_identity_env", "")
    notary = data.get("notary_profile_env", "")
    if not isinstance(sign, str) or not isinstance(notary, str) or (notary and not sign):
        raise SetupError("notary_profile_env requires sign_identity_env")
    qt_args = strings(data.get("qt_args", []), "qt_args")
    managed = ("-codesign", "-sign-for-notarization", "-no-codesign", "-executable", "-dmg")
    if any(value.split("=", 1)[0] in managed for value in qt_args):
        raise SetupError("macos.qt_args cannot override managed signing, executables, or output formats")
    return MacOSOptions(formats, paths.tool(data.get("macdeployqt", "macdeployqt"), "macdeployqt"),
                        tuple(relative_path(value) for value in strings(data.get("extra_executables", []), "extra_executables")),
                        sign, notary, qt_args)


def credential(name: str) -> str:
    """Read a signing identity or profile from the environment.

    Read a nonempty, single-line signing identity or keychain profile from the environment.

    Args:
        name: Environment variable naming the signing identity or keychain profile.

    Returns:
        Validated value of the requested environment variable.

    Raises:
        SetupError: The environment variable is empty, missing, or contains a line
            break.
    """
    value = os.environ.get(name, "")
    if not value or "\n" in value or "\r" in value:
        raise SetupError(f"Required signing environment variable is missing or invalid: {name}")
    return value


class MacOSBackend(PackageBackend):
    """Use Qt/Apple deployment tools on macOS; credentials stay in the CI keychain."""

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Report unmet packaging requirements.

        Report native Apple tools and explicitly requested signing credential requirements.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Unmet requirements as messages; an empty tuple means all checked
            requirements are satisfied.
        """
        opts = ctx.target.options
        assert isinstance(opts, MacOSOptions)
        tools = [opts.macdeployqt, "lipo", "ditto", "codesign"]
        if "dmg" in opts.formats:
            tools.append("hdiutil")
        if opts.notary_profile_env:
            tools.append("xcrun")
        errors = list(native_check(ctx, "Darwin", tuple(tools)))
        for name in (opts.sign_identity_env, opts.notary_profile_env):
            if name and not os.environ.get(name):
                errors.append(f"Required CI environment variable: {name}")
        return tuple(errors)

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Stage the application or recipe contents.

        Preserve bundle links, apply resources, validate identity and architecture, and deploy and sign Qt code.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            hooks: Trusted host project callbacks invoked at the backend-defined
                extension points.

        Raises:
            SetupError: The bundle, identity, architecture, extra code, or requested
                signing identity is invalid.
        """
        opts = ctx.target.options
        assert isinstance(opts, MacOSOptions)
        bundle = ctx.layout.bundle
        assert bundle is not None
        source = ctx.executable
        if source.suffix != ".app" or not source.is_dir():
            raise SetupError(f"Expected a built .app bundle: {source}")
        for path in source.rglob("*"):
            if path.is_symlink() and not path.resolve().is_relative_to(source.resolve()):
                raise SetupError(f"Bundle contains external symlink: {path}")
        # Framework version symlinks must survive copying and zip creation.
        shutil.copytree(source, bundle, symlinks=True)
        deploy_resources(ctx)
        hooks.deploy(ctx)
        apply_installation(ctx)
        info = cast(dict[str, object], plistlib.loads((bundle / "Contents/Info.plist").read_bytes()))
        if info.get("CFBundleIdentifier") != ctx.config.application.id or info.get("CFBundleExecutable") != ctx.executable_name:
            raise SetupError("Bundle identity or executable does not match configuration")
        architectures = ctx.run(["lipo", "-archs", str(ctx.app_dir / ctx.executable_name)]).split()
        required = {"x86_64", "aarch64"} if ctx.target.arch == "universal2" else {ctx.target.arch}
        if not required.issubset({normalize_arch(value) for value in architectures}):
            raise SetupError("Mach-O architectures do not match the target")
        args = [opts.macdeployqt, str(bundle), "-always-overwrite", *opts.qt_args]
        for name in opts.extra_executables:
            path = bundle / name
            if not path.is_file() or not path.resolve().is_relative_to(bundle.resolve()):
                raise SetupError(f"Missing or unsafe extra executable: {name}")
            args.append(f"-executable={path}")
        if opts.sign_identity_env:
            identity = credential(opts.sign_identity_env)
            if opts.notary_profile_env and identity == "-":
                raise SetupError("Notarization requires a Developer ID identity, not ad-hoc signing")
            args.append(f"-sign-for-notarization={identity}" if opts.notary_profile_env else f"-codesign={identity}")
        else:
            args.append("-codesign=-")
        ctx.run(args)

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Create final packaging artifacts.

        Verify signatures, optionally notarize, and create symlink-preserving ZIP or DMG outputs.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Completed output artifacts in the requested generation order.
        """
        opts = ctx.target.options
        assert isinstance(opts, MacOSOptions)
        bundle = ctx.layout.bundle
        assert bundle is not None
        # Qt may not identify custom plugin extensions; sign them before the bundle.
        identity = credential(opts.sign_identity_env) if opts.sign_identity_env else "-"
        signing = ["codesign", "--force", "--sign", identity]
        if identity != "-":
            signing.extend(["--options", "runtime", "--timestamp"])
        for name in opts.extra_executables:
            ctx.run([*signing, str(bundle / name)])
        ctx.run([*signing, str(bundle)])

        ctx.run(["codesign", "--verify", "--deep", "--strict", str(bundle)])
        if opts.notary_profile_env:
            submission = ctx.work / "notarization.zip"
            ctx.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(bundle), str(submission)])
            self.notarize(ctx, submission, bundle)
        result: list[Artifact] = []
        for format_name in opts.formats:
            if format_name == "app":
                # A .app is a directory; distribute it as a symlink-preserving zip.
                output = output_path(ctx, "app.zip")
            else:
                output = output_path(ctx, format_name)
            if format_name in ("app", "zip"):
                ctx.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(bundle), str(output)])
            else:
                folder = ctx.work / "dmg-root"
                folder.mkdir(exist_ok=True)
                shutil.copytree(bundle, folder / bundle.name, symlinks=True)
                (folder / "Applications").symlink_to("/Applications", target_is_directory=True)
                ctx.run(["hdiutil", "create", "-volname", ctx.config.application.name, "-srcfolder",
                         str(folder), "-format", "UDZO", "-fs", "HFS+", str(output)])
                if opts.sign_identity_env:
                    ctx.run(["codesign", "--force", "--timestamp", "--sign", credential(opts.sign_identity_env), str(output)])
                if opts.notary_profile_env:
                    self.notarize(ctx, output, output)
            result.append(artifact(ctx, output, "app.zip" if format_name == "app" else format_name))
        return tuple(result)

    def notarize(self, ctx: BuildContext, archive: Path, staple_target: Path) -> None:
        """Submit an archive, require acceptance, and staple and validate its ticket.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            archive: Archive submitted to Apple notarization.
            staple_target: Application bundle or DMG receiving and validating the
                accepted ticket.

        Raises:
            SetupError: The service response is invalid or rejected, or submission or
                stapling fails.
        """
        opts = ctx.target.options
        assert isinstance(opts, MacOSOptions)
        response = ctx.run(["xcrun", "notarytool", "submit", str(archive), "--keychain-profile",
                            credential(opts.notary_profile_env), "--wait", "--output-format", "json"])
        try:
            result = mapping(cast(object, json.loads(response)), "notarytool response")
        except (ValueError, SetupError) as exc:
            raise SetupError("Invalid notarization response") from exc
        if result.get("status") != "Accepted":
            raise SetupError(f"Notarization was not accepted: {result.get('status')}")
        ctx.run(["xcrun", "stapler", "staple", str(staple_target)])
        ctx.run(["xcrun", "stapler", "validate", str(staple_target)])
