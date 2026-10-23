# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Require CI summaries to distinguish complete results from missing evidence."""

from __future__ import annotations

import importlib.util
import json
import io
import subprocess
import zipfile
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch
from contextlib import redirect_stdout

from wingsetup import Artifact, SetupError

#: Repository root used to load the committed CI driver and explicit workflow.
ROOT = Path(__file__).resolve().parents[1]


def driver() -> ModuleType:
    """Load the CI driver without running its command-line entry point.

    Returns:
        Module containing coverage validation and execution-report helpers.
    """
    spec = importlib.util.spec_from_file_location(
        "ci_reporting_driver", ROOT / "ci/examples.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def success_receipts(module: ModuleType, directory: Path) -> None:
    """Write simulated success evidence for testing the report acceptance rule.

    Args:
        module: CI driver exposing the reviewed case and output-format contract.
        directory: Temporary receipt directory; no real execution is claimed.
    """
    for case in module.load_cases():
        value = {"case": case.id, "status": "passed", "run_id": "local",
                 "run_attempt": "local", "commit": "local", "runner": case.runner,
                 "artifacts": [{"format": name, "checksum": True,
                                "launch": name not in {"inno", "aur", "script"},
                                "wayland": module.requires_wayland(case)}
                               for name in module.expected_formats(case)]}
        (directory /
         f"{case.id}.json").write_text(json.dumps(value), encoding="utf-8")


class CIReportTests(unittest.TestCase):
    """Exercise visible matrix completeness and fail-closed result aggregation."""

    def test_linux_qt_provisioning_uses_release_specific_svg_packages(self) -> None:
        """Keep Jammy's renamed SVG development package and runtime plugin explicit."""
        spec = importlib.util.spec_from_file_location("ci_prepare_driver", ROOT / "ci/prepare.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        jammy = module.linux_qt_packages("22.04")
        latest = module.linux_qt_packages("26.04")
        self.assertIn("libqt6svg6-dev", jammy)
        self.assertNotIn("qt6-svg-dev", jammy)
        self.assertIn("qt6-svg-dev", latest)
        self.assertNotIn("libqt6svg6-dev", latest)
        self.assertNotIn("qt6-svg-plugins", jammy)
        self.assertIn("qt6-svg-plugins", latest)

    def test_explicit_workflow_matches_every_declared_case(self) -> None:
        """Keep the visible workflow matrix aligned with the backend coverage contract."""
        module = driver()
        module.validate_workflow(module.load_cases())

    def test_linux_endpoints_and_both_macos_architectures_are_declared(self) -> None:
        """Require each Linux target on both LTS endpoints and independent Mac builds."""
        module = driver()
        cases = module.load_cases()
        for case in cases:
            if case.group in {"linux", "flatpak"}:
                runners = {entry.runner for entry in cases
                           if (entry.config, entry.target) == (case.config, case.target)}
                self.assertEqual(runners, {"ubuntu-22.04", "ubuntu-26.04"})
        for identity, architecture in (("qt-macos", "aarch64"), ("qt-macos-intel", "x86_64")):
            case = next(entry for entry in cases if entry.id == identity)
            config = module.load_config(ROOT / case.config)
            target = next(entry for entry in config.targets if entry.name == case.target)
            self.assertEqual(target.arch, architecture)
            self.assertEqual(module.expected_formats(case), ("app.zip", "zip", "dmg"))

    def test_wrong_runner_receipt_cannot_satisfy_another_lts(self) -> None:
        """Reject otherwise complete evidence mislabeled with the other Linux runner."""
        module = driver()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True), patch.object(module, "publish_summary"):
            directory = Path(temporary)
            success_receipts(module, directory)
            path = directory / "basic-appimage-lts-old.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["runner"] = "ubuntu-26.04"
            path.write_text(json.dumps(value), encoding="utf-8")
            self.assertFalse(module.report_results(module.load_cases(), directory))

    def test_unknown_workflow_case_is_rejected(self) -> None:
        """Reject a workflow edit that replaces a required case with an unknown one."""
        module = driver()
        cases = module.load_cases()
        workflow = (
            ROOT / ".github/workflows/examples.yml").read_text(encoding="utf-8")
        changed = workflow.replace("- id: basic-deb", "- id: unknown-backend")
        with patch.object(Path, "read_text", return_value=changed):
            with self.assertRaisesRegex(SetupError, "workflow case"):
                module.validate_workflow(cases)

    def test_complete_current_receipts_pass_and_missing_case_fails(self) -> None:
        """Require all cases rather than reporting success for the available subset."""
        module = driver()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True), patch.object(module, "publish_summary") as summary:
            directory = Path(temporary)
            success_receipts(module, directory)
            self.assertTrue(module.report_results(
                module.load_cases(), directory))
            self.assertIn("24/24", summary.call_args.args[0])
            (directory / "qt-macos.json").unlink()
            self.assertFalse(module.report_results(
                module.load_cases(), directory))
            self.assertIn("23/24", summary.call_args.args[0])
            self.assertIn("MISSING", summary.call_args.args[0])

    def test_incomplete_native_formats_and_failed_launch_do_not_pass(self) -> None:
        """Reject missing native formats or launch evidence despite a passed label."""
        module = driver()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True), patch.object(module, "publish_summary"):
            directory = Path(temporary)
            success_receipts(module, directory)
            path = directory / "qt-windows.json"
            value = {"runner": "windows-latest", "case": "qt-windows", "status": "passed", "run_id": "local",
                     "run_attempt": "local", "commit": "local",
                     "artifacts": [{"format": "inno", "checksum": True, "launch": False}]}
            path.write_text(json.dumps(value), encoding="utf-8")
            self.assertFalse(module.report_results(
                module.load_cases(), directory))
            success_receipts(module, directory)
            value["artifacts"] = [{"format": "zip", "checksum": True, "launch": False},
                                  {"format": "inno", "checksum": True, "launch": False}]
            path.write_text(json.dumps(value), encoding="utf-8")
            self.assertFalse(module.report_results(
                module.load_cases(), directory))

    def test_timeout_preserves_plugin_diagnostics(self) -> None:
        """Include captured Qt diagnostics when a smoke process times out."""
        module = driver()
        expired = subprocess.TimeoutExpired(
            ["widgets-demo.exe"], 120, output=b"offscreen load failed\n")
        output = io.StringIO()
        with patch.object(module.subprocess, "run", side_effect=expired), redirect_stdout(output):
            with self.assertRaisesRegex(SetupError, "offscreen load failed"):
                module.command(["widgets-demo.exe", "--smoke"],
                               marker="WIDGETS_DEPLOY_OK")
        self.assertIn("offscreen load failed", output.getvalue())

    def test_windows_archive_requires_its_own_offscreen_plugin(self) -> None:
        """Reject incomplete Qt payloads before a missing-plugin dialog can hang CI."""
        module = driver()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "widgets.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("widgets-demo.exe", b"fixture")
            artifact = Artifact(package, "zip", "x86_64", "fixture")
            with patch.object(module.os, "name", "nt"), patch.object(module, "command") as command:
                with self.assertRaisesRegex(SetupError, "qoffscreen.dll"):
                    module.verify_archive(
                        artifact, root / "missing", "WIDGETS_DEPLOY_OK", "widgets-demo.exe")
                command.assert_not_called()
            with zipfile.ZipFile(package, "a") as archive:
                archive.writestr("platforms/qoffscreen.dll", b"plugin fixture")
            with patch.object(module.os, "name", "nt"), patch.object(module, "command") as command:
                module.verify_archive(
                    artifact, root / "complete", "WIDGETS_DEPLOY_OK", "widgets-demo.exe")
                command.assert_called_once()

    def test_wayland_evidence_is_required_for_the_qt_appimage(self) -> None:
        """Reject an offscreen-only receipt when the target promises Wayland support."""
        module = driver()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True), patch.object(module, "publish_summary"):
            directory = Path(temporary)
            success_receipts(module, directory)
            path = directory / "qt-appimage.json"
            value = {"runner": "ubuntu-26.04", "case": "qt-appimage", "status": "passed", "run_id": "local",
                     "run_attempt": "local", "commit": "local",
                     "artifacts": [{"format": "appimage", "checksum": True, "launch": True}]}
            path.write_text(json.dumps(value), encoding="utf-8")
            self.assertFalse(module.report_results(module.load_cases(), directory))

    def test_failed_case_writes_a_failure_receipt(self) -> None:
        """Retain a failed outcome when packaging raises before producing outputs."""
        module = driver()
        failure = SetupError("simulated package failure")
        with patch.object(sys, "argv", ["examples.py", "--case", "basic-deb"]), patch.object(module, "run_case", side_effect=failure), patch.object(module, "write_receipt") as write:
            with self.assertRaisesRegex(SetupError, "package failure"):
                module.main()
        self.assertEqual(write.call_args.args[0].id, "basic-deb")
        self.assertEqual(write.call_args.args[1]["status"], "failed")

    def test_stale_receipts_or_failed_prerequisite_cannot_turn_the_gate_green(self) -> None:
        """Reject other-run evidence and upstream failures even with complete receipts."""
        module = driver()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True), patch.object(module, "publish_summary"):
            directory = Path(temporary)
            success_receipts(module, directory)
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "new-run"}):
                self.assertFalse(module.report_results(
                    module.load_cases(), directory))
            with patch.dict(os.environ, {"EXAMPLE_JOB_RESULTS": '{"native":{"result":"cancelled"}}'}):
                self.assertFalse(module.report_results(
                    module.load_cases(), directory))


if __name__ == "__main__":
    unittest.main()
