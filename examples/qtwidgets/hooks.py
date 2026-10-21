# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Deploy Qt Widgets translations, resources, and private plugin dependencies."""

import shutil
from pathlib import Path

from wingsetup import BuildContext, ProjectHooks, paths
from wingsetup.model import FlatpakOptions


class WidgetsHooks(ProjectHooks):
    """Complete native CMake staging while leaving SDK installation to its manifest."""

    def after_build(self, ctx: BuildContext) -> None:
        """Install the macOS bundle payload before backend deployment.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        if ctx.target.backend == "macos":
            ctx.run(["cmake", "--install", "{build}", "--prefix", "{build}/stage"])
            bundle = paths.CURRENT_BUILD_DIR / "widgets-demo.app"
            shutil.copytree(paths.CURRENT_BUILD_DIR / "stage/widgets-demo.app", bundle, dirs_exist_ok=True)
            # Include the offscreen platform explicitly for headless archive tests.
            plugins = Path(ctx.run(["qmake", "-query", "QT_INSTALL_PLUGINS"]).strip())
            destination = bundle / "Contents/PlugIns/platforms"
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plugins / "platforms/libqoffscreen.dylib", destination)

    def deploy(self, ctx: BuildContext) -> None:
        """Install native outputs or retain the manifest-owned SDK deployment.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        options = ctx.target.options
        if isinstance(options, FlatpakOptions) and options.mode == "sdk":
            return  # Installed by the SDK manifest's CMake module.
        if ctx.target.backend == "macos":
            return
        ctx.run(["cmake", "--install", "{build}", "--prefix", "{prefix}"])
