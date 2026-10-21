# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Demonstrate host lifecycle callbacks and read-only deployment paths."""

from wingsetup import BuildContext, ProjectHooks, paths, get_console


class HelloHooks(ProjectHooks):
    """Prepare the minimal C example and report its build completion."""

    def pre_build(self, ctx: BuildContext) -> None:
        """Create the example source-relative build directory before compilation.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        (paths.CURRENT_SOURCE_DIR / "build").mkdir(exist_ok=True)

    def after_build(self, ctx: BuildContext) -> None:
        """Report the target whose build stage completed successfully.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
        """
        get_console().write(f"Build completed for {ctx.target.name}", "success")
