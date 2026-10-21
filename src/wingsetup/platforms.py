# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Normalize architectures and describe platform deployment layouts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def normalize_arch(value: str) -> str:
    """Normalize common host architecture aliases to framework architecture names.

    Args:
        value: Untyped input value to validate or normalize.

    Returns:
        Canonical architecture name, leaving unrecognized names lowercased.
    """
    return {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}.get(value.lower(), value.lower())


@dataclass(frozen=True)
class DeploymentLayout:
    """Logical deployment paths for one application and packaging format."""

    #: Logical installation prefix within the staging tree.
    prefix: Path
    #: Directory containing the application executable and adjacent resources.
    app: Path
    #: Platform-preferred directory for application data.
    resources: Path
    #: Platform-preferred directory for private shared libraries.
    libraries: Path
    #: Platform-preferred directory for deployment plugins.
    plugins: Path
    #: Root of the macOS application bundle, or None for other layouts.
    bundle: Path | None = None


def deployment_layout(root: Path, kind: str, app_name: str) -> DeploymentLayout:
    """Describe deployment paths without invoking tools or creating directories.

    Args:
        root: Root of the staged installation tree.
        kind: Registered deployment layout identifier.
        app_name: Filename-safe application name used for private directories and
            bundles.

    Returns:
        Logical installation directories for the requested layout.
    """
    if kind == "deb":
        prefix = root / "usr"
        app = prefix / "lib" / app_name
        return DeploymentLayout(prefix, app / "bin", prefix / "share" / app_name, app / "lib", app / "plugins")
    if kind == "macos":
        bundle = root / f"{app_name}.app"
        contents = bundle / "Contents"
        return DeploymentLayout(contents, contents / "MacOS", contents / "Resources",
                                contents / "Frameworks", contents / "PlugIns", bundle)
    if kind == "windows" or kind == "portable" or kind == "recipe":
        return DeploymentLayout(root, root, root, root, root / "plugins")
    prefix = root / ("files" if kind == "flatpak" else "usr")
    return DeploymentLayout(prefix, prefix / "bin", prefix / "share", prefix / "lib", prefix / "plugins")
