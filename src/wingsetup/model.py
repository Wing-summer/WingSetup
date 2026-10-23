# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Immutable configuration models and packaging result types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class SetupError(Exception):
    """An actionable configuration or packaging failure."""


@dataclass(frozen=True)
class Application:
    """Shared application identity, version, and desktop metadata."""

    #: Reverse-DNS application identifier used by desktop integrations.
    id: str
    #: Filename-safe application name used in output names and layouts.
    name: str
    #: Release version string shared by all targets.
    version: str
    #: Short application description for package metadata.
    summary: str
    #: License identifier of the packaged application.
    license: str
    #: Default build output path; run-time placeholders are permitted.
    executable: Path
    #: Desktop entry source, required by Linux desktop backends.
    desktop: Path | None
    #: Application icon source, required by Linux desktop backends.
    icon: Path | None


@dataclass(frozen=True)
class CopyRule:
    """Describe a source copied into a logical deployment location."""

    #: Source file or directory, optionally containing a run-time placeholder.
    source: Path
    #: Relative destination path inside the selected logical deployment location.
    destination: str
    #: Logical deployment location used as the destination base.
    relative_to: Literal["root", "prefix", "app", "resources", "libraries", "plugins"] = "root"
    #: Optional host-platform allowlist for this resource, independent of source presence.
    platforms: tuple[str, ...] = ()
    #: Source-relative glob patterns omitted while recursively copying this resource.
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class Project:
    """Host source tree, extension hooks, build commands, and common resources."""

    #: Source directory used as the default command working directory.
    source: Path
    #: Trusted local extension specification in file.py:ClassName form.
    hooks: str | None
    #: Host build commands expressed as argument tuples without an implicit shell.
    commands: tuple[tuple[str, ...], ...]
    #: Common resource rules applied before target-specific resources.
    resources: tuple[CopyRule, ...]
    #: Host build tools checked unless compilation belongs to the SDK or is skipped.
    tools: tuple[str, ...] = ()


class BackendOptions:
    """Base for validated format-specific options, including custom extensions."""


@dataclass(frozen=True)
class AppImageOptions(BackendOptions):
    """Validated AppImage tools, plugins, and dependency deployment inputs."""

    #: linuxdeploy executable name or resolved tool path.
    linuxdeploy: str = "linuxdeploy"
    #: appimagetool executable name or resolved tool path.
    appimagetool: str = "appimagetool"
    #: linuxdeploy plugin names enabled during dependency deployment.
    plugins: tuple[str, ...] = ()
    #: Additional shared libraries to deploy, including generated paths.
    libraries: tuple[Path, ...] = ()
    #: Environment overrides passed to linuxdeploy as name/value pairs.
    environment: tuple[tuple[str, str], ...] = ()
    #: Deployment-root-relative directories scanned for dynamically loaded ELF dependencies.
    dependency_dirs: tuple[str, ...] = ()
    #: Optional predownloaded AppImage runtime passed to appimagetool.
    runtime_file: Path | None = None
    #: Explicit Qt platform backends to bundle: xcb, wayland, and offscreen.
    qt_platforms: tuple[str, ...] = ()
    #: Shared-library glob patterns passed to linuxdeploy's dependency exclusion option.
    exclude_libraries: tuple[str, ...] = ()


@dataclass(frozen=True)
class FlatpakOptions(BackendOptions):
    """Validated Flatpak runtime selection and binary or SDK build settings."""

    #: Select host binary deployment or manifest-driven SDK compilation.
    mode: Literal["binary", "sdk"]
    #: Flatpak platform runtime application identifier.
    runtime: str
    #: Flatpak SDK application identifier used for initialization or compilation.
    sdk: str
    #: Runtime and SDK branch required by this target.
    runtime_version: str
    #: Application branch used for export and bundle creation.
    branch: str = "stable"
    #: Explicit sandbox permissions for binary mode; SDK mode uses the manifest.
    finish_args: tuple[str, ...] = ()
    #: Manifest path required for SDK mode.
    manifest: Path | None = None
    #: Flatpak installation containing the preinstalled runtime and SDK.
    installation: Literal["user", "system"] = "user"


@dataclass(frozen=True)
class Target:
    """One named backend invocation with isolated deployment settings."""

    #: Unique target name used for selection and output isolation.
    name: str
    #: Built-in backend name or trusted file.py:ClassName extension specification.
    backend: str
    #: Normalized output architecture, or any for architecture-independent recipes.
    arch: str
    #: Validated format-specific options; custom backends may omit them.
    options: BackendOptions | None
    #: Target-specific resource rules applied after common resources.
    resources: tuple[CopyRule, ...] = ()
    #: Required host platform, or any for platform-independent recipes.
    platform: str = ""
    #: Optional build-output override for this target.
    executable: Path | None = None
    #: Logical deployment layout selected by the backend registry.
    layout: str = ""
    #: Additional required tools checked even for SDK and recipe targets.
    tools: tuple[str, ...] = ()
    #: Deployment-root-relative patterns removed before packaging and final signing.
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    """Validated immutable configuration shared across isolated target runs."""

    #: Absolute path of the YAML file used to resolve extensions and resources.
    path: Path
    #: Shared application metadata.
    application: Application
    #: Host project build and deployment settings.
    project: Project
    #: Configured targets in YAML declaration order.
    targets: tuple[Target, ...]
    #: Root under which each invocation creates an isolated working directory.
    workspace: Path
    #: Root containing per-target package and checksum files.
    output: Path


@dataclass(frozen=True)
class Artifact:
    """Completed output with its format, architecture, kind, and SHA-256 digest."""

    #: Path to the completed output file.
    path: Path
    #: Concrete output format such as appimage, deb, or app.zip.
    format: str
    #: Normalized target architecture recorded for this output.
    arch: str
    #: Hexadecimal SHA-256 digest of the output contents.
    sha256: str
    #: Classify the output as a package, recipe, or reserved directory artifact.
    kind: Literal["package", "recipe", "directory"] = "package"
