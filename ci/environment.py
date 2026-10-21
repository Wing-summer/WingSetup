# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Install CI Python dependencies into a repository-local virtual environment."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Create a local environment and export its interpreter to subsequent steps.

    Environment variables:
        WINGSETUP_ROOT: Framework checkout; defaults to this script's parent root.
        WINGSETUP_DEVELOPMENT: Set to true to include strict checking and tests.
        GITHUB_ENV: Optional GitHub environment export destination.
        GITHUB_PATH: Optional GitHub executable search-path export destination.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", action="store_true")
    arguments = parser.parse_args()
    root = Path(os.environ.get("WINGSETUP_ROOT", Path(__file__).resolve().parents[1])).resolve()
    directory = root / ".venv-ci"
    subprocess.run([sys.executable, "-m", "venv", str(directory)], check=True)
    bin_dir = directory / ("Scripts" if os.name == "nt" else "bin")
    python = bin_dir / ("python.exe" if os.name == "nt" else "python")
    development = arguments.development or os.environ.get("WINGSETUP_DEVELOPMENT") == "true"
    requirement = f"{root}[dev]" if development else str(root)
    subprocess.run([str(python), "-m", "pip", "install", "-e", requirement], check=True)
    for variable, value in (("GITHUB_ENV", f"WINGSETUP_PYTHON={python}"), ("GITHUB_PATH", str(bin_dir))):
        destination = os.environ.get(variable)
        if destination:
            with Path(destination).open("a", encoding="utf-8") as stream:
                stream.write(value + "\n")
    print(f"Workspace Python: {python}")


if __name__ == "__main__":
    main()
