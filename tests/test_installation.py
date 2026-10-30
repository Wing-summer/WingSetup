# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Exercise installer preferences, staged metadata, and non-invasive native rendering."""

from __future__ import annotations

import json
import plistlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Mapping
from unittest.mock import patch

import yaml

from wingsetup import BuildContext, CommandRunner, SetupError
from wingsetup.config import load_config
from wingsetup.install_config import arguments, merge_installation
from wingsetup.installation import apply_installation, feature_results, installation_requirements, write_installation_report, validate_staged_installation
from wingsetup.install_model import Installation
from wingsetup.backends.inno import InnoOptions, setup_directives
from wingsetup.backends.inno_installation import effective_options, sections, windows_command
from wingsetup.model import Artifact


class InstallationTests(unittest.TestCase):
    """Check strict configuration and platform-specific integration without native tools."""

    def setUp(self) -> None:
        """Create isolated assets and application metadata for each test."""
        #: Owner of this test's automatically removed source tree.
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        #: Canonical root avoids platform-specific temporary-path aliases.
        self.root = Path(self.temporary.name).resolve()
        (self.root / "app.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        (self.root / "app.ico").write_bytes(b"icon fixture")
        (self.root / "app.icns").write_bytes(b"icns fixture")
        (self.root / "license.txt").write_text("Example license")
        (self.root / "app.desktop").write_text("# preserved comment\n[Desktop Entry]\nType=Application\nName=Demo\nName[zh_CN]=Demo CN\nExec=demo\nIcon=org.example.Demo\n")

    def context(self, backend: str = "deb", shared: Mapping[str, object] | None = None,
                override: dict[str, object] | None = None, options: dict[str, object] | None = None) -> BuildContext:
        """Construct an immutable context from real YAML parsing.

        Args:
            backend: Native backend used to select platform and layout.
            shared: Optional top-level installation preferences.
            override: Optional target installation overrides.
            options: Optional explicit native backend settings.

        Returns:
            Target-local context without executing hooks or external tools.
        """
        native: dict[str, object] = {"package_name": "demo", "maintainer": "Example"} if backend == "deb" else {}
        native.update(options or {})
        target: dict[str, object] = {"backend": backend, "arch": "x86_64", "options": native}
        if override is not None:
            target["installation"] = override
        data: dict[str, object] = {"schema_version": 1, "application": {"id": "org.example.Demo", "name": "Demo", "version": "1.0", "summary": "Demo", "license": "BSD-3-Clause", "executable": "demo", "desktop": "app.desktop", "icon": "app.svg"},
                                  "project": {"source": "."}, "targets": {"test": target}}
        if shared is not None:
            data["installation"] = shared
        path = self.root / "package.yml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        config = load_config(path)
        ctx = BuildContext(config, config.targets[0], self.root / "work", self.root / "build", self.root / "stage", CommandRunner())
        ctx.work.mkdir(exist_ok=True)
        ctx.deploy_dir.mkdir(exist_ok=True)
        return ctx

    def declarations(self) -> dict[str, object]:
        """Return independent file and URL handlers with explicit command arguments."""
        return {"file_types": [{"id": "demo", "description": "Demo document", "extensions": [".wing-demo"], "mime_type": "application/x-wing-demo", "arguments": ["--open", "{file}"], "icons": {"linux": "app.svg", "windows": "app.ico", "macos": "app.icns"}}],
                "protocols": [{"scheme": "wing-demo", "description": "Demo URL", "arguments": ["--url", "{url}"]}]}

    def test_legacy_configuration_keeps_installation_absent(self) -> None:
        """Do not change legacy installer settings when shared preferences are absent."""
        self.assertIsNone(self.context().installation)

    def test_deep_mapping_overrides_replace_lists_and_retain_unrelated_fields(self) -> None:
        """Merge icon/shortcut mappings but replace handler lists atomically."""
        shared = {**self.declarations(), "icons": {"linux": "app.svg", "windows": "missing.ico"}, "shortcuts": {"start_menu": False, "desktop": True}}
        ctx = self.context(shared=shared, override={"file_types": [], "icons": {"windows": "app.ico"}})
        install = ctx.installation
        assert install is not None
        self.assertEqual(install.file_types, ())
        self.assertFalse(install.start_menu)
        self.assertTrue(install.desktop)
        self.assertEqual(install.icons.linux, self.root / "app.svg")
        self.assertEqual(install.icons.windows, self.root / "app.ico")
        self.assertEqual(merge_installation({"x": [1]}, {"x": []}), {"x": []})

    def test_only_used_platform_assets_are_checked(self) -> None:
        """Missing Windows icons must not block Linux metadata preparation."""
        ctx = self.context(shared={"icons": {"windows": "absent.ico", "linux": "app.svg"}})
        self.assertEqual(installation_requirements(ctx), ())
        self.assertTrue(installation_requirements(self.context("inno", {"icons": {"windows": "absent.ico"}})))

    def test_invalid_fields_and_ambiguous_tokens_are_rejected(self) -> None:
        """Keep YAML strict even when a requested feature is unsupported on Linux."""
        for invalid in ({"typo": True}, {"shortcuts": {"typo": True}}, {"autostart": "true"}, {"scope": "root"}):
            with self.assertRaises(SetupError):
                self.context(shared=invalid)
        for invalid_args in (["prefix{file}"], ["{file}", "{file}"], ["{url}"]):
            with self.assertRaises(SetupError):
                arguments(invalid_args, "{file}")

    def test_linux_handlers_preserve_localization_and_generate_mime_xml(self) -> None:
        """Retain source desktop content and avoid writing a default association."""
        ctx = self.context(shared=self.declarations())
        destination = ctx.prefix_dir / "share/applications"
        destination.mkdir(parents=True)
        (destination / "org.example.Demo.desktop").write_text((self.root / "app.desktop").read_text())
        apply_installation(ctx)
        self.assertIn("Name[zh_CN]", (destination / "org.example.Demo.desktop").read_text())
        handler = (destination / "org.example.Demo.demo.desktop").read_text()
        self.assertIn('Exec=demo "--open" %f', handler)
        self.assertIn("NoDisplay=true", handler)
        self.assertIn("MimeType=application/x-wing-demo;", handler)
        self.assertTrue((ctx.prefix_dir / "share/mime/packages/org.example.Demo.xml").is_file())
        self.assertFalse(tuple(ctx.deploy_dir.rglob("mimeapps.list")))

    def test_macos_merge_preserves_unrelated_declarations_and_is_idempotent(self) -> None:
        """Rewrite only managed types and preserve unrelated bundle metadata."""
        ctx = self.context("macos", self.declarations())
        bundle = ctx.layout.bundle
        assert bundle is not None
        path = bundle / "Contents/Info.plist"
        path.parent.mkdir(parents=True)
        path.write_bytes(plistlib.dumps({"CFBundleDocumentTypes": [{"CFBundleTypeName": "Other", "LSItemContentTypes": ["public.text"]}]}))
        apply_installation(ctx)
        once = path.read_bytes()
        apply_installation(ctx)
        self.assertEqual(path.read_bytes(), once)
        info = plistlib.loads(once)
        self.assertEqual(len(info["CFBundleDocumentTypes"]), 2)
        self.assertEqual(info["CFBundleDocumentTypes"][1]["LSHandlerRank"], "Alternate")
        empty = replace(ctx.target, installation=Installation(file_types=(), protocols=()))
        apply_installation(replace(ctx, target=empty))
        self.assertEqual(len(plistlib.loads(path.read_bytes())["CFBundleDocumentTypes"]), 1)

    def test_inno_native_options_override_shared_scope_and_setup(self) -> None:
        """Retain explicit backend directory, privilege, and publisher choices."""
        ctx = self.context("inno", {"scope": "machine", "publisher": "Shared", "directory": "{autopf}\\Shared"}, options={"privileges": "lowest", "default_dir": "{localappdata}\\Native", "setup": {"AppPublisher": "Native"}})
        options = ctx.target.options
        assert isinstance(options, InnoOptions)
        effective = effective_options(ctx, options)
        text = setup_directives(ctx, effective)
        self.assertIn("PrivilegesRequired=lowest", text)
        self.assertIn("AppPublisher=Native", text)
        self.assertNotIn("AppPublisher=Shared", text)
        self.assertIn("DefaultDirName={localappdata}\\Native", text)

    def test_inno_tasks_are_unchecked_and_registrations_are_owned(self) -> None:
        """Register candidates without default changes and compose optional actions."""
        ctx = self.context("inno", {**self.declarations(), "add_to_path": True, "autostart": True, "shortcuts": {"desktop": True}, "launch_after_install": True,
                                    "context_menu": [{"id": "open", "label": "Open Demo", "targets": ["file", "directory", "background"]}]})
        options = ctx.target.options
        assert isinstance(options, InnoOptions)
        rendered = sections(ctx, effective_options(ctx, options))
        self.assertIn("OpenWithProgids", rendered)
        self.assertIn("RegisteredApplications", rendered)
        self.assertIn("URLAssociations", rendered)
        self.assertNotIn("UserChoice", rendered)
        self.assertIn("Flags: postinstall nowait skipifsilent unchecked", rendered)
        self.assertEqual(rendered.count("Flags: unchecked"), 4)
        self.assertIn("WingClearOwned", rendered)
        self.assertIn("RegWriteExpandStringValue", rendered)
        self.assertIn("RegWriteStringValue", rendered)

    def test_machine_scope_omits_current_user_startup(self) -> None:
        """Avoid writing the elevated user's personal login settings."""
        ctx = self.context("inno", {"scope": "machine", "autostart": True})
        options = ctx.target.options
        assert isinstance(options, InnoOptions)
        self.assertNotIn("Name: \"wingsetup_autostart", sections(ctx, effective_options(ctx, options)))
        self.assertEqual(feature_results(ctx, "inno")[0]["status"], "ignored")

    def test_custom_template_requires_explicit_opt_in_for_shared_sections(self) -> None:
        """Report ignored integrations rather than changing an unprepared custom ISS."""
        (self.root / "custom.iss").write_text("[Setup]\nAppName=Demo\n")
        ctx = self.context("inno", {"add_to_path": True}, options={"script": "custom.iss"})
        options = ctx.target.options
        assert isinstance(options, InnoOptions)
        self.assertEqual(sections(ctx, options), "")
        self.assertEqual(feature_results(ctx, "inno")[0]["status"], "ignored")

    def test_ignored_custom_template_assets_are_not_required(self) -> None:
        """Do not require unused shared inputs for an unprepared installer template."""
        (self.root / "custom.iss").write_text("[Setup]\nAppName=Custom\n")
        ctx = self.context("inno", {"license_file": "absent.txt", "icons": {"windows": "absent.ico"}},
                           options={"script": "custom.iss", "formats": ["inno"]})
        self.assertEqual(installation_requirements(ctx), ())
        apply_installation(ctx)
        validate_staged_installation(ctx)

    def test_report_distinguishes_portable_assets_from_installer_behavior(self) -> None:
        """Write per-format evidence and preserve the existing artifact result shape."""
        ctx = self.context("inno", {"icons": {"windows": "app.ico"}, "add_to_path": True})
        output = ctx.config.output / ctx.target.name
        output.mkdir(parents=True)
        artifacts = (Artifact(output / "demo.zip", "zip", "x86_64", "fixture"), Artifact(output / "demo.exe", "inno", "x86_64", "fixture"))
        with patch("wingsetup.installation.get_console"):
            write_installation_report(ctx, artifacts)
        report = json.loads((output / "installation.json").read_text())
        self.assertEqual(report[0]["features"][0]["status"], "ignored")
        self.assertEqual(report[1]["features"][0]["status"], "applied")

    def test_final_filter_cannot_leave_a_managed_icon_dangling(self) -> None:
        """Validate integration dependencies after user hooks and final exclusions."""
        ctx = self.context("inno", {"icons": {"windows": "app.ico"}})
        apply_installation(ctx)
        validate_staged_installation(ctx)
        (ctx.app_dir / "wingsetup-assets/app.ico").unlink()
        with self.assertRaisesRegex(SetupError, "required installation asset"):
            validate_staged_installation(ctx)

    def test_windows_arguments_quote_dynamic_inputs_and_do_not_use_a_shell(self) -> None:
        """Keep whitespace, quote, and metacharacter arguments as explicit tokens."""
        command = windows_command("{app}\\demo.exe", ("--open", "a & b", "{file}"), "{file}")
        self.assertEqual(command, '\"{app}\\demo.exe\" --open \"a & b\" \"%1\"')
        self.assertNotIn("cmd.exe", command)
