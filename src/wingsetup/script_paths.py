# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Expose read-only deployment paths bound to the currently executing target."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Generator

from .model import SetupError

if TYPE_CHECKING:
    from .core import BuildContext


#: Target context isolated across nested runs, threads, and asynchronous tasks.
_CURRENT_CONTEXT: ContextVar[BuildContext | None] = ContextVar("wingsetup_paths", default=None)


def _current() -> BuildContext:
    """Return the active packaging context.

    Returns:
        Context associated with the current target execution.

    Raises:
        SetupError: A path is accessed outside an active target run.
    """
    context = _CURRENT_CONTEXT.get()
    if context is None:
        raise SetupError("Script paths are available only during an active target run")
    return context


@dataclass(frozen=True, slots=True)
class ScriptPaths:
    """Read-only global namespace whose paths follow the active target run.

    Import the shared ``paths`` object instead of caching an individual path at
    module import time. Its properties resolve on each access, so nested runs
    restore the caller's paths and independent targets cannot overwrite them.
    Paths describe locations; accessing them does not create directories.
    """

    @property
    def CURRENT_SOURCE_DIR(self) -> Path:
        """Return the configured project source directory."""
        return _current().source_dir

    @property
    def CURRENT_CONFIG_DIR(self) -> Path:
        """Return the directory containing the selected YAML configuration."""
        return _current().config.path.parent

    @property
    def CURRENT_SCRIPT_DIR(self) -> Path:
        """Return the project Hook directory, or the YAML directory without hooks."""
        context = _current()
        spec = context.config.project.hooks
        if spec is None:
            return context.config.path.parent
        filename, _, _ = spec.rpartition(":")
        return (context.config.path.parent / filename).resolve().parent

    @property
    def CURRENT_WORK_DIR(self) -> Path:
        """Return the unique working directory retained for this target run."""
        return _current().work

    @property
    def CURRENT_BUILD_DIR(self) -> Path:
        """Return the isolated build directory for generated project outputs."""
        return _current().build_dir

    @property
    def CURRENT_DEPLOY_DIR(self) -> Path:
        """Return the root of the staged installation tree."""
        return _current().deploy_dir

    @property
    def CURRENT_INSTALL_PREFIX(self) -> Path:
        """Return the installation prefix inside the current deployment tree."""
        return _current().prefix_dir

    @property
    def CURRENT_APP_DIR(self) -> Path:
        """Return the directory for the executable and adjacent application data."""
        return _current().app_dir

    @property
    def CURRENT_RESOURCES_DIR(self) -> Path:
        """Return the platform-preferred deployment directory for application data."""
        return _current().layout.resources

    @property
    def CURRENT_LIBRARIES_DIR(self) -> Path:
        """Return the deployment directory for private shared libraries."""
        return _current().layout.libraries

    @property
    def CURRENT_PLUGINS_DIR(self) -> Path:
        """Return the platform-preferred deployment directory for plugins."""
        return _current().layout.plugins

    @property
    def CURRENT_OUTPUT_DIR(self) -> Path:
        """Return the selected target's final package and checksum directory."""
        context = _current()
        return context.config.output / context.target.name


#: Immutable, dynamically resolved path namespace available to trusted scripts.
paths: Final[ScriptPaths] = ScriptPaths()


@contextmanager
def activate_paths(context: BuildContext) -> Generator[None, None, None]:
    """Bind paths for one target and restore the caller after success or failure.

    Args:
        context: Target context exposed while the scope is active.

    Yields:
        Control to the target invocation with its paths available.
    """
    token = _CURRENT_CONTEXT.set(context)
    try:
        yield
    finally:
        _CURRENT_CONTEXT.reset(token)
