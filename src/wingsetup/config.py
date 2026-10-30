# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Parse and validate YAML configuration into immutable models."""

from __future__ import annotations

import re
from pathlib import Path
from .model import Application, BackendOptions, Config, CopyRule, Project, SetupError, Target
from .validation import ConfigPaths, fields, mapping, read_yaml, sequence, string, strings, patterns
from .platforms import normalize_arch
from .install_config import merge_installation, parse_installation


def load_config(path: Path) -> Config:
    """Parse YAML, reject invalid fields, and resolve configuration-relative paths.

    Args:
        path: File or directory path to inspect or process.

    Returns:
        Immutable validated configuration with resolved static paths.

    Raises:
        SetupError: The YAML structure, application metadata, target, or backend options
            are invalid.
    """
    path = path.resolve()
    base = path.parent
    data = read_yaml(path)
    fields(data, "schema_version application project targets workspace output installation", "config")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise SetupError("schema_version must be 1")

    paths = ConfigPaths(base)
    resolve = paths.resolve
    app = mapping(data.get("application"), "application")
    fields(app, "id name version summary license executable desktop icon", "application")
    text = {key: string(app.get(key), f"application.{key}")
            for key in ("id", "name", "version", "summary", "license")}
    if not re.fullmatch(r"[A-Za-z_][\w-]*(?:\.[A-Za-z_][\w-]*){2,}", text["id"]):
        raise SetupError("application.id must be a reverse DNS application ID")
    for key in ("name", "version"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", text[key]):
            raise SetupError(f"application.{key}: expected filename-safe value")
    application = Application(text["id"], text["name"], text["version"], text["summary"], text["license"], executable=resolve(app.get("executable", text["name"]), "executable"),
                              desktop=None if app.get("desktop") is None else resolve(app["desktop"], "desktop"),
                              icon=None if app.get("icon") is None else resolve(app["icon"], "icon"))
    project = mapping(data.get("project", {}), "project")
    fields(project, "source hooks commands resources tools", "project")
    hooks = project.get("hooks")
    commands = tuple(strings(cmd, "project.commands[]") for cmd in
                     sequence(project.get("commands", []), "project.commands"))
    if any(not cmd for cmd in commands):
        raise SetupError("project.commands: commands cannot be empty")
    def parse_resources(value: object) -> tuple[CopyRule, ...]:
        """Validate resource rules and resolve their source paths.

        Args:
            value: Untyped input value to validate or normalize.

        Returns:
            Immutable resource copy rules in configuration order.

        Raises:
            SetupError: A copy rule has invalid fields, types, destination, or logical
                location.
        """
        resources: list[CopyRule] = []
        for item in sequence(value, "resources"):
            rule = mapping(item, "resource")
            fields(rule, "source destination relative_to platforms exclude", "resource")
            dest = string(rule.get("destination"), "resource.destination")
            if Path(dest).is_absolute() or ".." in Path(dest).parts:
                raise SetupError("resource.destination must stay inside deployment directory")
            relative_to = rule.get("relative_to", "root")
            if relative_to not in ("root", "prefix", "app", "resources", "libraries", "plugins"):
                raise SetupError("resource.relative_to must be root, prefix, app, resources, libraries or plugins")
            platforms = strings(rule.get("platforms", []), "resource.platforms")
            if set(platforms) - {"Linux", "Windows", "Darwin", "FreeBSD"}:
                raise SetupError("resource.platforms must contain Linux, Windows, Darwin, or FreeBSD")
            resources.append(CopyRule(resolve(rule.get("source"), "resource.source"), dest, relative_to,
                                      platforms, patterns(rule.get("exclude", []), "resource.exclude")))
        return tuple(resources)

    installation_data = mapping(data.get("installation", {}), "installation")
    installation = parse_installation(installation_data, paths) if "installation" in data else None
    resources = parse_resources(project.get("resources", []))
    project_config = Project(resolve(project.get("source", "."), "project.source"),
                             None if hooks is None else string(hooks, "project.hooks"),
                             commands, tuple(resources),
                             tuple(paths.tool(value, "project.tools") for value in strings(project.get("tools", []), "project.tools")))
    targets: list[Target] = []
    for name, value in mapping(data.get("targets"), "targets").items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise SetupError(f"Invalid target name: {name}")
        target = mapping(value, f"targets.{name}")
        fields(target, "backend arch options resources platform executable tools exclude installation", name)
        backend = string(target.get("backend"), f"{name}.backend")
        import platform as host_platform
        arch = normalize_arch(string(target.get("arch", host_platform.machine()), f"{name}.arch"))
        if arch not in ("x86_64", "aarch64", "riscv64", "universal2", "any"):
            raise SetupError(f"Unsupported architecture: {arch}")
        opts = mapping(target.get("options", {}), f"{name}.options")
        from .registry import registration
        spec = registration(backend)
        options: BackendOptions | None
        if spec is None:
            if ":" not in backend:
                raise SetupError(f"Unknown backend: {backend}; use file.py:ClassName")
            fields(opts, "", name)
            options = None
        else:
            options = spec.parse(opts, paths)
        target_platform = string(target.get("platform", spec.platforms[0] if spec else host_platform.system()), "platform")
        if spec and target_platform not in spec.platforms and spec.platforms != ("any",):
            raise SetupError(f"{backend} does not support platform {target_platform}")
        if arch == "riscv64" and target_platform != "Linux":
            raise SetupError("riscv64 is only supported for Linux")
        if arch == "universal2" and target_platform != "Darwin":
            raise SetupError("universal2 is only supported for macOS")
        if arch == "any" and (spec is None or spec.kind != "recipe"):
            raise SetupError("any architecture is only supported for recipes")
        override = target.get("executable")
        targets.append(Target(name, backend, arch, options, parse_resources(target.get("resources", [])),
                              target_platform, None if override is None else resolve(override, "target.executable"),
                              spec.layout if spec else "portable",
                              tuple(paths.tool(value, "target.tools") for value in strings(target.get("tools", []), "target.tools")),
                              patterns(target.get("exclude", []), "target.exclude"),
                              parse_installation(merge_installation(installation_data, mapping(target.get("installation", {}), "target.installation")), paths) if installation is not None or "installation" in target else None,
                              frozenset(opts)))
    if not targets:
        raise SetupError("At least one target is required")
    return Config(path, application, project_config, tuple(targets),
                  resolve(data.get("workspace", ".wingsetup"), "workspace"),
                  resolve(data.get("output", "dist"), "output"), installation)

