# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Verify target-local script paths and example CI coverage contracts."""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from wingsetup import BuildContext, CommandRunner, SetupError, paths
from wingsetup.config import load_config
from wingsetup.core import run_target
from wingsetup.script_paths import activate_paths

#: Repository root used to load committed examples and their CI manifest.
ROOT = Path(__file__).resolve().parents[1]


def load_ci_examples() -> ModuleType:
    """Import the example CI driver without invoking its command-line entry.

    Returns:
        Module exposing coverage validation and native package verification.
    """
    spec = importlib.util.spec_from_file_location("wingsetup_ci_examples", ROOT / "ci/examples.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ScriptPathTests(unittest.TestCase):
    """Exercise path scope restoration, immutability, and target coverage."""

    def context(self, directory: Path, name: str) -> BuildContext:
        """Create a context with isolated paths without executing a backend.

        Args:
            directory: Temporary root for all generated paths.
            name: Distinct target name used to detect accidental context leakage.

        Returns:
            Context referencing the basic example and the requested work directory.
        """
        config = load_config(ROOT / "examples/basic/package.yml")
        config = dataclasses.replace(config, workspace=directory / "work", output=directory / "dist")
        target = dataclasses.replace(config.targets[0], name=name)
        work = directory / name
        return BuildContext(config, target, work, work / "build", work / "deploy", CommandRunner())

    def test_paths_reject_access_outside_a_run(self) -> None:
        """Reject unbound paths rather than leaking the previous target's context."""
        with self.assertRaisesRegex(SetupError, "active target"):
            _ = paths.CURRENT_SOURCE_DIR

    def test_nested_paths_restore_after_failure_and_cannot_be_reassigned(self) -> None:
        """Restore outer paths after a failed nested run and reject reassignment."""
        with tempfile.TemporaryDirectory() as directory:
            first = self.context(Path(directory), "first")
            second = self.context(Path(directory), "second")
            with activate_paths(first):
                self.assertEqual(paths.CURRENT_SOURCE_DIR, first.source_dir)
                self.assertEqual(paths.CURRENT_CONFIG_DIR, first.config.path.parent)
                self.assertEqual(paths.CURRENT_SCRIPT_DIR, first.config.path.parent)
                self.assertEqual(paths.CURRENT_APP_DIR, first.app_dir)
                self.assertEqual(paths.CURRENT_INSTALL_PREFIX, first.prefix_dir)
                self.assertEqual(paths.CURRENT_RESOURCES_DIR, first.layout.resources)
                self.assertEqual(paths.CURRENT_LIBRARIES_DIR, first.layout.libraries)
                self.assertEqual(paths.CURRENT_PLUGINS_DIR, first.layout.plugins)
                self.assertEqual(paths.CURRENT_OUTPUT_DIR, first.config.output / first.target.name)
                with self.assertRaises((AttributeError, TypeError)):
                    setattr(paths, "CURRENT_SOURCE_DIR", Path(directory))
                with self.assertRaisesRegex(RuntimeError, "nested failure"):
                    with activate_paths(second):
                        self.assertEqual(paths.CURRENT_BUILD_DIR, second.build_dir)
                        self.assertEqual(paths.CURRENT_WORK_DIR, second.work)
                        self.assertEqual(paths.CURRENT_DEPLOY_DIR, second.deploy_dir)
                        raise RuntimeError("nested failure")
                self.assertEqual(paths.CURRENT_BUILD_DIR, first.build_dir)
            self.assertFalse(first.work.exists())
        with self.assertRaises(SetupError):
            _ = paths.CURRENT_BUILD_DIR

    def test_pipeline_binds_paths_while_importing_project_hooks(self) -> None:
        """Expose paths during extension import and restore them if loading fails."""
        with tempfile.TemporaryDirectory() as directory:
            context = self.context(Path(directory), "hook-import")

            def fail_import(*_args: object) -> None:
                """Observe active paths before simulating a project import failure.

                Args:
                    *_args: Extension-loader arguments ignored by this replacement.
                """
                self.assertEqual(paths.CURRENT_SOURCE_DIR, context.source_dir)
                raise SetupError("import failure")

            with patch("wingsetup.core.load_extension", side_effect=fail_import):
                with self.assertRaisesRegex(SetupError, "import failure"):
                    run_target(context.config, context.target)
            with self.assertRaises(SetupError):
                _ = paths.CURRENT_SOURCE_DIR

    def test_example_manifest_covers_all_targets_and_backends(self) -> None:
        """Require CI coverage to grow when example targets or backends are added."""
        module = load_ci_examples()
        cases: object = module.load_cases()
        self.assertIsInstance(cases, tuple)
        assert isinstance(cases, tuple)
        self.assertTrue(cases)

    def test_missing_example_case_fails_coverage_validation(self) -> None:
        """Reject a manifest that silently drops one supported example target."""
        module = load_ci_examples()
        manifest = (ROOT / "ci/examples.json").read_text(encoding="utf-8")
        import json
        from typing import cast
        values = cast(list[object], json.loads(manifest))
        with tempfile.TemporaryDirectory() as directory:
            incomplete = Path(directory) / "examples.json"
            incomplete.write_text(json.dumps(values[1:]), encoding="utf-8")
            with patch.object(module, "MANIFEST", incomplete):
                with self.assertRaisesRegex(SetupError, "Incomplete example coverage"):
                    module.load_cases()


if __name__ == "__main__":
    unittest.main()
