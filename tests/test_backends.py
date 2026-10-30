# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Verify packaging framework behavior with isolated temporary fixtures."""

from __future__ import annotations

import dataclasses
import json
import os
import plistlib
import zipfile
import tempfile
import unittest
from pathlib import Path
from typing import Mapping, Sequence
from unittest.mock import patch

from wingsetup import BuildContext, CommandRunner, ProjectHooks, SetupError
from wingsetup.backends.archive import ArchiveBackend, ArchiveOptions
from wingsetup.backends.aur import AurBackend
from wingsetup.backends.deb import DebBackend
from wingsetup.backends.rpm import RpmBackend
from wingsetup.backends.arch import ArchBackend
from wingsetup.backends.common import validate_elf
from wingsetup.backends.inno import InnoBackend, validate_pe
from wingsetup.backends.macos import MacOSBackend
from wingsetup.backends.makeself import MakeselfBackend
from wingsetup.backends.script import ScriptBackend
from wingsetup.cli import main
from wingsetup.config import load_config
from wingsetup.core import check_requirements, run_target, deploy_resources
from wingsetup.model import CopyRule
from wingsetup.filtering import filter_deployment
from wingsetup.backends.appimage import AppImageBackend, deploy_qt_platforms
from wingsetup.model import AppImageOptions
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
        if args[0] == "rpmbuild":
            top = Path(next(value.removeprefix("_topdir ") for value in args if value.startswith("_topdir ")))
            output = top / "RPMS/x86_64/demo.rpm"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"rpm fixture")
        if args[0] == "makepkg" and "--config" in args:
            (cwd / "packages/demo.pkg.tar.zst").write_bytes(b"arch fixture")
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

    def test_archive_validates_and_packages_a_native_payload(self) -> None:
        """Use the portable backend for a native ELF without an installer script."""
        import tarfile
        ctx = self.context("archive", "      payload: .\n", extra="    platform: FreeBSD\n")
        # An explicit small payload avoids including the work tree in this fixture.
        ctx = dataclasses.replace(ctx, target=dataclasses.replace(ctx.target, options=ArchiveOptions()))
        backend = ArchiveBackend()
        backend.deploy(ctx, ProjectHooks())
        result = backend.package(ctx)
        self.assertEqual(result[0].format, "tar.gz")
        with tarfile.open(result[0].path) as stream:
            self.assertIn("./demo", stream.getnames())

    def test_appimage_update_companion_is_required_and_returned(self) -> None:
        """Return real zsync artifacts and fail when a requested companion is absent."""
        ctx = self.context("appimage", "      update_information: 'zsync|https://example.org/demo.AppImage.zsync'\n")
        ctx.deploy_dir.mkdir()
        (ctx.deploy_dir / "AppRun").write_text("#!/bin/sh\n")
        (ctx.config.output / ctx.target.name).mkdir(parents=True)
        produce = [True]

        def package_tool(arguments: Sequence[str], **_kwargs: object) -> str:
            """Simulate the packager's output and optional companion using real files.

            Args:
                arguments: Appimagetool argument list containing the final output path.
                _kwargs: Unused command execution settings.

            Returns:
                Empty captured standard output.
            """
            destination = Path(arguments[-1])
            destination.write_bytes(b"AppImage fixture")
            if produce[0]:
                destination.with_name(destination.name + ".zsync").write_bytes(b"zsync fixture")
            return ""

        with patch.object(BuildContext, "run", side_effect=package_tool), patch("wingsetup.backends.appimage.validate_elf"):
            outputs = AppImageBackend().package(ctx)
            self.assertEqual([item.format for item in outputs], ["appimage", "appimage.zsync"])
            for item in outputs:
                item.path.unlink()
            produce[0] = False
            with self.assertRaisesRegex(SetupError, "zsync"):
                AppImageBackend().package(ctx)

    def test_rpm_stages_usr_payload_and_escapes_spec_macros(self) -> None:
        """Generate an isolated spec with explicit dependencies and literal metadata."""
        ctx = self.context("rpm", "      package_name: demo\n      depends: ['libc.so.6()(64bit)']\n")
        ctx = dataclasses.replace(ctx, config=dataclasses.replace(
            ctx.config, application=dataclasses.replace(ctx.config.application, summary="literal %{macro}")))
        backend = RpmBackend()
        backend.deploy(ctx, ProjectHooks())
        output = backend.package(ctx)[0]
        spec = (ctx.work / "rpmbuild/SPECS/demo.spec").read_text(encoding="utf-8")
        self.assertIn("Summary: literal %%{macro}", spec)
        self.assertIn("Requires: libc.so.6()(64bit)", spec)
        self.assertIn('"/usr/bin/demo"', spec)
        self.assertNotIn('\n"/usr"\n', spec)
        self.assertEqual(output.format, "rpm")
        self.assertTrue(output.path.with_name(output.path.name + ".sha256").is_file())
        invocation = next(args for args in self.runner.commands if args[0] == "rpmbuild")
        self.assertIn("--target", invocation)
        self.assertIn("_rpmformat 4", invocation)
        self.assertIn("_dbpath " + str(ctx.work / "rpmbuild/rpmdb"), invocation)
        self.assertTrue(any(args[0] == "rpmdb" for args in self.runner.commands))
        with self.assertRaises(SetupError):
            self.context("rpm", "      package_name: 'demo\\nName: injected'\n")

    def test_arch_builds_a_binary_package_without_dependency_installation(self) -> None:
        """Use a local checksummed payload and preserve staged files in makepkg."""
        ctx = self.context("arch", "      package_name: demo\n      depends: [glibc]\n")
        backend = ArchBackend()
        backend.deploy(ctx, ProjectHooks())
        output = backend.package(ctx)[0]
        script = (ctx.work / "makepkg/PKGBUILD").read_text(encoding="utf-8")
        self.assertIn("depends=(glibc)", script)
        self.assertIn("sha256sums=('", script)
        self.assertIn("!strip", script)
        self.assertEqual(output.format, "pkg.tar.zst")
        invocation = next(args for args in self.runner.commands if args[0] == "makepkg")
        self.assertIn("--nodeps", invocation)
        self.assertNotIn("--syncdeps", invocation)
        self.assertNotIn("--install", invocation)

    def test_riscv64_elf_and_debian_metadata(self) -> None:
        """Validate RISC-V e_machine and retain riscv64 in Debian control metadata."""
        binary = self.root / "demo"
        data = bytearray(binary.read_bytes())
        data[18:20] = (243).to_bytes(2, "little")
        binary.write_bytes(data)
        validate_elf(binary, "riscv64")
        with self.assertRaises(SetupError):
            validate_elf(binary, "aarch64")
        ctx = self.context("deb", "      package_name: demo\n      maintainer: Example\n")
        ctx = dataclasses.replace(ctx, target=dataclasses.replace(ctx.target, arch="riscv64"))
        backend = DebBackend()
        backend.deploy(ctx, ProjectHooks())
        backend.package(ctx)
        self.assertIn("Architecture: riscv64", (ctx.deploy_dir / "DEBIAN/control").read_text())

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
        backend = MacOSBackend()
        backend.deploy(ctx, ProjectHooks())
        backend.package(ctx)
        codesign = [command for command in self.runner.commands if command[0] == "codesign" and "--force" in command]
        self.assertEqual(len(codesign), 2)
        self.assertEqual(codesign[0][1:4], ("--force", "--sign", "-"))
        self.assertTrue(codesign[0][-1].endswith("plugin.wingplg"))
        self.assertNotIn("--timestamp", codesign[0])

    def test_resource_platform_and_recursive_exclusions(self) -> None:
        """Skip foreign resources before reading sources and omit matching children."""
        ctx = self.context("deb", "      package_name: demo\n      maintainer: Example\n")
        assets = self.root / "assets"
        (assets / "cache").mkdir(parents=True)
        (assets / "cache/secret.txt").write_text("exclude")
        (assets / "debug.pdb").write_text("exclude")
        (assets / "keep.txt").write_text("keep")
        rules = (CopyRule(self.root / "absent", "foreign", platforms=("Windows",)),
                 CopyRule(assets, "assets", exclude=("cache", "*.pdb")))
        project = dataclasses.replace(ctx.config.project, resources=rules)
        ctx = dataclasses.replace(ctx, config=dataclasses.replace(ctx.config, project=project))
        deploy_resources(ctx)
        self.assertTrue((ctx.deploy_dir / "assets/keep.txt").is_file())
        self.assertFalse((ctx.deploy_dir / "assets/debug.pdb").exists())
        self.assertFalse((ctx.deploy_dir / "assets/cache").exists())
        self.assertFalse((ctx.deploy_dir / "foreign").exists())

    def test_final_exclusions_reject_entry_removal_before_deleting(self) -> None:
        """Prune generated payloads while preserving entry and traversal boundaries."""
        ctx = self.context("deb", "      package_name: demo\n      maintainer: Example\n")
        ctx.copy_app(self.root / "demo", "demo")
        debug = ctx.app_dir / "debug.pdb"
        debug.write_text("debug")
        unsafe = dataclasses.replace(ctx, target=dataclasses.replace(ctx.target, exclude=("**",)))
        with self.assertRaisesRegex(SetupError, "required entry"):
            filter_deployment(unsafe)
        self.assertTrue(debug.is_file())
        filtered = dataclasses.replace(ctx, target=dataclasses.replace(ctx.target, exclude=("**/*.pdb",)))
        filter_deployment(filtered)
        self.assertFalse(debug.exists())
        self.assertTrue((ctx.app_dir / "demo").is_file())
        with self.assertRaises(SetupError):
            self.context("deb", "      package_name: demo\n      maintainer: Example\n", extra="    exclude: ['../outside']\n")

    def test_inno_customization_and_format_specific_exclusions(self) -> None:
        """Render compiler settings without excluding debug files from portable ZIP."""
        self.pe(self.root / "demo.exe")
        (self.root / "setup.ico").write_bytes(b"compiler icon fixture")
        ctx = self.context("inno", "      formats: [zip, inno]\n      setup_icon: setup.ico\n      default_dir: '{autopf}/Demo'\n      privileges: admin\n      app_id: stable-installer-id\n      setup: {AppPublisher: Example, WizardStyle: modern}\n      file_excludes: ['*.pdb']\n      desktop_shortcut: true\n", extra="    executable: demo.exe\n")
        backend = InnoBackend()
        backend.deploy(ctx, ProjectHooks())
        (ctx.deploy_dir / "debug.pdb").write_text("debug")
        result = backend.package(ctx)
        script = (ctx.work / "installer.iss").read_text(encoding="utf-8-sig")
        self.assertIn("DefaultDirName={autopf}/Demo", script)
        self.assertIn("PrivilegesRequired=admin", script)
        self.assertIn("AppId=stable-installer-id", script)
        # Config paths are canonical even when macOS /var or Windows temp paths are aliases.
        self.assertIn("SetupIconFile=" + str((self.root / "setup.ico").resolve()), script)
        self.assertIn('Excludes: "*.pdb"', script)
        self.assertIn("{autodesktop}", script)
        with zipfile.ZipFile(result[0].path) as archive:
            self.assertIn("debug.pdb", archive.namelist())

    def test_custom_iss_cannot_silently_ignore_typed_settings(self) -> None:
        """Require an explicit setup insertion point in project-owned templates."""
        self.pe(self.root / "demo.exe")
        (self.root / "custom.iss").write_text("[Setup]\nAppName=Custom\n")
        ctx = self.context("inno", "      script: custom.iss\n      default_dir: '{autopf}/Demo'\n", extra="    executable: demo.exe\n")
        backend = InnoBackend()
        backend.deploy(ctx, ProjectHooks())
        with self.assertRaisesRegex(SetupError, "SETUP_DIRECTIVES"):
            backend.package(ctx)
        with self.assertRaises(SetupError):
            self.context("inno", "      setup: {OutputDir: override}\n")

    def test_wayland_platforms_and_integration_dependencies_are_staged(self) -> None:
        """Find Qt 6 platform variants from QMAKE and stage client integration types."""
        qt = self.root / "qt"
        (qt / "platforms").mkdir(parents=True)
        (qt / "platforms/libqwayland.so").write_bytes(b"platform")
        (qt / "wayland-shell-integration").mkdir()
        (qt / "wayland-shell-integration/libxdg-shell.so").write_bytes(b"integration")
        ctx = self.context("appimage", "      plugins: [qt]\n      qt_platforms: [wayland]\n")
        assert isinstance(ctx.target.options, AppImageOptions)
        with patch.object(self.runner, "run", return_value=str(qt)):
            deploy_qt_platforms(ctx, ctx.target.options)
        self.assertTrue((ctx.deploy_dir / "usr/plugins/platforms/libqwayland.so").is_file())
        self.assertTrue((ctx.deploy_dir / "usr/plugins/wayland-shell-integration/libxdg-shell.so").is_file())
        (qt / "platforms/libqwayland.so").unlink()
        with patch.object(self.runner, "run", return_value=str(qt)):
            with self.assertRaisesRegex(SetupError, "missing wayland"):
                deploy_qt_platforms(ctx, ctx.target.options)

    def test_macos_final_signing_occurs_after_payload_exclusions(self) -> None:
        """Remove staged resources before signing the final bundle in package."""
        ctx = self.mac_context()
        resources = ctx.executable / "Contents/Resources"
        resources.mkdir()
        (resources / "unused.tmp").write_text("excluded")
        target = dataclasses.replace(ctx.target, exclude=("**/*.tmp",))
        with patch.object(MacOSBackend, "check", return_value=()):
            run_target(ctx.config, target, self.runner)
        roots = list(ctx.config.workspace.glob("test-*/root/Demo.app/Contents/Resources"))
        self.assertEqual(len(roots), 1)
        self.assertFalse((roots[0] / "unused.tmp").exists())
        self.assertTrue(any(command[:2] == ("codesign", "--force") for command in self.runner.commands))

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
