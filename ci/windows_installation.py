# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Explicitly validate example Inno installation, upgrades, and cleanup on ephemeral CI."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Callable

from wingsetup.core import BuildContext, CommandRunner
from wingsetup.backends.inno import InnoBackend, InnoOptions
from wingsetup.model import Config, SetupError, Target
from wingsetup.validation import mapping, sequence, string

if sys.platform == "win32":
    import winreg


#: Registry value snapshots retain the existing value and registry storage type.
RegistryValue = tuple[str, int] | None


def query(key: str, name: str = "") -> RegistryValue:
    """Read a current-user registry value without coercing its storage type.

    Args:
        key: Path relative to HKCU.
        name: Registry value name.

    Returns:
        Existing value and type, or None when absent.
    """
    if sys.platform == "win32":
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                value: object
                value, kind = winreg.QueryValueEx(handle, name)
                if not isinstance(value, str):
                    raise SetupError(f"Expected a string registry value: {key} {name}")
                return value, kind
        except FileNotFoundError:
            return None
    raise SetupError("Windows registry verification requires Windows")


def restore(key: str, name: str, value: RegistryValue) -> None:
    """Restore a snapshot, or remove only the value created by this CI fixture.

    Args:
        key: Current-user registry path.
        name: Individual value name to restore.
        value: Snapshot before the fixture touched this value.
    """
    if sys.platform == "win32":
        if value is None:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:
                    winreg.DeleteValue(handle, name)
            except FileNotFoundError:
                pass
        else:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
                winreg.SetValueEx(handle, name, 0, value[1], value[0])
        return
    raise SetupError("Windows registry verification requires Windows")


def run(arguments: list[str]) -> str:
    """Run one explicit example verification command with bounded diagnostics.

    Args:
        arguments: Executable and argument list; no shell interpolation.

    Returns:
        Successful combined process output.

    Raises:
        SetupError: The command fails or exceeds the installer timeout.
    """
    try:
        result = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", timeout=180, check=False)
    except subprocess.TimeoutExpired as exc:
        raise SetupError(f"Installer check timed out: {arguments}") from exc
    except OSError as exc:
        raise SetupError(f"Cannot start installer command: {arguments}: {exc}") from exc
    print(result.stdout, end="", flush=True)
    if result.returncode != 0:
        raise SetupError(f"Installer command failed ({result.returncode}): {arguments}\n{result.stdout}")
    return result.stdout


def shortcuts(logs: Path, installed: Path) -> list[Path]:
    """Validate target and icon paths through Windows' native shortcut reader.

    Args:
        logs: Persistent CI diagnostic directory.
        installed: Expected installed executable directory.

    Returns:
        Shortcut paths checked for removal after uninstall.
    """
    script = logs / "check-shortcuts.ps1"
    script.write_text("""param([string]$InstallRoot)
$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('Desktop')
$programs = [Environment]::GetFolderPath('Programs')
$shell = New-Object -ComObject WScript.Shell
$links = @((Join-Path $desktop 'WidgetsDemo.lnk'), (Join-Path $programs 'WidgetsDemo/WidgetsDemo.lnk'))
$results = @(foreach ($path in $links) {
  if (!(Test-Path -LiteralPath $path)) { throw "Missing shortcut: $path" }
  $link = $shell.CreateShortcut($path)
  [PSCustomObject]@{path = $path; target = $link.TargetPath; icon = $link.IconLocation}
})
ConvertTo-Json -InputObject $results -Compress
""", encoding="utf-8-sig")
    output = run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), str(installed)])
    (logs / "shortcuts.json").write_text(output, encoding="utf-8")
    value: object = json.loads(output)
    checked: list[Path] = []
    expected_target = installed / "widgets-demo.exe"
    expected_icon = installed / "wingsetup-assets/app.ico"
    for raw in sequence(value, "shortcut results"):
        item = mapping(raw, "shortcut")
        path = Path(string(item.get("path"), "shortcut.path"))
        actual_target = Path(string(item.get("target"), "shortcut.target"))
        icon_text = string(item.get("icon"), "shortcut.icon")
        icon_path, separator, icon_index = icon_text.rpartition(",")
        actual_icon = Path((icon_path if separator else icon_text).strip().strip('"'))
        try:
            # File identity handles Windows 8.3 names, casing, junctions, and long paths.
            if not actual_target.samefile(expected_target):
                raise SetupError(f"Wrong shortcut target in {path}: actual={actual_target!s}; expected={expected_target!s}")
            if (separator and icon_index.strip() != "0") or not actual_icon.samefile(expected_icon):
                raise SetupError(f"Wrong shortcut icon in {path}: actual={icon_text}; expected={expected_icon!s},0")
        except OSError as exc:
            raise SetupError(f"Cannot inspect shortcut files in {path}: target={actual_target!s}; icon={icon_text}: {exc}") from exc
        checked.append(path)
    if len(checked) != 2 or len(set(checked)) != 2:
        raise SetupError("Shortcut inspection must return both distinct fixture shortcuts")
    return checked


def registered_uninstaller(installed: Path, key: str, logs: Path, phase: str) -> Path:
    """Resolve the fixture's actual uninstaller from its application registration.

    Args:
        installed: Exact fixture installation directory authorized for execution.
        key: Current-user uninstall key for the fixture's stable AppId.
        logs: Persistent diagnostic directory.
        phase: Fixture-owned snapshot phase identifier.

    Returns:
        Existing registered Inno uninstaller inside the fixture directory.

    Raises:
        SetupError: Registration is missing, malformed, outside the fixture, or stale.
    """
    value = query(key, "UninstallString")
    snapshot = {"registration": value, "installed": str(installed),
                "available": sorted(str(path) for path in installed.glob("unins*.exe"))}
    (logs / f"uninstaller-{phase}.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    if value is None or value[1] not in (1, 2):
        raise SetupError(f"Missing fixture UninstallString after {phase}: {key}")
    try:
        parts = shlex.split(value[0], posix=False)
    except ValueError as exc:
        raise SetupError(f"Malformed fixture UninstallString after {phase}: {value[0]!r}") from exc
    if len(parts) != 1:
        raise SetupError(f"Expected one quoted uninstaller pathname after {phase}: {value[0]!r}")
    executable = Path(parts[0].strip('"'))
    if not re.fullmatch(r"unins[0-9]+\.exe", executable.name, flags=re.IGNORECASE) or executable.resolve().parent != installed.resolve():
        raise SetupError(f"Registered uninstaller escapes fixture directory after {phase}: {executable}")
    if not executable.is_file():
        raise SetupError(f"Registered uninstaller is missing after {phase}: {executable}; available={snapshot['available']}")
    return executable


def check_path(logs: Path, phase: str, expected: RegistryValue, owner: str,
               expected_entry: str | None) -> None:
    """Persist and compare exact PATH content, registry type, and installation ownership.

    Args:
        logs: Persistent example diagnostic directory.
        phase: Fixture-owned phase identifier used for the snapshot filename.
        expected: Exact unrelated tokens and registry type that must be preserved.
        owner: Application-owned registry tracking key.
        expected_entry: Owned installed directory, or None after uninstall.

    Raises:
        SetupError: PATH content, type, or ownership differs from expectations.
    """
    actual = query("Environment", "Path")
    actual_entry = query(owner, "PathEntry")
    wanted_entry = None if expected_entry is None else (expected_entry, 1)
    snapshot = {"expected": expected, "actual": actual, "expected_entry": wanted_entry,
                "actual_entry": actual_entry, "path_created": query(owner, "PathCreated")}
    (logs / f"path-{phase}.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    if actual != expected or actual_entry != wanted_entry:
        raise SetupError(f"PATH validation failed after {phase}: expected={expected!r}; actual={actual!r}; "
                         f"expected ownership={wanted_entry!r}; actual ownership={actual_entry!r}")


def verify(config: Config, target: Target, installer: Path,
           launch: Callable[[list[str]], str]) -> dict[str, bool]:
    """Install only the repository fixture and prove upgrade and uninstall behavior.

    Args:
        config: Trusted Qt Widgets example configuration.
        target: Explicit native Inno example target.
        installer: Installer produced in this example job.
        launch: Existing clean-environment Qt smoke launcher.

    Returns:
        Independent success evidence for installation, upgrade, and uninstall.

    Raises:
        SetupError: Used outside the ephemeral CI fixture or an acceptance check fails.
    """
    expected_config = Path(__file__).resolve().parents[1] / "examples/qtwidgets/package.yml"
    if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true" or config.path.resolve() != expected_config.resolve() or config.application.id != "org.example.Widgets" or target.name != "windows":
        raise SetupError("Installer execution is restricted to the explicitly selected Qt Windows example on GitHub CI")
    options = target.options
    install = target.installation or config.installation
    if not isinstance(options, InnoOptions) or install is None:
        raise SetupError("Installer fixture lacks typed Inno integration")
    logs = config.output / target.name / "installation-validation"
    logs.mkdir(parents=True, exist_ok=True)
    extension_key = "Software\\Classes\\.wingsetup-demo"
    default_choice = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\.wingsetup-demo\\UserChoice"
    protocol_choice = "Software\\Microsoft\\Windows\\Shell\\Associations\\UrlAssociations\\wingsetup-demo\\UserChoice"
    before_protocol_choice = query(protocol_choice, "ProgId")
    before_default = query(extension_key)
    before_choice = query(default_choice, "ProgId")
    before_path = query("Environment", "Path")
    app = config.application
    classes = "Software\\Classes\\" + app.id
    capabilities = "Software\\" + app.id + "\\Capabilities"
    owner = "Software\\" + app.id + "\\WingSetup"
    selected_tasks = "wingsetup_desktop,wingsetup_path,wingsetup_autostart,wingsetup_context"
    uninstall_key = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + (options.app_id or app.id) + "_is1"
    with tempfile.TemporaryDirectory(prefix="wingsetup-install-") as temporary:
        root = Path(temporary).resolve()
        installed = root / "Application With Spaces"
        uninstall: Path | None = None
        baseline = (str(before_path[0]) if before_path else "") + ";;" + str(root / "unrelated-path") + ";"
        kind = before_path[1] if before_path else 2
        # A sentinel default must remain untouched by candidate registrations.
        restore(extension_key, "", ("WingSetup.ExternalFixture", 1))
        restore("Environment", "Path", (baseline, kind))
        evidence: dict[str, bool] = {}
        uninstall_finished = False
        try:
            run([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/DIR={installed}", f"/TASKS={selected_tasks}", f"/LOG={logs / 'install.log'}"])
            uninstall = registered_uninstaller(installed, uninstall_key, logs, "install")
            executable = installed / "widgets-demo.exe"
            launch([str(executable), "--smoke"])
            links = shortcuts(logs, installed)
            for key, name in ((classes + ".File.demo\\shell\\open\\command", ""),
                              (capabilities + "\\FileAssociations", ".wingsetup-demo"),
                              (capabilities + "\\URLAssociations", "wingsetup-demo"),
                              ("Software\\Microsoft\\Windows\\CurrentVersion\\Run", app.id),
                              ("Software\\Classes\\Directory\\shell\\" + app.id + ".open\\command", "")):
                if query(key, name) is None:
                    raise SetupError(f"Missing installed registration: {key} {name}")
            if query(extension_key) != ("WingSetup.ExternalFixture", 1) or query(default_choice, "ProgId") != before_choice or query(protocol_choice, "ProgId") != before_protocol_choice:
                raise SetupError("Installer changed a pre-existing default application")
            registered_command = query(classes + ".File.demo\\shell\\open\\command")
            expected_command = '"' + str(executable) + '" "%1"'
            if registered_command != (expected_command, 1):
                raise SetupError("Installed file-handler command lost executable/input quoting")
            expected_path = baseline + ";" + str(installed)
            check_path(logs, "install", (expected_path, kind), owner, str(installed))
            if query(uninstall_key, "DisplayVersion") != (app.version, 1):
                raise SetupError("Uninstall display metadata differs from the installed version")
            evidence["installed"] = True
            user_data = installed / "user-data.txt"
            user_data.write_text("must survive upgrade and uninstall", encoding="utf-8")
            work = max(config.workspace.glob(f"{target.name}-*"), key=lambda item: item.stat().st_mtime_ns)
            payload = work / "root"
            (payload / "upgrade-proof.txt").write_text("upgrade payload", encoding="utf-8")
            next_install = replace(install, file_types=tuple(item for item in install.file_types if item.id != "obsolete"),
                                   protocols=tuple(item for item in install.protocols if item.scheme != "wingsetup-obsolete"))
            upgraded_config = replace(config, application=replace(app, version="0.1.1"), output=root / "upgrade-output")
            upgraded_target = replace(target, installation=next_install)
            upgrade_work = root / "upgrade-work"
            upgrade_work.mkdir()
            context = BuildContext(upgraded_config, upgraded_target, upgrade_work, work / "build", payload, CommandRunner(logs / "upgrade-build.log"))
            upgraded = next(item.path for item in InnoBackend().package(context) if item.format == "inno")
            # Compile pure PATH round-trip checks into this explicit CI fixture only.
            upgrade_script = upgrade_work / "installer.iss"
            checks = Path(__file__).with_name("inno_path_checks.iss").read_text(encoding="utf-8")
            with upgrade_script.open("a", encoding="utf-8") as stream:
                stream.write("\n" + checks.split("[Code]", 1)[1])
            context.run([options.iscc, f"/O{upgraded.parent}", f"/F{upgraded.stem}", str(upgrade_script)])
            # No /DIR or /TASKS: verify the installer's remembered choices.
            run([str(upgraded), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/LOG={logs / 'upgrade.log'}"])
            if not (installed / "upgrade-proof.txt").is_file() or not user_data.is_file():
                raise SetupError("Upgrade did not preserve directory or user data")
            shortcuts(logs, installed)
            if query(capabilities + "\\FileAssociations", ".wingsetup-obsolete") is not None or query(capabilities + "\\URLAssociations", "wingsetup-obsolete") is not None:
                raise SetupError("Upgrade retained obsolete managed associations")
            if query(uninstall_key, "DisplayVersion") != ("0.1.1", 1):
                raise SetupError("Upgrade did not update uninstall metadata")
            uninstall = registered_uninstaller(installed, uninstall_key, logs, "upgrade")
            check_path(logs, "upgrade", (expected_path, kind), owner, str(installed))
            evidence["upgraded"] = True
            run([str(uninstall), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={logs / 'uninstall.log'}"])
            uninstall_finished = True
            if executable.exists() or any(link.exists() for link in links) or not user_data.is_file():
                raise SetupError("Uninstall payload/shortcut cleanup or user-data preservation failed")
            check_path(logs, "uninstall", (baseline, kind), owner, None)
            for key, name in ((capabilities + "\\FileAssociations", ".wingsetup-demo"),
                              ("Software\\RegisteredApplications", app.id),
                              ("Software\\Microsoft\\Windows\\CurrentVersion\\Run", app.id),
                              (classes + ".File.demo\\shell\\open\\command", "")):
                if query(key, name) is not None:
                    raise SetupError("Uninstall left a managed registration")
            if query(extension_key) != ("WingSetup.ExternalFixture", 1) or query(default_choice, "ProgId") != before_choice or query(protocol_choice, "ProgId") != before_protocol_choice:
                raise SetupError("Upgrade or uninstall changed a pre-existing default application")
            # Isolate this independent scenario from delayed self-deletion of the prior uninstaller.
            installed = root / "Preexisting PATH With Spaces"
            uninstall = None
            # Existing PATH tokens must never be claimed or removed on uninstall.
            unowned_path = baseline + '"' + str(installed) + '\\"'
            restore("Environment", "Path", (unowned_path, 1))
            uninstall_finished = False
            run([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/DIR={installed}", f"/TASKS={selected_tasks}", f"/LOG={logs / 'preexisting-path-install.log'}"])
            uninstall = registered_uninstaller(installed, uninstall_key, logs, "preexisting-install")
            launch([str(installed / "widgets-demo.exe"), "--smoke"])
            shortcuts(logs, installed)
            check_path(logs, "preexisting-install", (unowned_path, 1), owner, None)
            run([str(uninstall), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={logs / 'preexisting-path-uninstall.log'}"])
            uninstall_finished = True
            check_path(logs, "preexisting-uninstall", (unowned_path, 1), owner, None)
            evidence["uninstalled"] = True
            return evidence
        finally:
            if not uninstall_finished and uninstall is not None and uninstall.exists():
                try:
                    run([str(uninstall), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={logs / 'failure-cleanup.log'}"])
                except SetupError as exc:
                    print(f"Installer cleanup diagnostic: {exc}", flush=True)
            restore("Environment", "Path", before_path)
            restore(extension_key, "", before_default)
