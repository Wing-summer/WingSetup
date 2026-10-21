# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Run a selected target and publish artifact paths to GitHub Actions."""

from __future__ import annotations

import os
import json
import platform
import uuid
from pathlib import Path

from wingsetup.config import load_config
from wingsetup.core import run_target
from wingsetup.model import SetupError


def main() -> None:
    """Package the requested target and emit checksum and artifact report paths."""
    config = load_config(Path(os.environ["GITHUB_WORKSPACE"]) / os.environ["PACKAGE_CONFIG"])
    target = next((item for item in config.targets if item.name == os.environ["PACKAGE_TARGET"]), None)
    if target is None:
        raise SetupError("Unknown CI target")
    artifacts = run_target(config, target)
    if not artifacts:
        raise SetupError("CI target produced no artifacts")
    paths = [str(path) for item in artifacts for path in (item.path, item.path.with_name(item.path.name + ".sha256"))]
    report = config.output / f"{target.name}-artifacts.json"
    report.write_text(json.dumps({"target": target.name, "backend": target.backend,
                                 "host": platform.system(), "arch": target.arch,
                                 "artifacts": [{"path": str(item.path), "sha256": item.sha256,
                                                "format": item.format, "kind": item.kind} for item in artifacts]},
                                indent=2) + "\n", encoding="utf-8")
    paths.append(str(report))
    delimiter = f"wingsetup_{uuid.uuid4().hex}"
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
        stream.write("artifact-paths<<" + delimiter + "\n" + "\n".join(paths) + "\n" + delimiter + "\n")


if __name__ == "__main__":
    main()
