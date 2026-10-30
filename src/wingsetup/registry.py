# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Register built-in backends and expose their discovery metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from .core import PackageBackend
from .model import BackendOptions
from .validation import ConfigPaths
from .installation import INNO_FEATURES, LINUX_FEATURES, MAC_FEATURES
from .backends import appimage, archive, arch, aur, deb, rpm, flatpak, inno, macos, makeself, script


@dataclass(frozen=True)
class BackendRegistration:
    """Backend factory, option parser, and side-effect-free discovery metadata."""

    #: Callable constructing a new backend instance.
    factory: Callable[[], PackageBackend]
    #: Callable validating raw option values into a typed backend options object.
    parse: Callable[[dict[str, object], ConfigPaths], BackendOptions]
    #: Supported host platform names; any denotes unrestricted recipe export.
    platforms: tuple[str, ...]
    #: Deployment layout assigned to targets using this backend.
    layout: str
    #: Output category exposed during target discovery.
    kind: Literal["package", "recipe"] = "package"
    #: Shared installation fields the backend can implement.
    installation_features: frozenset[str] = frozenset({"license_file"})


#: Built-in factories, typed option parsers, and platform discovery capabilities.
BACKENDS: dict[str, BackendRegistration] = {
    "archive": BackendRegistration(archive.ArchiveBackend, archive.parse_options, ("Linux", "FreeBSD", "Darwin"), "portable"),
    "appimage": BackendRegistration(appimage.AppImageBackend, appimage.parse_options, ("Linux",), "linux", installation_features=LINUX_FEATURES),
    "flatpak": BackendRegistration(flatpak.FlatpakBackend, flatpak.parse_options, ("Linux",), "flatpak", installation_features=LINUX_FEATURES),
    "rpm": BackendRegistration(rpm.RpmBackend, rpm.parse_options, ("Linux",), "linux", installation_features=LINUX_FEATURES),
    "arch": BackendRegistration(arch.ArchBackend, arch.parse_options, ("Linux",), "linux", installation_features=LINUX_FEATURES),
    "deb": BackendRegistration(deb.DebBackend, deb.parse_options, ("Linux",), "deb", installation_features=LINUX_FEATURES),
    "inno": BackendRegistration(inno.InnoBackend, inno.parse_options, ("Windows",), "windows", installation_features=INNO_FEATURES),
    "macos": BackendRegistration(macos.MacOSBackend, macos.parse_options, ("Darwin",), "macos", installation_features=MAC_FEATURES),
    "aur": BackendRegistration(aur.AurBackend, aur.parse_options, ("any",), "recipe", "recipe"),
    "makeself": BackendRegistration(makeself.MakeselfBackend, makeself.parse_options, ("Linux", "Darwin"), "portable"),
    "script": BackendRegistration(script.ScriptBackend, script.parse_options, ("any",), "recipe", "recipe"),
}


def registration(name: str) -> BackendRegistration | None:
    """Look up built-in backend capabilities without constructing the backend.

    Args:
        name: Built-in backend name to look up.

    Returns:
        Registered backend capabilities, or None for a custom or unknown name.
    """
    return BACKENDS.get(name)
