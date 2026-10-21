# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""A project-owned Python management entry point exported without execution."""
import argparse


def main() -> None:
    """Print the exported recipe status without installing an application."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.status:
        print("Recipe exported; no application was installed by WingSetup.")


if __name__ == "__main__":
    main()
