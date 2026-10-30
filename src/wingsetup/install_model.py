# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Immutable desktop integration and installer preferences shared across backends."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class InstallationIcons:
    """Explicit source assets without implicit rasterization or format conversion."""

    #: Linux application or MIME icon in PNG/SVG format.
    linux: Path | None = None
    #: Windows installed application or document icon in ICO format.
    windows: Path | None = None
    #: macOS application or document icon in ICNS format.
    macos: Path | None = None


@dataclass(frozen=True)
class FileType:
    """One application-owned document handler, not a forced system default."""

    #: Stable local identifier used to derive ProgIDs and default UTIs.
    id: str
    #: User-visible type description.
    description: str
    #: Dot-prefixed file extensions, normalized to lowercase.
    extensions: tuple[str, ...]
    #: MIME identifier advertised by desktop entries.
    mime_type: str
    #: Platform-specific document icon sources.
    icons: InstallationIcons = InstallationIcons()
    #: Optional known UTI; omission derives an application-specific imported UTI.
    uti: str = ""
    #: Application role in macOS document handling.
    role: Literal["editor", "viewer"] = "editor"
    #: Explicit arguments containing a complete {file} token.
    arguments: tuple[str, ...] = ("{file}",)


@dataclass(frozen=True)
class Protocol:
    """A URL handler registered as an application capability."""

    #: Stable protocol scheme, normalized to lowercase.
    scheme: str
    #: Human-readable handler description.
    description: str
    #: Arguments containing a complete {url} token.
    arguments: tuple[str, ...] = ("{url}",)


@dataclass(frozen=True)
class ContextMenu:
    """An optional Windows shell verb owned by this application."""

    #: Stable local verb identifier.
    id: str
    #: Menu label shown by Explorer.
    label: str
    #: Applicable Explorer objects: file, directory, or background.
    targets: tuple[str, ...] = ("file",)
    #: Arguments containing a complete {path} token.
    arguments: tuple[str, ...] = ("{path}",)


@dataclass(frozen=True)
class Installation:
    """Resolved shared preferences; absence preserves legacy backend behavior."""

    #: Publisher displayed by installation or bundle metadata.
    publisher: str = ""
    #: Application home page.
    homepage: str = ""
    #: Support page displayed by the installer.
    support_url: str = ""
    #: App-owned license text to carry in packages and show in Inno.
    license_file: Path | None = None
    #: Platform-specific application icons.
    icons: InstallationIcons = InstallationIcons()
    #: Windows installer scope; package managers retain their native scope.
    scope: Literal["user", "machine"] = "user"
    #: Windows-native directory expression; empty selects the scope's default.
    directory: str = ""
    #: Whether an Inno Start menu shortcut is created.
    start_menu: bool = True
    #: Whether Inno offers an initially unchecked desktop shortcut task.
    desktop: bool = False
    #: Whether Inno offers an initially unchecked post-install launch.
    launch_after_install: bool = False
    #: Document-handler declarations, replaced as a list by target overrides.
    file_types: tuple[FileType, ...] = ()
    #: URL-handler declarations, replaced as a list by target overrides.
    protocols: tuple[Protocol, ...] = ()
    #: Whether Inno offers an initially unchecked PATH task.
    add_to_path: bool = False
    #: Whether a user-scope Inno installer offers a login startup task.
    autostart: bool = False
    #: Optional Windows shell verbs, gated by an unchecked installer task.
    context_menu: tuple[ContextMenu, ...] = ()
    #: Explicit configuration paths used to distinguish defaults from requests.
    specified: frozenset[str] = frozenset()
