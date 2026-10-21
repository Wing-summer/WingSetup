# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Expose the public packaging context, lifecycle hooks, and result types."""

from .console import Console, get_console
from .core import BuildContext, CommandRunner, PackageBackend, ProjectHooks
from .model import Artifact, SetupError
from .script_paths import ScriptPaths, paths

#: Public symbols intentionally exported by this package.
__all__ = ["Artifact", "BuildContext", "CommandRunner", "PackageBackend", "ProjectHooks", "SetupError", "ScriptPaths", "paths", "Console", "get_console"]
