# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Inspect desktop integration inside packages without installing or registering them."""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import cast

from wingsetup.install_model import Installation
from wingsetup.model import SetupError
from wingsetup.validation import mapping, sequence, strings


def linux(prefix: Path, install: Installation, app_id: str) -> None:
    """Validate staged desktop files and rebuild MIME caches only in a temporary tree.

    Args:
        prefix: Extracted /usr or Flatpak /app tree.
        install: Expected typed handler declarations.
        app_id: Application export namespace.
    """
    applications = prefix / "share/applications"
    for desktop in applications.glob(f"{app_id}*.desktop"):
        subprocess.run(["desktop-file-validate", str(desktop)], check=True)
    if install.file_types:
        source = prefix / f"share/mime/packages/{app_id}.xml"
        tree = ET.parse(source)
        actual = {item.attrib.get("type") for item in tree.getroot()}
        if not {item.mime_type for item in install.file_types}.issubset(actual):
            raise SetupError("Packaged MIME declarations are incomplete")
        with tempfile.TemporaryDirectory(prefix="wingsetup-mime-") as temporary:
            mime = Path(temporary) / "mime"
            packages = mime / "packages"
            packages.mkdir(parents=True)
            shutil.copy2(source, packages / source.name)
            subprocess.run(["update-mime-database", str(mime)], check=True)
            if not (mime / "mime.cache").is_file():
                raise SetupError("Temporary MIME database was not generated")
    for item in install.file_types:
        desktop = applications / f"{app_id}.{item.id}.desktop"
        if f"MimeType={item.mime_type};" not in desktop.read_text(encoding="utf-8"):
            raise SetupError("Document handler missing from extracted package")
    for protocol in install.protocols:
        desktop = applications / f"{app_id}.url-{protocol.scheme}.desktop"
        if f"MimeType=x-scheme-handler/{protocol.scheme};" not in desktop.read_text(encoding="utf-8"):
            raise SetupError("URL handler missing from extracted package")


def macos(bundle: Path, install: Installation, app_id: str) -> None:
    """Inspect document and URL declarations in the extracted signed app bundle.

    Args:
        bundle: Extracted or read-only mounted .app directory.
        install: Expected immutable declarations.
        app_id: Namespace used to derive default UTIs.
    """
    info = cast(dict[str, object], plistlib.loads((bundle / "Contents/Info.plist").read_bytes()))
    documents = sequence(info.get("CFBundleDocumentTypes", []), "document types")
    urls = sequence(info.get("CFBundleURLTypes", []), "URL types")
    types = {uti for raw in documents for uti in strings(mapping(raw, "document").get("LSItemContentTypes", []), "document UTIs")}
    schemes = {scheme for raw in urls for scheme in strings(mapping(raw, "URL").get("CFBundleURLSchemes", []), "URL schemes")}
    for item in install.file_types:
        if (item.uti or app_id + "." + item.id) not in types:
            raise SetupError("Bundle document type missing from archive")
    for protocol in install.protocols:
        if protocol.scheme not in schemes:
            raise SetupError("Bundle URL scheme missing from archive")
    if install.icons.macos and not (bundle / "Contents/Resources/wingsetup-app.icns").is_file():
        raise SetupError("Bundle application icon was not archived")
