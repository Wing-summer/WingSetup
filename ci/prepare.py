# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Provision explicit example dependencies on disposable GitHub runners."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import cast

#: Repository root containing the tool lock and workspace-local download cache.
ROOT = Path(__file__).resolve().parents[1]


def run(arguments: list[str], cwd: Path | None = None) -> str:
    """Run a provisioning command and retain its output for actionable failures.

    Args:
        arguments: Explicit executable and argument list.
        cwd: Optional command working directory.

    Returns:
        Captured standard output from the successful command.
    """
    result = subprocess.run(arguments, cwd=cwd, check=True, text=True, stdout=subprocess.PIPE)
    print(result.stdout, end="", flush=True)
    return result.stdout


def export_path(directory: Path) -> None:
    """Make a prepared tool directory available to subsequent GitHub steps.

    Args:
        directory: Directory containing executable wrappers.
    """
    destination = os.environ.get("GITHUB_PATH")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.write(str(directory) + "\n")
    print(f"Prepared tool directory: {directory}")


def prepare_tools() -> None:
    """Verify and extract locked Linux tools without FUSE or system installation.

    Downloaded bytes must match the checked-in SHA-256 lock. A changed upstream
    continuous asset fails closed until its lock is reviewed explicitly.
    """
    tools = ROOT / ".tools" / "ci"
    tools.mkdir(parents=True, exist_ok=True)
    bin_dir = tools / "bin"
    bin_dir.mkdir(exist_ok=True)
    lock = cast(dict[str, dict[str, str]], json.loads((ROOT / "ci/tools.lock.json").read_text(encoding="utf-8")))
    for name, spec in lock.items():
        path = tools / name
        if not path.exists():
            temporary = path.with_suffix(".download")
            with urllib.request.urlopen(spec["url"], timeout=90) as source, temporary.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            temporary.replace(path)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != spec["sha256"]:
            raise RuntimeError(f"Tool checksum mismatch: {name}; review the lock before updating")
        if name.endswith(".AppImage"):
            path.chmod(0o755)
            unpack = tools / (name + ".unpacked")
            if not unpack.exists():
                unpack.mkdir()
                run([str(path), "--appimage-extract"], cwd=unpack)
            executable = unpack / "squashfs-root/AppRun"
            wrapper = bin_dir / name.removesuffix("-x86_64.AppImage")
            wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(str(executable))} "$@"\n', encoding="utf-8")
            wrapper.chmod(0o755)
    (tools / "makeself.sh").chmod(0o755)
    wrapper = bin_dir / "makeself"
    wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(str(tools / "makeself.sh"))} "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    qt_root = os.environ.get("QT_ROOT_DIR")
    qmake = str(Path(qt_root) / "bin/qmake") if qt_root else shutil.which("qmake6") or shutil.which("qmake")
    if qmake:
        wrapper = bin_dir / "qmake6"
        wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(qmake)} "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
    export_path(bin_dir)


def linux_qt_packages(ubuntu_version: str) -> tuple[str, ...]:
    """Select distro Qt dependencies using the release's SVG package name.

    Args:
        ubuntu_version: VERSION_ID read from the Ubuntu runner's os-release.

    Returns:
        Apt package names for the Qt Widgets, translation, SVG, and Wayland fixture.
    """
    # Jammy ships SVG plugins inside libqt6svg6, pulled in by its development package.
    svg = ("libqt6svg6-dev",) if ubuntu_version == "22.04" else ("qt6-svg-dev", "qt6-svg-plugins")
    return ("cmake", "ninja-build", "qt6-base-dev", "qt6-tools-dev",
            "qt6-tools-dev-tools", "qt6-wayland", *svg)


def main() -> None:
    """Prepare dependencies for a named CI group or only download local tools.

    Local invocation requires --tools-only and never installs system packages or
    Flatpak runtimes. Native package installation is restricted to GitHub runners.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", choices=("linux", "flatpak", "native"))
    parser.add_argument("--tools-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.tools_only:
        if platform.system() != "Linux" or arguments.group != "linux":
            parser.error("--tools-only supports the Linux download tools")
        prepare_tools()
        return
    if os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("System provisioning is CI-only; use linux --tools-only locally")
    system = platform.system()
    if arguments.group == "linux":
        run(["sudo", "apt-get", "update"])
        run(["sudo", "apt-get", "install", "-y", "build-essential", "desktop-file-utils", "dpkg-dev",
             "libgl1", "libegl1", "libxkbcommon-x11-0", "libxcb-cursor0", "weston"])
        if os.environ.get("EXAMPLE_QT") == "true":
            # Distro Qt preserves the runner's glibc baseline, including Jammy.
            version = platform.freedesktop_os_release().get("VERSION_ID", "")
            run(["sudo", "apt-get", "install", "-y", *linux_qt_packages(version)])
        prepare_tools()
    elif arguments.group == "flatpak":
        run(["sudo", "apt-get", "update"])
        run(["sudo", "apt-get", "install", "-y", "build-essential", "flatpak", "flatpak-builder", "desktop-file-utils"])
        run(["sudo", "flatpak", "remote-add", "--if-not-exists", "flathub", "https://flathub.org/repo/flathub.flatpakrepo"])
        run(["sudo", "flatpak", "install", "-y", "flathub", "org.kde.Platform//6.10", "org.kde.Sdk//6.10"])
    elif system == "Windows":
        if not shutil.which("ISCC.exe"):
            run(["choco", "install", "innosetup", "-y", "--no-progress"])
        export_path(Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 6")


if __name__ == "__main__":
    main()
