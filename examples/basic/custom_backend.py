# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""A small custom backend; select custom_backend.py:ArchiveBackend in YAML."""
import tarfile

from wingsetup import Artifact, BuildContext, PackageBackend, ProjectHooks
from wingsetup.core import artifact, deploy_resources


class ArchiveBackend(PackageBackend):
    """Demonstrate a custom archive backend with project deployment extensions."""

    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Accept this example without requiring an external archive executable.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.

        Returns:
            An empty tuple because the test backend needs no external tools.
        """
        return ()

    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Stage the compiled entry and resources, then invoke project deployment.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.
            hooks: Project callbacks invoked during deployment.
        """
        ctx.deploy_dir.mkdir(parents=True, exist_ok=True)
        ctx.copy_app(ctx.executable, ctx.executable_name)
        deploy_resources(ctx)
        hooks.deploy(ctx)

    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Archive the staged example and return its checksum-bearing artifact.

        Args:
            ctx: Target-local configuration, deployment paths, and command runner.

        Returns:
            Artifact records for the generated or simulated output.
        """
        output = ctx.config.output / ctx.target.name / f"{ctx.config.application.name}-{ctx.target.name}.tar.gz"
        with tarfile.open(output, "w:gz") as archive:
            archive.add(ctx.deploy_dir, arcname=".")
        return (artifact(ctx, output, "tar.gz"),)
