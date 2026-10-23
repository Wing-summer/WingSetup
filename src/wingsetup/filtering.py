# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Apply portable resource and staged-payload exclusions without following links."""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from .console import get_console
from .model import SetupError

if TYPE_CHECKING:
    from .core import BuildContext


def matches(relative: str, patterns: tuple[str, ...]) -> bool:
    """Match a relative file or directory using portable pathlib-style globs.

    Args:
        relative: POSIX-style path relative to the filter's documented root.
        patterns: Validated patterns; a basename pattern applies at any depth.

    Returns:
        Whether any pattern selects the path, including root files for **/ patterns.
    """
    path = PurePosixPath(relative)
    return any(path.match(pattern) or (pattern.startswith("**/") and path.match(pattern[3:]))
               for pattern in patterns)


def filter_deployment(ctx: BuildContext) -> None:
    """Remove excluded payload paths before final signing and package generation.

    Args:
        ctx: Selected target and the already staged deployment tree.

    Raises:
        SetupError: A filter would traverse outside staging or remove a required entry.
    """
    root = ctx.deploy_dir.resolve()
    if not ctx.target.exclude or not root.is_dir():
        return
    protected = [ctx.app_dir / ctx.executable_name]
    if ctx.target.backend == "appimage":
        protected += [ctx.deploy_dir / "AppRun", ctx.deploy_dir / f"usr/share/applications/{ctx.config.application.id}.desktop"]
    elif ctx.target.backend == "flatpak":
        protected += [ctx.deploy_dir / "metadata", ctx.deploy_dir / f"files/share/applications/{ctx.config.application.id}.desktop"]
    elif ctx.target.backend == "macos" and ctx.layout.bundle is not None:
        protected += [ctx.layout.bundle / "Contents/Info.plist"]
    protected = [root / path.relative_to(ctx.deploy_dir) for path in protected]
    # Reject destructive rules before removing anything; links themselves may be removed.
    selected: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts)):
        if matches(path.relative_to(root).as_posix(), ctx.target.exclude):
            if any(path == required or required.is_relative_to(path) for required in protected):
                raise SetupError(f"target.exclude would remove a required entry: {path}")
            if not path.parent.resolve().is_relative_to(root):
                raise SetupError(f"Excluded path has an external parent: {path}")
            selected.append(path)
    for path in selected:
        if not path.exists() and not path.is_symlink():
            continue
        get_console().write(f"    EXCLUDE {path.relative_to(root)}", "detail")
        if path.is_symlink() or not path.is_dir():
            path.unlink()
        else:
            shutil.rmtree(path)
