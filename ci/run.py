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
from wingsetup.platforms import normalize_arch


def main() -> None:
    """Package the requested target and emit checksum and artifact report paths."""
    source = Path(os.environ.get("PACKAGE_SOURCE") or os.environ["GITHUB_WORKSPACE"])
    config = load_config(source / os.environ["PACKAGE_CONFIG"])
    requested = os.environ.get("PACKAGE_TARGET", "all")
    if requested == "all":
        targets = tuple(item for item in config.targets if item.platform in ("any", platform.system())
                        and item.arch in ("any", "universal2", normalize_arch(platform.machine())))
    else:
        targets = tuple(item for item in config.targets if item.name in requested.split(","))
        if {item.name for item in targets} != set(requested.split(",")):
            raise SetupError("Unknown CI target")
    if not targets:
        raise SetupError("No matching targets on this runner; use the reusable workflow for multiple platforms")
    paths: list[str] = []
    records: list[dict[str, str]] = []
    reports: list[str] = []
    for selected in targets:
        target_paths, target_records, installation_report = package_target(config.path, selected.name)
        paths.extend(target_paths)
        records.extend(target_records)
        reports.append(installation_report)
    delimiter = f"wingsetup_{uuid.uuid4().hex}"
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
        for key, value in (("artifact-paths", "\n".join(paths)), ("installation-report", "\n".join(reports)),
                           ("assets", json.dumps(records)), ("files", "\n".join(item["name"] for item in records)),
                           ("checksums", "\n".join(item["sha256"] + "  " + item["name"] for item in records))):
            stream.write(key + "<<" + delimiter + "\n" + value + "\n" + delimiter + "\n")


def package_target(path: Path, name: str) -> tuple[list[str], list[dict[str, str]], str]:
    """Package one target and preserve compatible artifact and installation reports.

    Args:
        path: Resolved application configuration file.
        name: Exact target to execute on the current runner.

    Returns:
        Upload paths, release file metadata, and the installation report pathname.
    """
    config = load_config(path)
    target = next((item for item in config.targets if item.name == name), None)
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
    installation_report = config.output / target.name / "installation.json"
    paths.append(str(installation_report))
    return paths, [{"name": item.path.name, "path": str(item.path), "sha256": item.sha256,
                    "format": item.format, "arch": item.arch} for item in artifacts if item.kind != "directory"], str(installation_report)


if __name__ == "__main__":
    main()
