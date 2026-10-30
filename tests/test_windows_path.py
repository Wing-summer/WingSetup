# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Require exact PATH preservation and useful Windows fixture failure diagnostics."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ci.windows_installation import check_path, registered_uninstaller, run
from wingsetup.model import SetupError


class WindowsPathTests(unittest.TestCase):
    """Reject changed empty tokens, registry types, and installation ownership."""

    def test_path_snapshots_reject_changed_tokens_type_and_ownership(self) -> None:
        """Persist the actual registry evidence even when uninstall validation fails."""
        baseline = ('C:\\Keep;;', 2)
        with tempfile.TemporaryDirectory() as temporary:
            logs = Path(temporary)
            with patch('ci.windows_installation.query', side_effect=[baseline, None, None]):
                check_path(logs, 'uninstall', baseline, 'Software\\Example', None)
            for actual, owned in [(('C:\\Keep;', 2), None), (('C:\\Keep;;', 1), None), (baseline, ('C:\\App', 1))]:
                with patch('ci.windows_installation.query', side_effect=[actual, owned, None]):
                    with self.assertRaisesRegex(SetupError, 'expected=.*actual='):
                        check_path(logs, 'uninstall', baseline, 'Software\\Example', None)
                snapshot = json.loads((logs / 'path-uninstall.json').read_text())
                self.assertEqual(snapshot['actual'], list(actual))


class RegisteredUninstallerTests(unittest.TestCase):
    """Follow the fixture registration without broadening executable authorization."""

    def test_numbered_uninstallers_follow_current_registration(self) -> None:
        """Resolve a changed executable number in an installation path containing spaces."""
        with tempfile.TemporaryDirectory() as temporary:
            logs = Path(temporary)
            installed = logs / 'Application With Spaces'
            installed.mkdir()
            for name in ('unins001.exe', 'unins002.exe'):
                executable = installed / name
                executable.write_bytes(b'uninstaller fixture')
                with patch('ci.windows_installation.query', return_value=('"' + str(executable) + '"', 1)):
                    self.assertEqual(registered_uninstaller(installed, 'fixture', logs, 'install'), executable)
            self.assertTrue((logs / 'uninstaller-install.json').is_file())

    def test_missing_external_and_malformed_registrations_fail(self) -> None:
        """Never execute missing files, external programs, or registry command arguments."""
        with tempfile.TemporaryDirectory() as temporary:
            logs = Path(temporary)
            installed = logs / 'Application With Spaces'
            installed.mkdir()
            external = logs / 'unins001.exe'
            external.write_bytes(b'external fixture')
            values = [None, ('"' + str(installed / 'unins000.exe') + '"', 1),
                      ('"' + str(external) + '"', 1), ('"unterminated', 1),
                      ('"' + str(external) + '" /SILENT', 1)]
            for value in values:
                with patch('ci.windows_installation.query', return_value=value):
                    with self.assertRaises(SetupError):
                        registered_uninstaller(installed, 'fixture', logs, 'install')

    def test_missing_command_has_an_actionable_error(self) -> None:
        """Report the requested executable instead of leaking a raw CreateProcess traceback."""
        with patch('ci.windows_installation.subprocess.run', side_effect=FileNotFoundError('missing executable')):
            with self.assertRaisesRegex(SetupError, 'Cannot start installer command.*unins001.exe'):
                run(['unins001.exe'])
