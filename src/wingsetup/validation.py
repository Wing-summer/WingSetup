# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Validate untyped YAML values and resolve configuration-relative paths."""

from __future__ import annotations

from pathlib import Path
from typing import cast
import yaml
from .model import SetupError


def mapping(value: object, where: str) -> dict[str, object]:
    """Require a mapping with string keys at the untyped YAML boundary.

    Args:
        value: Untyped input value to validate or normalize.
        where: Configuration location used in actionable validation errors.

    Returns:
        Mapping with validated string keys and untyped values for further validation.

    Raises:
        SetupError: The input is not a mapping or includes a key that is not a string.
    """
    if not isinstance(value, dict):
        raise SetupError(f"{where}: expected mapping")
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        raise SetupError(f"{where}: keys must be strings")
    return cast(dict[str, object], raw)


def fields(data: dict[str, object], allowed: str, where: str) -> None:
    """Reject mapping keys that are not in the allowed field list.

    Args:
        data: Input mapping whose fields or backend options must be validated.
        allowed: Whitespace-separated field names accepted in the mapping.
        where: Configuration location used in actionable validation errors.

    Raises:
        SetupError: The mapping contains a field outside the allowed list.
    """
    unknown = data.keys() - set(allowed.split())
    if unknown:
        raise SetupError(f"{where}: unknown fields: {', '.join(sorted(unknown))}")


def string(value: object, where: str) -> str:
    """Require a nonempty string without silently converting other YAML types.

    Args:
        value: Untyped input value to validate or normalize.
        where: Configuration location used in actionable validation errors.

    Returns:
        Validated or preserved input string.

    Raises:
        SetupError: The value is not a string or contains only whitespace.
    """
    if not isinstance(value, str) or not value.strip():
        raise SetupError(f"{where}: expected nonempty string (quote versions)")
    return value


def sequence(value: object, where: str) -> list[object]:
    """Require a YAML sequence represented by a Python list.

    Args:
        value: Untyped input value to validate or normalize.
        where: Configuration location used in actionable validation errors.

    Returns:
        Input list for subsequent element validation.

    Raises:
        SetupError: The value is not a list.
    """
    if not isinstance(value, list):
        raise SetupError(f"{where}: expected list")
    return cast(list[object], value)


def strings(value: object, where: str) -> tuple[str, ...]:
    """Validate an immutable sequence of nonempty strings.

    Validate each sequence element as a nonempty string and return an immutable tuple.

    Args:
        value: Untyped input value to validate or normalize.
        where: Configuration location used in actionable validation errors.

    Returns:
        Validated strings in the input sequence order.
    """
    return tuple(string(item, where) for item in sequence(value, where))


def read_yaml(path: Path) -> dict[str, object]:
    """Read a UTF-8 YAML document and require a string-keyed top-level mapping.

    Args:
        path: File or directory path to inspect or process.

    Returns:
        Mapping with validated string keys and untyped values for further validation.

    Raises:
        SetupError: The file cannot be read or parsed, or its root is not a string-keyed
            mapping.
    """
    try:
        return mapping(cast(object, yaml.safe_load(path.read_text(encoding="utf-8"))), str(path))
    except (OSError, yaml.YAMLError) as exc:
        raise SetupError(f"Cannot read {path}: {exc}") from exc


class ConfigPaths:
    """Resolve recipe-relative paths while preserving run-time placeholders."""

    def __init__(self, base: Path) -> None:
        """Store the directory used to resolve static configuration paths.

        Args:
            base: Directory relative to which configuration or extension paths are
                resolved.
        """
        #: YAML directory against which static configuration paths are resolved.
        self.base = base

    def resolve(self, value: object, label: str) -> Path:
        """Resolve static paths and preserve supported placeholders.

        Resolve a configuration path while preserving supported run-time placeholders.

        Args:
            value: Untyped input value to validate or normalize.
            label: Configuration field name included in path validation errors.

        Returns:
            Resolved path, preserving supported placeholders only for configuration-time
            resolution.
        """
        name = string(value, label)
        if name.startswith(("{build}/", "{source}/", "{work}/")):
            return Path(name)
        return (self.base / name).resolve()

    def tool(self, value: object, label: str) -> str:
        """Resolve an explicit tool path or retain its executable name.

        Resolve explicit tool paths while preserving executable names for PATH lookup.

        Args:
            value: Untyped input value to validate or normalize.
            label: Configuration field name included in path validation errors.

        Returns:
            Resolved explicit tool path or unchanged executable name for PATH lookup.
        """
        name = string(value, label)
        return str((self.base / name).resolve()) if "/" in name or "\\" in name else name


def patterns(value: object, where: str) -> tuple[str, ...]:
    """Validate portable relative glob patterns used by copy and output filters.

    Args:
        value: YAML list of source-relative or deployment-relative patterns.
        where: Configuration field used in actionable validation errors.

    Returns:
        Validated POSIX-style patterns without absolute paths or parent traversal.

    Raises:
        SetupError: A pattern is absolute, contains a drive prefix, or traverses parents.
    """
    import re
    result = strings(value, where)
    for pattern in result:
        if pattern.startswith("/") or "\\" in pattern or ".." in pattern.split("/") or re.match(r"^[A-Za-z]:", pattern) or pattern in {".", "./", "/"}:
            raise SetupError(f"{where}: expected relative glob pattern: {pattern}")
    return result
