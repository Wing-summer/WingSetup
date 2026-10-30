# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Render optional Inno tasks and application-owned Windows shell registrations."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from ..installation import inno_enabled

if TYPE_CHECKING:
    from ..core import BuildContext
    from .inno import InnoOptions


def quoted(value: str) -> str:
    """Escape one Inno parameter while retaining deliberately generated constants.

    Args:
        value: Generated directive value or command line.

    Returns:
        Double-quoted Inno string.
    """
    return '"' + value.replace('"', '""') + '"'


def literal(value: str) -> str:
    """Prevent user metadata from being interpreted as an Inno constant.

    Args:
        value: Validated single-line user text.

    Returns:
        Inno-safe literal metadata, before parameter quoting.
    """
    return value.replace("{", "{{")


def pascal(value: str) -> str:
    """Quote literal or generated text as a Pascal string expression.

    Args:
        value: Text to emit into the runtime helper.

    Returns:
        Single-quoted Pascal string.
    """
    return "'" + value.replace("'", "''") + "'"


def windows_command(executable: str, arguments: tuple[str, ...], token: str, replacement: str = "%1") -> str:
    """Construct a CreateProcess-style command with a separately quoted input token.

    Args:
        executable: Installed filename, including generated Inno constants.
        arguments: Validated individual arguments.
        token: Shared dynamic input placeholder.
        replacement: Windows shell parameter such as %1 or %V.

    Returns:
        Quoted executable and argument sequence without cmd.exe interpretation.
    """
    parts = ['"' + executable + '"']
    parts += ['"' + replacement + '"' if value == token else literal(subprocess.list2cmdline([value])) for value in arguments]
    return " ".join(parts)


def effective_options(ctx: BuildContext, options: InnoOptions) -> InnoOptions:
    """Overlay shared defaults without overriding explicit legacy backend options.

    Args:
        ctx: Resolved installation preferences and explicit native option keys.
        options: Existing immutable Inno options.

    Returns:
        Independent effective compiler settings.
    """
    install = ctx.installation
    if install is None or not inno_enabled(ctx):
        return options
    explicit = ctx.target.option_fields
    privileges = options.privileges if "privileges" in explicit else "admin" if install.scope == "machine" else "lowest"
    directory = options.default_dir if "default_dir" in explicit else install.directory
    if not directory:
        directory = ("{autopf}" if privileges == "admin" else "{localappdata}\\Programs") + "\\" + ctx.config.application.name
    values = dict(options.setup)
    managed = {key.lower() for key in values}
    additions = {"AppPublisher": install.publisher, "AppPublisherURL": install.homepage, "AppSupportURL": install.support_url,
                 "LicenseFile": str(ctx.resolve_path(install.license_file)) if install.license_file else "",
                 "UninstallDisplayIcon": "{app}\\wingsetup-assets\\app.ico" if install.icons.windows else "",
                 "DefaultGroupName": ctx.config.application.name, "UsePreviousAppDir": "yes", "UsePreviousTasks": "yes", "CloseApplications": "no", "RestartApplications": "no"}
    if install.file_types or install.protocols:
        additions["ChangesAssociations"] = "yes"
    if install.add_to_path:
        additions["ChangesEnvironment"] = "yes"
    for key, value in additions.items():
        if value and key.lower() not in managed:
            values[key] = value
    return replace(options, privileges=privileges, default_dir=directory,
                   setup_icon=options.setup_icon if "setup_icon" in explicit else install.icons.windows or options.setup_icon,
                   setup=tuple(values.items()))


def sections(ctx: BuildContext, options: InnoOptions) -> str:
    """Generate opted-in tasks, shortcuts, and ownership-aware runtime registrations.

    Args:
        ctx: Windows staged executable and shared metadata.
        options: Effective compiler options after native precedence.

    Returns:
        Complete extra Inno sections, or empty text when integration is unavailable.
    """
    install = ctx.installation
    if install is None or not inno_enabled(ctx):
        return ""
    app = ctx.config.application
    executable = "{app}\\" + ctx.executable_name
    icon = "{app}\\wingsetup-assets\\app.ico" if install.icons.windows else executable
    tasks: list[str] = []
    icons: list[str] = []
    run: list[str] = []
    if install.desktop and "desktop_shortcut" not in ctx.target.option_fields:
        tasks.append('Name: "wingsetup_desktop"; Description: "Create a desktop shortcut"; Flags: unchecked')
        icons.append(f'Name: "{{autodesktop}}\\{app.name}"; Filename: {quoted(executable)}; IconFilename: {quoted(icon)}; Tasks: wingsetup_desktop')
    if install.start_menu:
        icons.append(f'Name: "{{group}}\\{app.name}"; Filename: {quoted(executable)}; IconFilename: {quoted(icon)}')
    if install.add_to_path:
        tasks.append('Name: "wingsetup_path"; Description: "Add application directory to PATH"; Flags: unchecked')
    if install.autostart and options.privileges != "admin":
        tasks.append('Name: "wingsetup_autostart"; Description: "Start at user login"; Flags: unchecked')
    if install.context_menu:
        tasks.append('Name: "wingsetup_context"; Description: "Add Explorer context menu commands"; Flags: unchecked')
    if install.launch_after_install:
        run.append(f'Filename: {quoted(executable)}; Description: "Launch application"; Flags: postinstall nowait skipifsilent unchecked')
    statements: list[str] = []
    capabilities = "Software\\" + app.id + "\\Capabilities"
    classes = "Software\\Classes\\"

    def write(key: str, name: str, value: str, *, expand: bool = False) -> None:
        """Append an owned registry write, expanding only generated constants.

        Args:
            key: Registry path relative to the selected installation hive.
            name: Value name, including an empty default value.
            value: Literal text or a generated Inno command expression.
            expand: Whether generated installation constants must be expanded.
        """
        expression = "ExpandConstant(" + pascal(value) + ")" if expand else pascal(value)
        statements.append(f"  WingWrite({pascal(key)}, {pascal(name)}, {expression});")

    if install.file_types or install.protocols:
        write(capabilities, "ApplicationName", app.name)
        write(capabilities, "ApplicationDescription", app.summary)
        write(capabilities, "ApplicationIcon", icon, expand=True)
        write("Software\\RegisteredApplications", app.id, capabilities)
    for item in install.file_types:
        progid = app.id + ".File." + item.id
        key = classes + progid
        write(key, "", item.description)
        file_icon = "{app}\\wingsetup-assets\\" + item.id + ".ico" if item.icons.windows else icon
        write(key + "\\DefaultIcon", "", file_icon, expand=True)
        write(key + "\\shell\\open\\command", "", windows_command(executable, item.arguments, "{file}"), expand=True)
        for suffix in item.extensions:
            write(classes + suffix + "\\OpenWithProgids", progid, "")
            write(capabilities + "\\FileAssociations", suffix, progid)
    for item in install.protocols:
        progid = app.id + ".Url." + item.scheme
        key = classes + progid
        write(key, "", item.description)
        write(key, "URL Protocol", "")
        write(key + "\\DefaultIcon", "", icon, expand=True)
        write(key + "\\shell\\open\\command", "", windows_command(executable, item.arguments, "{url}"), expand=True)
        write(capabilities + "\\URLAssociations", item.scheme, progid)
    if install.autostart and options.privileges != "admin":
        statements.append("  if WizardIsTaskSelected('wingsetup_autostart') then begin")
        write("Software\\Microsoft\\Windows\\CurrentVersion\\Run", app.id, '"' + executable + '"', expand=True)
        statements.append("  end;")
    if install.context_menu:
        statements.append("  if WizardIsTaskSelected('wingsetup_context') then begin")
        for item in install.context_menu:
            for target in item.targets:
                parent = {"file": "*", "directory": "Directory", "background": "Directory\\Background"}[target]
                key = classes + parent + "\\shell\\" + app.id + "." + item.id
                write(key, "", item.label)
                write(key, "Icon", icon, expand=True)
                write(key + "\\command", "", windows_command(executable, item.arguments, "{path}", "%V" if target == "background" else "%1"), expand=True)
        statements.append("  end;")
    runtime = Path(__file__).with_name("inno_runtime.iss").read_text(encoding="utf-8")
    runtime = runtime.replace("@@OWNER@@", pascal("Software\\" + app.id + "\\WingSetup"))
    runtime = runtime.replace("@@WRITES@@", "\n".join(statements))
    runtime = runtime.replace("@@PATH_REQUEST@@", "WizardIsTaskSelected('wingsetup_path')" if install.add_to_path else "False")
    result = ""
    for heading, entries in (("Tasks", tasks), ("Icons", icons), ("Run", run)):
        if entries:
            result += "[" + heading + "]\n" + "\n".join(entries) + "\n"
    return result + runtime
