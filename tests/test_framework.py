# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Verify packaging framework behavior with isolated temporary fixtures."""

from __future__ import annotations

import dataclasses
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Mapping, Sequence
from unittest.mock import patch

from wingsetup import Artifact, BuildContext, CommandRunner, PackageBackend, ProjectHooks, SetupError
from wingsetup.backends import AppImageBackend, FlatpakBackend
from wingsetup.cli import main
from wingsetup.config import load_config
from wingsetup.core import artifact, deploy_resources, run_target
from wingsetup.model import AppImageOptions, CopyRule, FlatpakOptions

#: Repository root containing the committed example fixtures.
ROOT = Path(__file__).resolve().parents[1]


class RecordingRunner(CommandRunner):
    """Record subprocess requests without invoking external packaging tools."""

    def __init__(self) -> None:
        """Initialize command recording or lifecycle trace state."""
        super().__init__()
        #: Recorded executable and argument tuples in invocation order.
        self.commands: list[tuple[str, ...]] = []
        #: Environment override dictionaries recorded for each command.
        self.environments: list[dict[str, str]] = []

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
        self.environments.append(dict(env or {}))
        return ""


class TraceBackend(PackageBackend):
    """Record backend lifecycle events and optionally fail during the build stage."""

    def __init__(self, events: list[str], fail: bool = False) -> None:
        """Initialize command recording or lifecycle trace state.

        Args:
            events: Shared event sequence used to assert lifecycle ordering.
            fail: Whether the simulated build raises an intentional failure.
        """
        #: Shared lifecycle event list used by assertions.
        self.events = events
        #: Whether the trace backend should fail at its build stage.
        self.fail = fail

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Report no external requirements for the lifecycle trace backend.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.

        Returns:
            An empty tuple because the test backend needs no external tools.
        """
        return ()

    def prepare(self, ctx: BuildContext) -> None:
        """Record preparation without invoking native tools.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        self.events.append("prepare")

    def build(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Record compilation and simulate the requested failure or skipped callback.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
            hooks: Project callbacks invoked during deployment.
        """
        self.events.append("build")
        if self.fail:
            raise SetupError("intentional")

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Record deployment without running external tools.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
            hooks: Project callbacks invoked during deployment.
        """
        self.events.append("deploy")

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Record packaging and return the simulated artifact collection.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.

        Returns:
            Artifact records for the generated or simulated output.
        """
        self.events.append("package")
        return ()


class TraceHooks(ProjectHooks):
    """Record all lifecycle callbacks and detect forbidden host SDK builds."""

    def __init__(self, events: list[str]) -> None:
        """Initialize command recording or lifecycle trace state.

        Args:
            events: Shared event sequence used to assert lifecycle ordering.
        """
        #: Shared lifecycle event list used by assertions.
        self.events = events

    def pre_prepare(self, ctx: BuildContext) -> None:
        """Record the pre callback for the prepare stage.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        self.events.append("pre_prepare")

    def after_prepare(self, ctx: BuildContext) -> None:
        """Record the after callback for the prepare stage.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        self.events.append("after_prepare")

    def pre_build(self, ctx: BuildContext) -> None:
        """Record the pre callback for the build stage.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        self.events.append("pre_build")

    def after_build(self, ctx: BuildContext) -> None:
        """Record the after callback for the build stage.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        self.events.append("after_build")

    def pre_deploy(self, ctx: BuildContext) -> None:
        """Record the pre callback for the deploy stage.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        self.events.append("pre_deploy")

    def after_deploy(self, ctx: BuildContext) -> None:
        """Record the after callback for the deploy stage.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        self.events.append("after_deploy")

    def pre_package(self, ctx: BuildContext) -> None:
        """Record the pre callback for the package stage.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        self.events.append("pre_package")

    def after_package(self, ctx: BuildContext) -> None:
        """Record the after callback for the package stage.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        self.events.append("after_package")

    def build(self, ctx: BuildContext) -> None:
        """Record compilation and simulate the requested failure or skipped callback.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        raise AssertionError("SDK called host build")


class FrameworkTests(unittest.TestCase):
    """Test typed configuration, resource isolation, and backend lifecycle contracts."""

    def setUp(self) -> None:
        """Create temporary test inputs and register cleanup of generated files."""
        #: Temporary-directory owner registered for automatic test cleanup.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        #: Temporary root containing this test fixture and generated outputs.
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / "examples/basic", self.root / "examples/basic",
                        ignore=shutil.ignore_patterns(".wingsetup", "build", "dist", "__pycache__"))
        #: Path to the copied basic example YAML configuration.
        self.path = self.root / "examples/basic/package.yml"
        #: Validated basic example configuration scoped to this test.
        self.config = load_config(self.path)
        # Portable ELF fixture keeps Linux backend tests runnable on Windows/macOS.
        #: Minimal executable fixture used without a platform-native compiler.
        self.binary = self.root / "fake-elf"
        header = bytearray(64)
        header[:6] = b"\x7fELF\x02\x01"
        header[18:20] = (62).to_bytes(2, "little")
        self.binary.write_bytes(header)
        self.binary.chmod(0o755)

    def test_validation(self) -> None:
        """Reject unknown fields, incorrect YAML types, and escaping resource paths."""
        original = self.path.read_text()
        for before, after in [("schema_version: 1", "schema_version: true"),
                              ("license: BSD-3-Clause",
                               "license: BSD-3-Clause\n  typo: value"),
                              ("version: '0.1.0'", "version: 123"),
                              ("source: .", "source: .\n  resources:\n    - source: hello.c\n      destination: ../escape")]:
            self.path.write_text(original.replace(before, after))
            with self.assertRaises(SetupError):
                load_config(self.path)

    def test_hook_order_and_failure(self) -> None:
        """Preserve lifecycle order and stop immediately when a stage fails."""
        for fail in (False, True):
            events: list[str] = []
            with patch("wingsetup.core.backend_for", return_value=TraceBackend(events, fail)), \
                    patch("wingsetup.core.load_extension", return_value=TraceHooks(events)):
                if fail:
                    with self.assertRaises(SetupError):
                        run_target(self.config, self.config.targets[0])
                    self.assertEqual(
                        events, ["pre_prepare", "prepare", "after_prepare", "pre_build", "build"])
                else:
                    run_target(self.config, self.config.targets[0])
                    self.assertEqual(events, [part for stage in ("prepare", "build", "deploy", "package")
                                              for part in (f"pre_{stage}", stage, f"after_{stage}")])

    def test_run_directories_isolated(self) -> None:
        """Create a distinct working directory for every target invocation."""
        config = dataclasses.replace(
            self.config, project=dataclasses.replace(self.config.project, hooks=None))
        with patch("wingsetup.core.backend_for", return_value=TraceBackend([])):
            run_target(config, config.targets[0])
            run_target(config, config.targets[0])
        self.assertEqual(len(list(config.workspace.iterdir())), 2)

    @unittest.skipIf(__import__("os").name == "nt", "Symlink permissions vary on Windows runners")
    def test_copy_escape(self) -> None:
        """Reject copy destinations that escape through parent paths or symlinks."""
        ctx = self.context(0)
        ctx.deploy_dir.mkdir()
        with self.assertRaises(SetupError):
            ctx.copy(self.path, "../escape")
        (ctx.deploy_dir / "link").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(SetupError):
            ctx.copy(self.path, "link/escape")

    def context(self, index: int) -> BuildContext:
        """Construct a typed target context using temporary fixture paths.

        Args:
            index: Index of the configured example target used for this context.

        Returns:
            Target context backed by temporary fixture paths.
        """
        return BuildContext(self.config, self.config.targets[index], self.root,
                            self.root / "build", self.root / "root", RecordingRunner())

    def test_sdk_commands_skip_host_build(self) -> None:
        """Delegate SDK builds to flatpak-builder without invoking host compilation."""
        ctx = self.context(2)
        backend = FlatpakBackend()
        backend.validate_manifest(ctx)
        backend.build(ctx, TraceHooks([]))
        self.assertIsInstance(ctx.runner, RecordingRunner)
        assert isinstance(ctx.runner, RecordingRunner)
        self.assertIn("--build-only", ctx.runner.commands[0])
        self.assertIn(str(
            (self.root / "examples/basic/org.example.Hello.yml").resolve()), ctx.runner.commands[0])

    def test_flatpak_finish_and_export(self) -> None:
        """Finish binary deployments before exporting and bundling the application."""
        ctx = self.context(1)
        executable = ctx.deploy_dir / "files/bin/hello"
        executable.parent.mkdir(parents=True)
        shutil.copy2(self.binary, executable)
        desktop = ctx.deploy_dir / "files/share/applications/org.example.Hello.desktop"
        desktop.parent.mkdir(parents=True)
        assert self.config.application.desktop is not None
        shutil.copy2(self.config.application.desktop, desktop)
        backend = FlatpakBackend()
        with patch("wingsetup.backends.flatpak.binary_deploy"):
            backend.deploy(ctx, ProjectHooks())
        assert isinstance(ctx.runner, RecordingRunner)
        self.assertIn("build-finish", ctx.runner.commands[-1])
        with patch("wingsetup.backends.flatpak.artifact", return_value=Artifact(self.root, "flatpak", "x86_64", "test")):
            backend.package(ctx)
        self.assertEqual(ctx.runner.commands[-2][1], "build-export")
        self.assertEqual(ctx.runner.commands[-1][1], "build-bundle")

    def test_check_never_imports_hook(self) -> None:
        """Keep configuration checks free of project imports and workspace creation."""
        with patch("wingsetup.core.load_extension", side_effect=AssertionError("imported")), \
                patch.object(AppImageBackend, "check", return_value=()):
            self.assertEqual(
                main(["check", "-c", str(self.path), "--target", "appimage"]), 0)
        self.assertFalse(self.config.workspace.exists())

    @unittest.skipIf(__import__("os").name == "nt", "AppRun is a Unix launcher")
    def test_appimage_deployment_and_packaging(self) -> None:
        """Preserve entry-relative resources when generating AppRun and the package."""
        ctx = self.context(0)
        app = ctx.config.application
        app.executable.parent.mkdir(exist_ok=True)
        shutil.copy2(self.binary, app.executable)
        backend = AppImageBackend()
        # linuxdeploy supplies AppRun; all commands are recorded, never executed.
        ctx.deploy_dir.mkdir()
        (ctx.deploy_dir / "AppRun").symlink_to("usr/bin/hello")
        backend.deploy(ctx, ProjectHooks())
        assert isinstance(ctx.runner, RecordingRunner)
        self.assertFalse((ctx.deploy_dir / "AppRun").is_symlink())
        self.assertIn('exec "$appdir"/usr/bin/hello "$@"',
                      (ctx.deploy_dir / "AppRun").read_text())
        self.assertIn("--appdir", ctx.runner.commands[-1])
        self.assertIn("--executable", ctx.runner.commands[-1])
        self.assertTrue((ctx.deploy_dir / "usr/bin/hello").is_file())
        with patch("wingsetup.backends.appimage.artifact", return_value=Artifact(self.root, "appimage", "x86_64", "test")):
            backend.package(ctx)
        self.assertEqual(ctx.runner.commands[-1][0], "appimagetool")

    def test_dynamic_plugin_dependencies_and_environment(self) -> None:
        """Forward Qt overrides and scan dynamically loaded plugin dependencies."""
        ctx = self.context(0)
        app = ctx.config.application
        app.executable.parent.mkdir(exist_ok=True)
        shutil.copy2(self.binary, app.executable)
        assert isinstance(ctx.target.options, AppImageOptions)
        options = dataclasses.replace(ctx.target.options, plugins=("qt",),
                                      environment=(
                                          ("QMAKE", "/custom/qt/qmake"),),
                                      dependency_dirs=("usr/bin/plugin",))
        target = dataclasses.replace(ctx.target, options=options, resources=(
            CopyRule(self.binary, "plugin/demo.wingplg", "app"),))
        ctx = dataclasses.replace(ctx, target=target)
        ctx.deploy_dir.mkdir()
        (ctx.deploy_dir / "AppRun").write_text("#!/bin/sh\n")
        AppImageBackend().deploy(ctx, ProjectHooks())
        assert isinstance(ctx.runner, RecordingRunner)
        command = ctx.runner.commands[-1]
        self.assertIn("--deploy-deps-only", command)
        self.assertIn(str(ctx.app_dir / "plugin"), command)
        self.assertEqual(
            ctx.runner.environments[-1]["QMAKE"], "/custom/qt/qmake")
        self.assertTrue((ctx.app_dir / "plugin/demo.wingplg").is_file())

    def test_sdk_finishing(self) -> None:
        """Finish SDK manifests without silently installing runtime dependencies."""
        ctx = self.context(2)
        binary = ctx.deploy_dir / "files/bin/hello"
        binary.parent.mkdir(parents=True)
        shutil.copy2(self.binary, binary)
        desktop = ctx.deploy_dir / "files/share/applications/org.example.Hello.desktop"
        desktop.parent.mkdir(parents=True)
        assert self.config.application.desktop is not None
        shutil.copy2(self.config.application.desktop, desktop)
        FlatpakBackend().deploy(ctx, ProjectHooks())
        assert isinstance(ctx.runner, RecordingRunner)
        self.assertIn("--finish-only", ctx.runner.commands[-1])
        self.assertNotIn("--install", ctx.runner.commands[-1])
        self.assertFalse(
            any("--install-deps-from" in arg for cmd in ctx.runner.commands for arg in cmd))

    def test_checksum_and_missing_output(self) -> None:
        """Reject absent outputs and record the expected SHA-256 sidecar."""
        ctx = self.context(0)
        output = self.root / "package"
        with self.assertRaises(SetupError):
            artifact(ctx, output, "test")
        output.write_bytes(b"abc")
        result = artifact(ctx, output, "test")
        self.assertEqual(
            result.sha256, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(output.with_suffix(
            ".sha256").read_text(), f"{result.sha256}  package\n")

    def test_command_failure_logged(self) -> None:
        """Retain subprocess diagnostics when a command exits unsuccessfully."""
        import sys
        log = self.root / "commands.log"
        with self.assertRaises(SetupError):
            CommandRunner(log).run(
                [sys.executable, "-c", "print('failure detail'); raise SystemExit(2)"], cwd=self.root)
        self.assertIn("failure detail", log.read_text())

    @unittest.skipIf(__import__("os").name == "nt", "Symlink permissions vary on Windows runners")
    def test_nested_copy_target_symlink_rejected(self) -> None:
        """Reject existing nested symlinks in the destination resource tree."""
        ctx = self.context(0)
        destination = ctx.deploy_dir / "assets"
        destination.mkdir(parents=True)
        (destination / "escape").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(SetupError):
            ctx.copy(self.path.parent, "assets")

    def test_relative_tool_path(self) -> None:
        """Resolve explicit tool paths relative to their YAML configuration."""
        self.path.write_text(self.path.read_text().replace(
            "linuxdeploy: linuxdeploy", "linuxdeploy: tools/linuxdeploy"))
        options = load_config(self.path).targets[0].options
        assert isinstance(options, AppImageOptions)
        self.assertEqual(options.linuxdeploy, str(
            (self.path.parent / "tools/linuxdeploy").resolve()))

    def test_resource_bases_and_target_resources(self) -> None:
        """Apply logical resource bases consistently for native and SDK layouts."""
        for index, prefix in ((0, "usr"), (1, "files"), (2, "files")):
            ctx = self.context(index)
            project = dataclasses.replace(ctx.config.project, resources=(
                CopyRule(self.path, "shared.yml", "app"),
                CopyRule(self.path, "share/prefix.yml", "prefix"),
            ))
            target = dataclasses.replace(ctx.target, resources=(
                CopyRule(self.path, "target.yml", "app"),))
            ctx = dataclasses.replace(ctx, config=dataclasses.replace(
                ctx.config, project=project), target=target)
            deploy_resources(ctx)
            self.assertTrue((ctx.deploy_dir / prefix /
                            "bin/shared.yml").is_file())
            self.assertTrue((ctx.deploy_dir / prefix /
                            "bin/target.yml").is_file())
            self.assertTrue((ctx.deploy_dir / prefix /
                            "share/prefix.yml").is_file())

    def test_generated_resource_paths(self) -> None:
        """Resolve generated build resources and reject escaping adjacent paths."""
        ctx = self.context(0)
        ctx.build_dir.mkdir()
        (ctx.build_dir / "generated.txt").write_text("generated")
        ctx.copy_app(Path("{build}/generated.txt"), "lang/generated.txt")
        self.assertEqual(
            (ctx.app_dir / "lang/generated.txt").read_text(), "generated")
        with self.assertRaises(SetupError):
            ctx.copy_app(self.path, "../escape")

    def test_qt_options_and_target_resource_config(self) -> None:
        """Parse Qt deployment options and target-specific copy rules."""
        self.path.write_text(self.path.read_text().replace(
            "      linuxdeploy: linuxdeploy", "      plugins: [qt]\n      environment: {QMAKE: /usr/bin/qmake6}\n      dependency_dirs: [usr/bin/plugin]\n      linuxdeploy: linuxdeploy").replace(
            "    backend: appimage", "    resources:\n      - source: hello.c\n        destination: source.c\n        relative_to: app\n    backend: appimage"))
        config = load_config(self.path)
        opts = config.targets[0].options
        assert isinstance(opts, AppImageOptions)
        self.assertEqual(opts.environment, (("QMAKE", "/usr/bin/qmake6"),))
        self.assertEqual(opts.dependency_dirs, ("usr/bin/plugin",))
        self.assertEqual(config.targets[0].resources[0].relative_to, "app")

    def test_manifest_mismatch(self) -> None:
        """Reject SDK runtime branches inconsistent with the shared configuration."""
        ctx = self.context(2)
        assert isinstance(ctx.target.options, FlatpakOptions)
        bad = dataclasses.replace(ctx.target.options, runtime_version="wrong")
        with self.assertRaises(SetupError):
            FlatpakBackend().validate_manifest(dataclasses.replace(
                ctx, target=dataclasses.replace(ctx.target, options=bad)))


if __name__ == "__main__":
    unittest.main()
