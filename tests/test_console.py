# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Verify color policy, clean command capture, and truthful lifecycle progress."""

from __future__ import annotations

import dataclasses
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from threading import Event
from unittest.mock import patch

from wingsetup import Artifact, BuildContext, CommandRunner, PackageBackend, ProjectHooks, SetupError
from wingsetup.cli import main
from wingsetup.config import load_config
from wingsetup.console import Console, console_scope
from wingsetup.core import run_target

#: Root containing the committed generic packaging fixtures.
ROOT = Path(__file__).resolve().parents[1]


class ProgressBackend(PackageBackend):
    """Exercise lifecycle progress without invoking external packaging tools."""

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Report no native dependencies for this progress fixture.

        Args:
            ctx: Target context used by the test pipeline.

        Returns:
            Empty dependency diagnostics.
        """
        return ()

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Create an empty deployment tree without running a real installer.

        Args:
            ctx: Target-local deployment paths.
            hooks: Project callbacks unused by this minimal fixture.
        """
        ctx.deploy_dir.mkdir()

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Return no native artifacts from the progress-only fixture.

        Args:
            ctx: Target context whose packaging phase is being observed.

        Returns:
            Empty output tuple for this lifecycle-only test.
        """
        return ()


class FailingHook(ProjectHooks):
    """Fail an after hook to verify that its stage never appears complete."""

    def after_build(self, ctx: BuildContext) -> None:
        """Reject build completion before the progress counter advances.

        Args:
            ctx: Active target context, unused by this failure injection.

        Raises:
            SetupError: The test intentionally rejects the completed backend build.
        """
        raise SetupError("after-build failure")


class ConsoleTests(unittest.TestCase):
    """Validate terminal output independently from command and JSON data."""

    def test_color_policy_and_no_color_environment(self) -> None:
        """Respect plain streams and environment policy while allowing explicit color."""
        stream = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            Console(stream=stream).write("READY", "success")
        self.assertEqual(stream.getvalue(), "READY\n")
        stream.seek(0)
        stream.truncate()
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "NO_COLOR": "1"}, clear=True):
            Console(stream=stream).write("READY", "success")
            self.assertFalse(Console(stream=stream).colored)
            self.assertTrue(Console("always", stream).colored)
        self.assertNotIn("\x1b", stream.getvalue())
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=True):
            self.assertTrue(Console(stream=stream).colored)
        Console("always", stream).write("FAILED", "error")
        self.assertIn("\x1b[31mFAILED\x1b[0m", stream.getvalue())

    def test_progress_uses_completed_units_and_heartbeat_uses_elapsed_time(self) -> None:
        """Show real counters and periodic running state without fabricating progress."""
        stream = io.StringIO()
        console = Console("never", stream)
        console.progress(1, 4, "deploy")
        self.assertIn("[=====...............] 1/4 deploy", stream.getvalue())
        with patch.object(Event, "wait", side_effect=[False, True]), patch("wingsetup.console.monotonic", return_value=15.0):
            console.heartbeat(Event(), "compiler", 0.0)
        self.assertIn("RUNNING compiler (15.0s elapsed)", stream.getvalue())
        with self.assertRaises(ValueError):
            console.progress(5, 4, "invalid")

    def test_command_output_is_not_mixed_with_progress_and_log_has_no_ansi(self) -> None:
        """Keep parsable process output separate and save uncolored command logs."""
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "commands.log"
            script = "print('\\x1b[31mvalue\\x1b[0m')"
            with console_scope(Console("never", stream)):
                output = CommandRunner(log).run([sys.executable, "-c", script], cwd=Path(directory))
            self.assertEqual(output, "\x1b[31mvalue\x1b[0m\n")
            self.assertNotIn("\x1b", log.read_text(encoding="utf-8"))
        self.assertIn("COMMAND", stream.getvalue())
        self.assertIn("DONE", stream.getvalue())
        self.assertNotIn("\x1b", stream.getvalue())

    def test_json_remains_clean_even_with_forced_color(self) -> None:
        """Keep list JSON parseable without colored status messages on stdout."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["list", "-c", str(ROOT / "examples/basic/package.yml"), "--json", "--color", "always"])
        self.assertEqual(code, 0)
        self.assertIsInstance(json.loads(out.getvalue()), list)
        self.assertNotIn("\x1b", out.getvalue())
        self.assertEqual(err.getvalue(), "")

    def test_after_hook_failure_does_not_advance_the_completed_stage(self) -> None:
        """Stop at the failing callback and retain an accurate completed-stage count."""
        config = load_config(ROOT / "examples/basic/package.yml")
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            config = dataclasses.replace(config, workspace=Path(directory) / "work", output=Path(directory) / "dist",
                                         project=dataclasses.replace(config.project, commands=()))
            with console_scope(Console("never", stream)), patch("wingsetup.core.backend_for", return_value=ProgressBackend()), patch("wingsetup.core.load_extension", return_value=FailingHook()):
                with self.assertRaisesRegex(SetupError, "after-build failure"):
                    run_target(config, config.targets[0])
        text = stream.getvalue()
        self.assertIn("1/4", text)
        self.assertIn("FAILED build at after_build", text)
        self.assertNotIn("DONE build", text)
        self.assertNotIn("pre_deploy", text)
        self.assertNotIn("4/4", text)


if __name__ == "__main__":
    unittest.main()
