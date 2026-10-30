# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Provision optional Qt inside the disposable RISC-V guest and run one case."""

from __future__ import annotations

import os
import platform
import subprocess
import sys

from prepare import check_linux_linguist_tools, linux_qt_packages


def main() -> None:
    """Prepare guest Qt and delegate to the shared checksum and launch verifier.

    Raises:
        RuntimeError: Invoked outside the explicitly configured RISC-V CI guest.
    """
    if platform.machine() != "riscv64" or not os.environ.get("GITHUB_RUN_ID"):
        raise RuntimeError("This preparation entry requires the disposable riscv64 CI guest")
    if os.environ.get("EXAMPLE_QT") == "true":
        packages = linux_qt_packages(platform.freedesktop_os_release().get("VERSION_ID", ""))
        subprocess.run(["apt-get", "install", "-y", *packages], check=True)
        check_linux_linguist_tools()
    subprocess.run([sys.executable, "ci/examples.py", *sys.argv[1:]], check=True)


if __name__ == "__main__":
    main()
