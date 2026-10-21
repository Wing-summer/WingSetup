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
from .backends import appimage, aur, deb, flatpak, inno, macos, makeself, script


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


#: Built-in factories, typed option parsers, and platform discovery capabilities.
BACKENDS: dict[str, BackendRegistration] = {
    "appimage": BackendRegistration(appimage.AppImageBackend, appimage.parse_options, ("Linux",), "linux"),
    "flatpak": BackendRegistration(flatpak.FlatpakBackend, flatpak.parse_options, ("Linux",), "flatpak"),
    "deb": BackendRegistration(deb.DebBackend, deb.parse_options, ("Linux",), "deb"),
    "inno": BackendRegistration(inno.InnoBackend, inno.parse_options, ("Windows",), "windows"),
    "macos": BackendRegistration(macos.MacOSBackend, macos.parse_options, ("Darwin",), "macos"),
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
