# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Validate shared installation preferences and merge target overrides at the boundary."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

from .install_model import ContextMenu, FileType, Installation, InstallationIcons, Protocol
from .model import SetupError
from .validation import ConfigPaths, fields, mapping, sequence, string, strings


def merge_installation(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    """Merge mapping fields recursively while replacing scalar and list values.

    Args:
        base: Shared YAML preferences without mutable typed state.
        override: Target-specific preferences taking precedence.

    Returns:
        Independent merged mapping; no input is modified.
    """
    result = dict(base)
    for key, value in override.items():
        previous = result.get(key)
        if isinstance(previous, dict) and isinstance(value, dict):
            result[key] = merge_installation(mapping(cast(object, previous), key), mapping(cast(object, value), key))
        else:
            result[key] = value
    return result


def text(value: object, where: str) -> str:
    """Require a nonempty, single-line, NUL-free metadata value.

    Args:
        value: Untyped configuration value.
        where: Name used by validation errors.

    Returns:
        Validated literal text.
    """
    result = string(value, where)
    if any(char in result for char in ("\r", "\n", "\0")):
        raise SetupError(f"{where} must be a single line")
    return result


def boolean(data: dict[str, object], name: str, default: bool = False) -> bool:
    """Validate a boolean without accepting integer or string lookalikes.

    Args:
        data: Input mapping.
        name: Field to inspect.
        default: Value when omitted.

    Returns:
        A validated boolean.
    """
    value = data.get(name, default)
    if not isinstance(value, bool):
        raise SetupError(f"installation.{name} must be boolean")
    return value


def identifier(value: object, where: str) -> str:
    """Validate a stable identifier safe in registry keys and XML identities.

    Args:
        value: Untyped local identifier.
        where: Diagnostic field name.

    Returns:
        Validated ASCII identifier.
    """
    result = text(value, where)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", result):
        raise SetupError(f"Invalid {where}")
    return result


def arguments(value: object, token: str) -> tuple[str, ...]:
    """Validate explicit arguments and require one complete dynamic input token.

    Args:
        value: Untyped argument list.
        token: The supported file, URL, or Explorer path placeholder.

    Returns:
        Immutable argument tokens; no shell interpretation is introduced.
    """
    result = strings(value, "installation.arguments")
    if result.count(token) != 1:
        raise SetupError(f"Arguments must contain exactly one complete {token} token")
    for item in result:
        text(item, "argument")
        if item != token and any(char in item for char in ("{", "}")):
            raise SetupError("Only the declared complete input placeholder is supported")
    return result


def icons(value: object, paths: ConfigPaths) -> InstallationIcons:
    """Resolve platform icon paths without requiring unused assets to exist.

    Args:
        value: Icon mapping containing Linux, Windows, and macOS source paths.
        paths: Configuration-relative path resolver.

    Returns:
        Immutable explicit icon assets.
    """
    data = mapping(value, "installation.icons")
    fields(data, "linux windows macos", "installation.icons")
    assets: list[Path | None] = []
    for name, suffixes in (("linux", (".png", ".svg")), ("windows", (".ico",)), ("macos", (".icns",))):
        asset = paths.resolve(data[name], f"icons.{name}") if name in data else None
        if asset is not None and asset.suffix.lower() not in suffixes:
            raise SetupError(f"Invalid {name} icon format; expected {suffixes}")
        assets.append(asset)
    return InstallationIcons(*assets)


def parse_installation(data: dict[str, object], paths: ConfigPaths) -> Installation:
    """Convert merged YAML metadata to immutable installation preferences.

    Args:
        data: Validated mapping shape, with target overrides already merged.
        paths: YAML-relative source and tool resolver.

    Returns:
        Complete typed preferences without checking irrelevant platform assets.

    Raises:
        SetupError: Fields, types, identities, or argument tokens are invalid.
    """
    fields(data, "publisher homepage support_url license_file icons scope directory shortcuts launch_after_install file_types protocols add_to_path autostart context_menu", "installation")
    scope = data.get("scope", "user")
    if scope not in ("user", "machine"):
        raise SetupError("installation.scope must be user or machine")
    shortcuts = mapping(data.get("shortcuts", {}), "installation.shortcuts")
    fields(shortcuts, "start_menu desktop", "installation.shortcuts")
    file_types: list[FileType] = []
    ids: set[str] = set()
    extensions: set[str] = set()
    for raw in sequence(data.get("file_types", []), "installation.file_types"):
        item = mapping(raw, "file_type")
        fields(item, "id description extensions mime_type icons uti role arguments", "file_type")
        identity = identifier(item.get("id"), "file_type.id")
        suffixes = tuple(value.lower() for value in strings(item.get("extensions"), "extensions"))
        if identity.lower() in ids or not suffixes or any(not re.fullmatch(r"\.[A-Za-z0-9][A-Za-z0-9._+-]*", value) or value in extensions for value in suffixes) or len(set(suffixes)) != len(suffixes):
            raise SetupError("Duplicate file type or invalid/duplicate extension")
        ids.add(identity.lower())
        extensions.update(suffixes)
        mime = text(item.get("mime_type"), "mime_type")
        if not re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", mime):
            raise SetupError("Invalid MIME type")
        uti = text(item["uti"], "uti") if "uti" in item else ""
        if uti and not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", uti):
            raise SetupError("Invalid macOS UTI")
        role: Literal["editor", "viewer"] = "viewer" if item.get("role") == "viewer" else "editor"
        if item.get("role", "editor") not in ("viewer", "editor"):
            raise SetupError("file_type.role must be editor or viewer")
        file_types.append(FileType(identity, text(item.get("description"), "description"), suffixes, mime,
                                   icons(item.get("icons", {}), paths), uti, role,
                                   arguments(item.get("arguments", ["{file}"]), "{file}")))
    protocols: list[Protocol] = []
    schemes: set[str] = set()
    for raw in sequence(data.get("protocols", []), "protocols"):
        item = mapping(raw, "protocol")
        fields(item, "scheme description arguments", "protocol")
        scheme = text(item.get("scheme"), "scheme").lower()
        if not re.fullmatch(r"[a-z][a-z0-9+.-]*", scheme) or scheme in schemes:
            raise SetupError("Invalid or duplicate URL scheme")
        schemes.add(scheme)
        protocols.append(Protocol(scheme, text(item.get("description"), "description"), arguments(item.get("arguments", ["{url}"]), "{url}")))
    menus: list[ContextMenu] = []
    ids.clear()
    for raw in sequence(data.get("context_menu", []), "context_menu"):
        item = mapping(raw, "context_menu")
        fields(item, "id label targets arguments", "context_menu")
        identity = identifier(item.get("id"), "context_menu.id")
        targets = strings(item.get("targets", ["file"]), "context_menu.targets")
        if identity.lower() in ids or not targets or set(targets) - {"file", "directory", "background"} or len(set(targets)) != len(targets):
            raise SetupError("Invalid or duplicate context menu")
        ids.add(identity.lower())
        menus.append(ContextMenu(identity, text(item.get("label"), "label"), targets, arguments(item.get("arguments", ["{path}"]), "{path}")))
    metadata = {name: text(data[name], name) if name in data else "" for name in ("publisher", "homepage", "support_url", "directory")}
    for name in ("homepage", "support_url"):
        try:
            parsed = urlsplit(metadata[name])
        except ValueError as exc:
            raise SetupError(f"installation.{name} contains an invalid URL") from exc
        if metadata[name] and (parsed.scheme not in ("http", "https") or not parsed.netloc):
            raise SetupError(f"installation.{name} must be an HTTP(S) URL")
    specified = set(data) - {"icons", "shortcuts"}
    specified.update(f"icons.{name}" for name in mapping(data.get("icons", {}), "icons"))
    specified.update(f"shortcuts.{name}" for name in shortcuts)
    return Installation(metadata["publisher"], metadata["homepage"], metadata["support_url"],
                        paths.resolve(data["license_file"], "license_file") if "license_file" in data else None,
                        icons(data.get("icons", {}), paths), scope, metadata["directory"],
                        boolean(shortcuts, "start_menu", True), boolean(shortcuts, "desktop"),
                        boolean(data, "launch_after_install"), tuple(file_types), tuple(protocols),
                        boolean(data, "add_to_path"), boolean(data, "autostart"), tuple(menus), frozenset(specified))
