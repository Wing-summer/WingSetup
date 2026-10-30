# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Validate shortcut file identity without requiring an installed Windows fixture."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ci.windows_installation import shortcuts
from wingsetup.model import SetupError


class ShortcutTests(unittest.TestCase):
    """Keep native shortcut inspection strict while accepting equivalent path spellings."""

    def test_equivalent_paths_pass_and_wrong_files_fail(self) -> None:
        """Compare real files rather than literal target or wildcard icon strings."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            installed = root / 'Application With Spaces'
            installed.mkdir()
            (installed / 'widgets-demo.exe').write_bytes(b'executable fixture')
            icons = installed / 'wingsetup-assets'
            icons.mkdir()
            (icons / 'app.ico').write_bytes(b'icon fixture')
            links = [str(root / 'desktop.lnk'), str(root / 'start-menu.lnk')]
            alternate = icons / '..' / 'widgets-demo.exe'
            entries = [{'path': name, 'target': str(alternate), 'icon': str(icons / 'app.ico') + ',0'} for name in links]
            with patch('ci.windows_installation.run', return_value=json.dumps(entries)):
                self.assertEqual(shortcuts(root, installed), [Path(name) for name in links])
            self.assertTrue((root / 'shortcuts.json').is_file())
            wrong = installed / 'wrong.exe'
            wrong.write_bytes(b'executable fixture')
            entries[0]['target'] = str(wrong)
            with patch('ci.windows_installation.run', return_value=json.dumps(entries)):
                with self.assertRaisesRegex(SetupError, 'Wrong shortcut target.*actual=.*wrong.exe'):
                    shortcuts(root, installed)
            entries[0]['target'] = str(alternate)
            entries[0]['icon'] = str(icons / 'app.ico') + ',1'
            with patch('ci.windows_installation.run', return_value=json.dumps(entries)):
                with self.assertRaisesRegex(SetupError, 'Wrong shortcut icon'):
                    shortcuts(root, installed)
