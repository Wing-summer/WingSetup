# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Verify packaging framework behavior with isolated temporary fixtures."""

from __future__ import annotations

import dataclasses
import json
import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from typing import Mapping, Sequence
from unittest.mock import patch

from wingsetup import BuildContext, CommandRunner, ProjectHooks, SetupError
from wingsetup.backends.aur import AurBackend
from wingsetup.backends.deb import DebBackend
from wingsetup.backends.inno import InnoBackend, validate_pe
from wingsetup.backends.macos import MacOSBackend
from wingsetup.backends.makeself import MakeselfBackend
from wingsetup.backends.script import ScriptBackend
from wingsetup.cli import main
from wingsetup.config import load_config
from wingsetup.core import check_requirements, run_target
from wingsetup.platforms import deployment_layout, normalize_arch


class NativeRunner(CommandRunner):
    """Replace native packaging tools, while exercising actual staging and metadata."""

    def __init__(self) -> None:
        """Initialize command recording or lifecycle trace state."""
        super().__init__()
        #: Recorded executable and argument tuples in invocation order.
        self.commands: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str], *, cwd: Path,
            env: Mapping[str, str] | None = None) -> str:
        """Record command arguments and simulate the external tool response.

        Args:
            args: Explicit executable and argument sequence to record.
            cwd: Working directory requested for the simulated command.
            env: Environment overrides requested for the simulated command.

        Returns:
            Simulated process output for the requested command.
        """
        self.commands.append(tuple(args))
        if args[0] == "lipo":
            return "x86_64 arm64\n"
        if tuple(args[:3]) == ("xcrun", "notarytool", "submit"):
            return '{"status":"Accepted"}'
        if args[0] == "makepkg":
            return "pkgbase = demo\n\tpkgver = 1.0\npkgname = demo\n"
        if args[0] in ("dpkg-deb", "ditto", "hdiutil"):
            Path(args[-1]).write_bytes(b"package")
        if args[0] == "ISCC.exe":
            directory = next(value[2:] for value in args if value.startswith("/O"))
            filename = next(value[2:] for value in args if value.startswith("/F"))
            (Path(directory) / (filename + ".exe")).write_bytes(b"installer")
        if args[0] == "makeself":
            Path(args[3]).write_bytes(b"#!/bin/sh\n")
        return ""


class BackendTests(unittest.TestCase):
    """Test native layouts and packaging arguments with simulated external tools."""

    def setUp(self) -> None:
        """Create temporary test inputs and register cleanup of generated files."""
        #: Temporary-directory owner registered for automatic test cleanup.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        #: Temporary root containing this test fixture and generated outputs.
        self.root = Path(self.tmp.name)
        #: Command simulator recording native backend requests.
        self.runner = NativeRunner()
        if os.name == "nt":
            # DMG staging is simulated on Windows, where symlink privileges differ.
            links = patch.object(Path, "symlink_to")
            links.start()
            self.addCleanup(links.stop)
        (self.root / "desktop.desktop").write_text("[Desktop Entry]\nType=Application\nName=Demo\nExec=demo\nIcon=org.example.Demo\n")
        (self.root / "icon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        elf = bytearray(64)
        elf[:6] = b"\x7fELF\x02\x01"
        elf[18:20] = (62).to_bytes(2, "little")
        (self.root / "demo").write_bytes(elf)
        (self.root / "demo").chmod(0o755)

    def context(self, backend: str, options: str, *, extra: str = "") -> BuildContext:
        """Construct a typed target context using temporary fixture paths.

        Args:
            backend: Built-in backend name used in the temporary YAML configuration.
            options: Indented YAML text containing backend-specific options.
            extra: Additional indented target fields added before the options mapping.

        Returns:
            Target context backed by temporary fixture paths.
        """
        config = self.root / "package.yml"
        config.write_text("""schema_version: 1
application:
  id: org.example.Demo
  name: Demo
  version: '1.0'
  summary: Demo package
  license: BSD-3-Clause
  executable: demo
  desktop: desktop.desktop
  icon: icon.svg
project:
  source: .
workspace: work
output: output
targets:
  test:
    arch: x86_64
""" + f"    backend: {backend}\n" + extra + "    options:\n" + options)
        loaded = load_config(config)
        (self.root / "work").mkdir(exist_ok=True)
        return BuildContext(loaded, loaded.targets[0], self.root / "work", self.root / "build",
                            self.root / "root", self.runner)

    def test_layouts_and_arch_aliases(self) -> None:
        """Normalize architecture aliases and preserve native installation layouts."""
        root = self.root
        self.assertEqual(normalize_arch("AMD64"), "x86_64")
        self.assertEqual(normalize_arch("arm64"), "aarch64")
        self.assertEqual(deployment_layout(root, "windows", "Demo").app, root)
        self.assertEqual(deployment_layout(root, "macos", "Demo").app, root / "Demo.app/Contents/MacOS")
        self.assertEqual(deployment_layout(root, "linux", "Demo").prefix, root / "usr")

    def test_deb_control_checksums_and_rootless_command(self) -> None:
        """Generate Debian control metadata, relative checksums, and rootless packaging arguments."""
        ctx = self.context("deb", "      package_name: demo\n      maintainer: Example <example@example.org>\n      depends: [libc6]\n")
        backend = DebBackend()
        backend.deploy(ctx, ProjectHooks())
        result = backend.package(ctx)
        text = (ctx.deploy_dir / "DEBIAN/control").read_text()
        self.assertIn("Architecture: amd64", text)
        self.assertIn("Depends: libc6", text)
        self.assertIn("usr/bin/demo", (ctx.deploy_dir / "DEBIAN/md5sums").read_text())
        self.assertIn("--root-owner-group", self.runner.commands[-1])
        self.assertTrue(result[0].path.is_file())

    def test_recipe_build_does_not_compile_application(self) -> None:
        """Export recipes without executing host commands or project compilation."""
        recipe = self.root / "recipe"
        recipe.mkdir()
        (recipe / "PKGBUILD").write_text("pkgname=demo\npkgver=1.0\npkgrel=1\n")
        ctx = self.context("aur", "      recipe: recipe\n")
        project = dataclasses.replace(ctx.config.project, commands=(("must-not-run",),))
        config = dataclasses.replace(ctx.config, project=project)
        with patch.object(AurBackend, "check", return_value=()), patch.object(ProjectHooks, "build", side_effect=AssertionError("host build")):
            result = run_target(config, ctx.target, self.runner)
        self.assertEqual(result[0].kind, "recipe")
        self.assertTrue(any(command[0] == "makepkg" for command in self.runner.commands))
        self.assertFalse(any(command[0] == "must-not-run" for command in self.runner.commands))
        reports = list(config.workspace.glob("*/artifacts.json"))
        self.assertEqual(json.loads(reports[0].read_text())[0]["kind"], "recipe")

    def test_declared_tools_skip_host_build_for_recipes_and_sdk(self) -> None:
        """Check target tools while skipping irrelevant host compiler requirements."""
        ctx = self.context("script", "      recipe: .\n      entry: desktop.desktop\n")
        project = dataclasses.replace(ctx.config.project, tools=("missing-host-compiler",))
        config = dataclasses.replace(ctx.config, project=project)
        target = dataclasses.replace(ctx.target, tools=("missing-target-tool",))
        ctx = dataclasses.replace(ctx, config=config, target=target)
        def missing(name: str) -> tuple[str, ...]:
            """Return a missing-tool message for the supplied executable name.

            Args:
                name: Executable name returned as an unmet requirement.

            Returns:
                One diagnostic message representing the missing executable.
            """
            return (name,)
        with patch("wingsetup.core.tool_missing", side_effect=missing):
            self.assertEqual(check_requirements(ScriptBackend(), ctx), ("missing-target-tool",))
        from wingsetup.model import FlatpakOptions
        sdk = dataclasses.replace(target, backend="flatpak", options=FlatpakOptions(mode="sdk", runtime="org.example.Platform", sdk="org.example.Sdk", runtime_version="1"))
        ctx = dataclasses.replace(ctx, target=sdk)
        with patch.object(ScriptBackend, "check", return_value=()), patch("wingsetup.core.tool_missing", side_effect=missing):
            self.assertEqual(check_requirements(ScriptBackend(), ctx), ("missing-target-tool",))
        native = dataclasses.replace(target, backend="deb", options=None)
        ctx = dataclasses.replace(ctx, target=native)
        with patch.object(ScriptBackend, "check", return_value=()), patch("wingsetup.core.tool_missing", side_effect=missing):
            self.assertEqual(check_requirements(ScriptBackend(), ctx), ("missing-target-tool", "missing-host-compiler"))

    def test_script_recipe_is_exported_without_execution(self) -> None:
        """Archive management scripts without executing their entry point."""
        recipe = self.root / "scripts"
        recipe.mkdir()
        (recipe / "install.py").write_text("raise RuntimeError('must not execute')\n")
        ctx = self.context("script", "      recipe: scripts\n      entry: install.py\n")
        backend = ScriptBackend()
        backend.build(ctx, ProjectHooks())
        backend.deploy(ctx, ProjectHooks())
        result = backend.package(ctx)
        self.assertEqual(result[0].kind, "recipe")
        self.assertEqual(self.runner.commands, [])

    def test_makeself_does_not_run_startup(self) -> None:
        """Syntax-check and archive installer startup scripts without running them."""
        payload = self.root / "payload"
        payload.mkdir()
        (payload / "file").write_text("payload")
        (self.root / "install.sh").write_text("#!/bin/sh\nexit 33\n")
        ctx = self.context("makeself", "      payload: payload\n      startup: install.sh\n")
        backend = MakeselfBackend()
        backend.deploy(ctx, ProjectHooks())
        result = backend.package(ctx)
        self.assertIn("--sha256", self.runner.commands[-1])
        self.assertEqual(result[0].format, "makeself")
        self.assertEqual(self.runner.commands[0][1], "-n")

    def pe(self, path: Path) -> None:
        """Write a minimal x86_64 PE header for architecture validation.

        Args:
            path: Temporary executable path receiving the minimal PE header.
        """
        data = bytearray(128)
        data[:2] = b"MZ"
        data[60:64] = (64).to_bytes(4, "little")
        data[64:70] = b"PE\0\0\x64\x86"
        path.write_bytes(data)

    def test_windows_deploy_and_both_formats(self) -> None:
        """Validate PE architecture and generate portable ZIP and Inno outputs."""
        self.pe(self.root / "demo.exe")
        ctx = self.context("inno", "      formats: [zip, inno]\n", extra="    executable: demo.exe\n")
        self.assertEqual(ctx.app_dir, ctx.deploy_dir)
        backend = InnoBackend()
        backend.deploy(ctx, ProjectHooks())
        result = backend.package(ctx)
        self.assertEqual([item.format for item in result], ["zip", "inno"])
        self.assertEqual(self.runner.commands[0][0], "windeployqt")
        with self.assertRaises(SetupError):
            validate_pe(self.root / "demo.exe", "aarch64")

    def mac_context(self, signing: str = "") -> BuildContext:
        """Create a minimal macOS bundle and parse its requested signing options.

        Args:
            signing: Indented YAML text configuring optional signing environment variables.

        Returns:
            Target context containing the macOS bundle and selected formats.
        """
        bundle = self.root / "demo.app/Contents"
        (bundle / "MacOS").mkdir(parents=True)
        (bundle / "MacOS/demo").write_bytes(b"Mach-O fixture")
        (bundle / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "org.example.Demo", "CFBundleExecutable": "demo"}))
        return self.context("macos", "      formats: [app, zip, dmg]\n" + signing, extra="    executable: demo.app\n")

    def test_macos_adhoc_outputs_and_bundle_identity(self) -> None:
        """Validate bundle identity and emit all requested ad-hoc signed formats."""
        ctx = self.mac_context()
        backend = MacOSBackend()
        backend.deploy(ctx, ProjectHooks())
        result = backend.package(ctx)
        self.assertEqual([item.format for item in result], ["app.zip", "zip", "dmg"])
        self.assertIn("-codesign=-", self.runner.commands[1])
        self.assertFalse(any(command[0] == "xcrun" for command in self.runner.commands))

    def test_macos_signing_notarization_sequence(self) -> None:
        """Submit and staple notarized app and DMG outputs in the required order."""
        ctx = self.mac_context("      sign_identity_env: TEST_SIGN_ID\n      notary_profile_env: TEST_NOTARY\n")
        backend = MacOSBackend()
        with patch.dict(os.environ, {"TEST_SIGN_ID": "Developer ID Example", "TEST_NOTARY": "ci-profile"}):
            backend.deploy(ctx, ProjectHooks())
            backend.package(ctx)
        commands = self.runner.commands
        self.assertTrue(any("-sign-for-notarization=Developer ID Example" in command for command in commands))
        self.assertTrue(any(command[:3] == ("xcrun", "notarytool", "submit") for command in commands))
        self.assertTrue(any(command[:3] == ("xcrun", "stapler", "validate") for command in commands))

    def test_notarization_rejection_prevents_stapling(self) -> None:
        """Stop before stapling when Apple rejects the notarization submission."""
        ctx = self.mac_context("      sign_identity_env: TEST_SIGN_ID\n      notary_profile_env: TEST_NOTARY\n")
        with patch.dict(os.environ, {"TEST_SIGN_ID": "Developer ID Example", "TEST_NOTARY": "ci-profile"}), patch.object(self.runner, "run", return_value='{"status":"Invalid"}') as run:
            with self.assertRaisesRegex(SetupError, "not accepted"):
                MacOSBackend().notarize(ctx, self.root / "submit.zip", self.root / "demo.app")
        self.assertEqual(run.call_count, 1)

    def test_macos_adhoc_custom_plugin_and_universal_architecture(self) -> None:
        """Sign custom plugin code before the app while validating universal slices."""
        ctx = self.mac_context()
        plugin = ctx.executable / "Contents/MacOS/plugin.wingplg"
        plugin.write_bytes(b"custom plugin")
        from wingsetup.backends.macos import MacOSOptions
        assert isinstance(ctx.target.options, MacOSOptions)
        opts = dataclasses.replace(ctx.target.options, extra_executables=("Contents/MacOS/plugin.wingplg",))
        ctx = dataclasses.replace(ctx, target=dataclasses.replace(ctx.target, arch="universal2", options=opts))
        MacOSBackend().deploy(ctx, ProjectHooks())
        codesign = [command for command in self.runner.commands if command[0] == "codesign"]
        self.assertEqual(len(codesign), 2)
        self.assertEqual(codesign[0][1:4], ("--force", "--sign", "-"))
        self.assertTrue(codesign[0][-1].endswith("plugin.wingplg"))
        self.assertNotIn("--timestamp", codesign[0])

    def test_list_does_not_import_project_hooks(self) -> None:
        """Expose target discovery without importing user project hooks."""
        ctx = self.context("macos", "      formats: [zip]\n")
        with patch("wingsetup.core.load_extension", side_effect=AssertionError("hook import")):
            self.assertEqual(main(["list", "-c", str(ctx.config.path), "--json"]), 0)

    def test_reject_platform_and_option_mismatches(self) -> None:
        """Reject inconsistent platform declarations and invalid backend options."""
        with self.assertRaises(SetupError):
            self.context("macos", "      formats: [zip]\n", extra="    platform: Linux\n")
        with self.assertRaises(SetupError):
            self.context("macos", "      notary_profile_env: PROFILE\n")
        with self.assertRaises(SetupError):
            self.context("deb", "      package_name: '../escape'\n      maintainer: Example\n")


if __name__ == "__main__":
    unittest.main()
