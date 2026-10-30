# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Render staged desktop integrations and report format-specific installation capabilities."""

from __future__ import annotations

import json
import plistlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .console import get_console
from .install_model import InstallationIcons
from .model import Artifact, SetupError

if TYPE_CHECKING:
    from .core import BuildContext


#: Portable resources and native desktop declarations supported by Linux package backends.
LINUX_FEATURES = frozenset({"license_file", "icons.linux", "file_types", "protocols"})
#: Features implemented by Inno's generated installer integration.
INNO_FEATURES = frozenset({"publisher", "homepage", "support_url", "license_file", "icons.windows", "scope",
                           "directory", "shortcuts.start_menu", "shortcuts.desktop", "launch_after_install",
                           "file_types", "protocols", "add_to_path", "autostart", "context_menu"})
#: Metadata that belongs in a signed macOS application bundle.
MAC_FEATURES = frozenset({"license_file", "icons.macos", "file_types", "protocols"})


def inno_enabled(ctx: BuildContext) -> bool:
    """Determine whether shared settings have an explicit Inno template integration point.

    Args:
        ctx: Target whose optional project-owned template is inspected.

    Returns:
        True for the default template or both required insertion points.
    """
    from .backends.inno import InnoOptions
    options = ctx.target.options
    if not isinstance(options, InnoOptions) or options.script is None:
        return True
    script = ctx.resolve_path(options.script)
    if not script.is_file():
        return False
    content = script.read_text(encoding="utf-8-sig")
    return "@INSTALLATION_SECTIONS@" in content and "@SETUP_DIRECTIVES@" in content


def inno_asset_modes(ctx: BuildContext) -> tuple[bool, bool]:
    """Determine whether portable assets and document icons are actually consumed.

    Args:
        ctx: Inno formats and optional custom-template integration points.

    Returns:
        Whether common assets and native document icons are used respectively.
    """
    from .backends.inno import InnoOptions
    options = ctx.target.options
    if not isinstance(options, InnoOptions):
        return True, True
    native = "inno" in options.formats and inno_enabled(ctx)
    return native or "zip" in options.formats, native


def selected_icon(icons: InstallationIcons, platform: str) -> Path | None:
    """Select an icon source without inspecting assets intended for another platform.

    Args:
        icons: Explicit immutable source assets.
        platform: Linux, Windows, or Darwin platform identifier.

    Returns:
        Applicable source or None.
    """
    return {"Linux": icons.linux, "Windows": icons.windows, "Darwin": icons.macos}.get(platform)


def asset(ctx: BuildContext, source: Path, destination: Path) -> None:
    """Copy a used asset through the context's staging boundary checks.

    Args:
        ctx: Target-local file copying services.
        source: YAML-relative or generated source path.
        destination: Absolute destination within the deployment tree.
    """
    resolved = ctx.resolve_path(source)
    if not resolved.is_file():
        raise SetupError(f"Missing installation asset: {resolved}")
    ctx.copy(resolved, destination.relative_to(ctx.deploy_dir).as_posix())


def windows_asset_path(ctx: BuildContext, identity: str) -> Path:
    """Return a stable installed icon path reserved for integration metadata.

    Args:
        ctx: Windows payload root.
        identity: Application or document identity.

    Returns:
        Absolute staged ICO pathname.
    """
    return ctx.app_dir / "wingsetup-assets" / f"{identity}.ico"


def linux_icon(ctx: BuildContext, source: Path, name: str, category: str) -> None:
    """Stage a PNG/SVG icon in the standard theme hierarchy.

    Args:
        ctx: Linux staged prefix.
        source: Icon source to validate and copy.
        name: Icon name advertised in desktop or MIME metadata.
        category: Theme context, apps or mimetypes.
    """
    size = "scalable" if source.suffix.lower() == ".svg" else "256x256"
    asset(ctx, source, ctx.prefix_dir / f"share/icons/hicolor/{size}/{category}/{name}{source.suffix.lower()}")


def desktop_update(path: Path, updates: dict[str, str]) -> None:
    """Replace managed Desktop Entry keys while preserving comments and localized keys.

    Args:
        path: Existing desktop file.
        updates: Exact unlocalized keys owned by this operation.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    in_entry = False
    inserted = False
    for line in lines:
        if line.startswith("["):
            if in_entry:
                output.extend(f"{key}={value}" for key, value in updates.items())
                inserted = True
            in_entry = line.strip() == "[Desktop Entry]"
        if in_entry and not line.startswith("[") and line.partition("=")[0] in updates:
            continue
        output.append(line)
    if in_entry:
        output.extend(f"{key}={value}" for key, value in updates.items())
        inserted = True
    if not inserted:
        raise SetupError(f"Desktop Entry section missing: {path}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def desktop_command(executable: str, arguments: tuple[str, ...], token: str, code: str) -> str:
    """Quote desktop arguments using the desktop specification, without a shell.

    Args:
        executable: Installed program name.
        arguments: Validated literal arguments and one dynamic token.
        token: Shared placeholder to replace.
        code: Desktop field code, %f or %u.

    Returns:
        A desktop Exec value with quoted literals and one unquoted field code.
    """
    parts = [executable]
    for value in arguments:
        if value == token:
            parts.append(code)
        else:
            escaped = value.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
            parts.append('"' + escaped + '"')
    return " ".join(parts)


def apply_linux(ctx: BuildContext) -> None:
    """Write desktop/MIME declarations only inside the staged Linux prefix.

    Args:
        ctx: Linux package, AppDir, or Flatpak deployment before finish/export.
    """
    install = ctx.installation
    if install is None:
        return
    app = ctx.config.application
    desktop = ctx.prefix_dir / f"share/applications/{app.id}.desktop"
    if install.icons.linux:
        for old in (ctx.prefix_dir / "share/icons/hicolor").glob(f"*/apps/{app.id}.*"):
            if old.suffix.lower() in {".png", ".svg"} and old.suffix.lower() != install.icons.linux.suffix.lower():
                old.unlink()
        linux_icon(ctx, install.icons.linux, app.id, "apps")
    if install.file_types or install.protocols:
        mime = ET.Element("mime-info", {"xmlns": "http://www.freedesktop.org/standards/shared-mime-info"})
        for item in install.file_types:
            entry = ET.SubElement(mime, "mime-type", {"type": item.mime_type})
            ET.SubElement(entry, "comment").text = item.description
            for suffix in item.extensions:
                ET.SubElement(entry, "glob", {"pattern": "*" + suffix})
            if item.icons.linux:
                icon_name = app.id + ".type." + item.id
                linux_icon(ctx, item.icons.linux, icon_name, "mimetypes")
                ET.SubElement(entry, "icon", {"name": icon_name})
        if install.file_types:
            destination = ctx.prefix_dir / f"share/mime/packages/{app.id}.xml"
            destination.parent.mkdir(parents=True, exist_ok=True)
            ET.indent(mime)
            ET.ElementTree(mime).write(destination, encoding="utf-8", xml_declaration=True)
        # Separate hidden entries preserve distinct argument contracts per handler.
        handlers = [(item.id, item.description, item.mime_type, item.arguments, "{file}", "%f") for item in install.file_types]
        handlers += [("url-" + item.scheme, item.description, "x-scheme-handler/" + item.scheme, item.arguments, "{url}", "%u") for item in install.protocols]
        for identity, description, mime_type, arguments, token, code in handlers:
            handler = desktop.with_name(f"{app.id}.{identity}.desktop")
            handler.write_text("[Desktop Entry]\nType=Application\n" + f"Name={app.name}\nComment={description}\nIcon={app.id}\nNoDisplay=true\n" +
                               f"Exec={desktop_command(ctx.executable_name, arguments, token, code)}\nMimeType={mime_type};\n", encoding="utf-8")
        # Existing application handlers and localized metadata remain untouched.
        if not desktop.is_file():
            raise SetupError(f"Missing application desktop entry: {desktop}")


def apply_macos(ctx: BuildContext) -> None:
    """Merge bundle declarations before final signing, retaining unrelated metadata.

    Args:
        ctx: Staged macOS application bundle.
    """
    install = ctx.installation
    bundle = ctx.layout.bundle
    if install is None or bundle is None:
        return
    app = ctx.config.application
    path = bundle / "Contents/Info.plist"
    info = cast(dict[str, object], plistlib.loads(path.read_bytes()))
    resources = bundle / "Contents/Resources"
    if install.icons.macos:
        name = "wingsetup-app.icns"
        asset(ctx, install.icons.macos, resources / name)
        info["CFBundleIconFile"] = name
    managed = info.get("WingSetupManagedIntegration", {})
    previous: dict[str, object] = cast(dict[str, object], managed) if isinstance(managed, dict) else {}
    documents: list[object] = []
    declarations: list[object] = []
    urls: list[object] = []
    document_ids: list[str] = []
    uti_ids: list[str] = []
    url_ids: list[str] = []
    for item in install.file_types:
        uti = item.uti or app.id + "." + item.id
        document_ids.append(uti)
        document: dict[str, object] = {"CFBundleTypeName": item.description, "CFBundleTypeRole": item.role.title(), "LSHandlerRank": "Alternate", "LSItemContentTypes": [uti]}
        if item.icons.macos:
            name = f"wingsetup-{item.id}.icns"
            asset(ctx, item.icons.macos, resources / name)
            document["CFBundleTypeIconFile"] = name
        documents.append(document)
        if not item.uti:
            uti_ids.append(uti)
            declarations.append({"UTTypeIdentifier": uti, "UTTypeDescription": item.description, "UTTypeConformsTo": ["public.data"],
                                 "UTTypeTagSpecification": {"public.filename-extension": [suffix[1:] for suffix in item.extensions], "public.mime-type": item.mime_type}})
    for item in install.protocols:
        name = app.id + ".url." + item.scheme
        url_ids.append(name)
        urls.append({"CFBundleURLName": name, "CFBundleURLSchemes": [item.scheme], "CFBundleTypeRole": "Editor"})
    for key, identity_key, fresh, identities in (("CFBundleDocumentTypes", "LSItemContentTypes", documents, document_ids),
                                                ("UTImportedTypeDeclarations", "UTTypeIdentifier", declarations, uti_ids),
                                                ("CFBundleURLTypes", "CFBundleURLName", urls, url_ids)):
        old = info.get(key, [])
        removed = previous.get(key, [])
        preserved: list[object] = []
        if isinstance(old, list):
            for raw in cast(list[object], old):
                if isinstance(raw, dict):
                    entry = cast(dict[str, object], raw)
                    identity = entry.get(identity_key)
                    names: list[object] = cast(list[object], identity) if isinstance(identity, list) else [identity]
                    if any(name in identities or (isinstance(removed, list) and name in removed) for name in names):
                        continue
                preserved.append(cast(object, raw))
        if fresh or key in info:
            info[key] = preserved + fresh
    info["WingSetupManagedIntegration"] = {"CFBundleDocumentTypes": document_ids, "UTImportedTypeDeclarations": uti_ids, "CFBundleURLTypes": url_ids}
    path.write_bytes(plistlib.dumps(info, sort_keys=False))


def license_destination(ctx: BuildContext) -> Path:
    """Choose a namespaced Linux license location or an application-local resource.

    Args:
        ctx: Target deployment layout and application identity.

    Returns:
        Installed license pathname that does not conflict with another application.
    """
    if ctx.target.backend in {"deb", "rpm", "arch", "appimage", "flatpak"}:
        return ctx.prefix_dir / "share/licenses" / ctx.config.application.id / "LICENSE.txt"
    return ctx.layout.resources / "licenses/LICENSE.txt"


def apply_installation(ctx: BuildContext) -> None:
    """Carry supported assets and write native staged metadata without host changes.

    Args:
        ctx: Current target with immutable resolved preferences.
    """
    install = ctx.installation
    if install is None:
        return
    common_assets, document_assets = inno_asset_modes(ctx)
    if ctx.target.backend == "inno" and not common_assets:
        return
    if install.license_file:
        destination = license_destination(ctx)
        asset(ctx, install.license_file, destination)
    if ctx.target.backend in {"deb", "rpm", "arch", "appimage", "flatpak"}:
        apply_linux(ctx)
    elif ctx.target.backend == "macos":
        apply_macos(ctx)
    elif ctx.target.backend == "inno":
        if install.icons.windows:
            asset(ctx, install.icons.windows, windows_asset_path(ctx, "app"))
        if document_assets:
            for item in install.file_types:
                if item.icons.windows:
                    asset(ctx, item.icons.windows, windows_asset_path(ctx, item.id))


def feature_results(ctx: BuildContext, format_name: str) -> list[dict[str, str]]:
    """Describe effective requested capabilities for one concrete output format.

    Args:
        ctx: Target and resolved installer configuration.
        format_name: Actual package format, distinguishing Inno from portable ZIP.

    Returns:
        Applied/ignored records with concrete reasons.
    """
    from .backends.inno import InnoOptions
    install = ctx.installation
    if install is None:
        return []
    from .registry import registration
    spec = registration(ctx.target.backend)
    capabilities = spec.installation_features if spec else frozenset({"license_file"})
    if ctx.target.backend == "inno" and format_name != "inno":
        capabilities = frozenset({"license_file", "icons.windows"})
    template = ctx.target.backend == "inno" and format_name == "inno" and not inno_enabled(ctx)
    result: list[dict[str, str]] = []
    overrides = {"scope": "privileges", "directory": "default_dir", "shortcuts.desktop": "desktop_shortcut"}
    options = ctx.target.options
    native_setup = {key.lower() for key, _ in options.setup} if isinstance(options, InnoOptions) else set[str]()
    setup_overrides = {"publisher": "apppublisher", "homepage": "apppublisherurl", "support_url": "appsupporturl", "license_file": "licensefile"}
    for feature in sorted(install.specified):
        supported = feature in capabilities
        reason = "Supported by this output format" if supported else "Unsupported by this output format; skipped"
        if template:
            supported, reason = False, "Custom ISS lacks the shared installation insertion points"
        if feature in overrides and overrides[feature] in ctx.target.option_fields and ctx.target.backend == "inno":
            supported, reason = False, "Explicit backend option takes precedence"
        if feature in setup_overrides and setup_overrides[feature] in native_setup and ctx.target.backend == "inno":
            supported, reason = False, "Explicit native [Setup] directive takes precedence"
        machine = install.scope == "machine"
        if isinstance(options, InnoOptions) and "privileges" in ctx.target.option_fields:
            machine = options.privileges == "admin"
        if feature == "autostart" and machine:
            supported, reason = False, "Current-user startup is not applied by a machine-scope installer"
        if feature == "autostart" and ctx.target.backend == "flatpak":
            reason = "Application must request the Background portal; no permission is granted by packaging"
        if ctx.target.backend == "macos" and feature in {"file_types", "protocols"}:
            reason = "Bundle declarations use OS open events; application handles delivery, not CLI argument rewriting"
        if ctx.target.backend == "appimage" and supported:
            reason = "Included in AppDir; host registration requires an external integration tool"
        if ctx.target.backend == "inno" and format_name == "zip" and supported:
            reason = "Asset carried in ZIP; no host registration is performed"
        result.append({"feature": feature, "status": "applied" if supported else "ignored", "reason": reason})
    return result


def installation_requirements(ctx: BuildContext) -> tuple[str, ...]:
    """Check only source assets used by the selected platform, without loading hooks.

    Args:
        ctx: Target-local configuration used by the check command.

    Returns:
        Missing static assets; generated build/work paths are checked during deploy.
    """
    install = ctx.installation
    if install is None:
        return ()
    common_assets, document_assets = inno_asset_modes(ctx)
    if ctx.target.backend == "inno" and not common_assets:
        return ()
    sources = [install.license_file]
    if ctx.target.backend in {"deb", "rpm", "arch", "appimage", "flatpak", "inno", "macos"}:
        sources += [selected_icon(install.icons, ctx.target.platform)]
        if document_assets:
            sources += [selected_icon(item.icons, ctx.target.platform) for item in install.file_types]
    errors: list[str] = []
    for source in sources:
        if source is not None and not any(token in str(source) for token in ("{build}", "{work}")) and not ctx.resolve_path(source).is_file():
            errors.append(f"Installation asset: {source}")
    return tuple(errors)


def validate_staged_installation(ctx: BuildContext) -> None:
    """Reject final exclusions that would leave managed native metadata dangling.

    Args:
        ctx: Completed, filtered deployment tree before signing or packaging.

    Raises:
        SetupError: A required integration asset was removed after deployment.
    """
    install = ctx.installation
    if install is None:
        return
    common_assets, document_assets = inno_asset_modes(ctx)
    if ctx.target.backend == "inno" and not common_assets:
        return
    required: list[Path] = []
    if install.license_file:
        required.append(license_destination(ctx))
    if ctx.target.backend == "inno":
        if install.icons.windows:
            required.append(windows_asset_path(ctx, "app"))
        if document_assets:
            required += [windows_asset_path(ctx, item.id) for item in install.file_types if item.icons.windows]
    elif ctx.target.backend == "macos":
        bundle = ctx.layout.bundle
        assert bundle is not None
        if install.icons.macos:
            required.append(bundle / "Contents/Resources/wingsetup-app.icns")
        required += [bundle / f"Contents/Resources/wingsetup-{item.id}.icns" for item in install.file_types if item.icons.macos]
    elif ctx.target.backend in {"deb", "rpm", "arch", "appimage", "flatpak"}:
        if install.file_types:
            required.append(ctx.prefix_dir / f"share/mime/packages/{ctx.config.application.id}.xml")
        for item in install.file_types:
            required.append(ctx.prefix_dir / f"share/applications/{ctx.config.application.id}.{item.id}.desktop")
        for protocol in install.protocols:
            required.append(ctx.prefix_dir / f"share/applications/{ctx.config.application.id}.url-{protocol.scheme}.desktop")
    for path in required:
        if not path.is_file():
            raise SetupError(f"Final deployment lacks a required installation asset: {path}")


def write_installation_report(ctx: BuildContext, artifacts: tuple[Artifact, ...]) -> None:
    """Write per-output capability evidence without changing artifacts.json compatibility.

    Args:
        ctx: Completed target and output directory.
        artifacts: Successfully built package records.
    """
    report = [{"path": str(item.path), "format": item.format, "features": feature_results(ctx, item.format)} for item in artifacts]
    destination = ctx.config.output / ctx.target.name / "installation.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for item in artifacts:
        for feature in feature_results(ctx, item.format):
            get_console().write(f"    INSTALLATION {item.format} {feature['feature']}: {feature['status']} ({feature['reason']})", "detail")
