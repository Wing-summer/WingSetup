# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Verify release selection and fail-closed cross-runner artifact aggregation."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ci.release import collect, load_jobs
from wingsetup.model import SetupError


class ReleaseTests(unittest.TestCase):
    """Exercise trusted build configuration and untrusted downloaded receipts."""

    def test_selection_and_qt_configuration(self) -> None:
        """Keep declared order and Qt commands while rejecting invalid build selection."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'build.yml'
            path.write_text('schema_version: 1\nbuilds:\n  linux:\n    runner: ubuntu-24.04\n    config: package.yml\n    targets: [appimage, rpm]\n    qt_prepare: [[python, qt.py]]\n  bsd:\n    runner: ubuntu-24.04\n    system: freebsd\n    config: package.yml\n    targets: [freebsd]\n')
            jobs = load_jobs(path)
            self.assertEqual(tuple(item.id for item in jobs), ('linux', 'bsd'))
            self.assertEqual(jobs[0].qt_prepare, (('python', 'qt.py'),))
            self.assertEqual(load_jobs(path, 'bsd')[0].system, 'freebsd')
            for selection in ('missing', ''):
                with self.assertRaises(SetupError):
                    load_jobs(path, selection)
            path.write_text(path.read_text().replace('config: package.yml', 'config: ../package.yml'))
            with self.assertRaises(SetupError):
                load_jobs(path)

    def receipt(self, root: Path, identity: str, name: str = 'demo.tar.gz') -> Path:
        """Write a representative immutable build receipt and its matching asset.

        Args:
            root: Download directory receiving a job subdirectory.
            identity: Stable planned job ID.
            name: Asset basename used for collision and tamper tests.

        Returns:
            Downloaded asset path.
        """
        directory = root / identity
        directory.mkdir()
        path = directory / name
        path.write_bytes(b'packaged application')
        (directory / 'release.json').write_text(json.dumps({'schema_version': 1, 'build': identity, 'assets': [{'name': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'format': 'tar.gz', 'arch': 'x86_64', 'target': 'portable'}]}))
        return path

    def test_collect_rehashes_and_emits_release_index(self) -> None:
        """Combine complete builds into sorted checksums and machine-readable metadata."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.receipt(root, 'linux')
            self.receipt(root, 'windows', 'demo.exe')
            assets = collect(root, root / 'release', ('linux', 'windows'))
            self.assertEqual([item['name'] for item in assets], ['demo.exe', 'demo.tar.gz'])
            self.assertEqual(len((root / 'release/SHA256SUMS.txt').read_text().splitlines()), 2)

    def test_collect_rejects_missing_duplicate_and_tampered_assets(self) -> None:
        """Never emit a release directory from incomplete or inconsistent build results."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.receipt(root, 'linux')
            with self.assertRaises(SetupError):
                collect(root, root / 'release', ('linux', 'windows'))
            self.receipt(root, 'windows')
            with self.assertRaises(SetupError):
                collect(root, root / 'release', ('linux', 'windows'))
            path.write_bytes(b'tampered')
            with self.assertRaises(SetupError):
                collect(root, root / 'release', ('linux',))
            self.assertFalse((root / 'release').exists())
