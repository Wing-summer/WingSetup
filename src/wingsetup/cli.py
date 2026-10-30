# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Provide target discovery, dependency checks, and packaging commands."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from time import monotonic

from .config import load_config
from .core import BuildContext, CommandRunner, backend_for, check_requirements, run_target
from .model import SetupError
from .console import ColorMode, Console, console_scope, get_console


class Arguments(argparse.Namespace):
    """Typed command-line values populated by argparse."""

    #: Requested operation: check, run, or list.
    command: str
    #: Path to the application YAML configuration.
    config: Path
    #: Explicitly selected target names in command-line order, if supplied.
    target: list[str] | None
    #: Select every configured target when no explicit target list is supplied.
    all: bool
    #: Emit machine-readable discovery data for the list command.
    json: bool
    #: Filter selected targets to those supporting the current host platform.
    compatible: bool
    #: Terminal color policy; JSON output remains unstyled.
    color: ColorMode


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and discover, check, or run the selected targets.

    Args:
        argv: Command-line argument list; None reads the process arguments.

    Returns:
        Zero on success, or one when validation or packaging fails.

    Raises:
        SystemExit: argparse handles help requests or rejects invalid command-line
            syntax.
    """
    parser = argparse.ArgumentParser(prog="wingsetup")
    parser.add_argument("command", choices=("check", "run", "list"))
    parser.add_argument("-c", "--config", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--target", action="append", default=None)
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--json", action="store_true", help="Machine-readable discovery output for list")
    parser.add_argument("--compatible", action="store_true", help="Select targets for this host platform")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto",
                        help="Color policy for progress messages (default: auto)")
    args = parser.parse_args(argv, namespace=Arguments())
    with console_scope(Console(args.color)):
        try:
            config = load_config(Path(str(args.config)))
            names = args.target or []
            if args.command == "run" and not names and not args.all:
                raise SetupError("run requires --target NAME or --all")
            known = {target.name: target for target in config.targets}
            for name in names:
                if name not in known:
                    raise SetupError(f"Unknown target: {name}")
            targets = tuple(known[name] for name in dict.fromkeys(names)) if names else config.targets
            if args.compatible:
                targets = tuple(target for target in targets if target.platform in ("any", "", platform.system()))
            if not targets:
                raise SetupError("No matching targets")
            if args.command == "list":
                from .registry import registration
                rows: list[dict[str, object]] = []
                for target in targets:
                    spec = registration(target.backend)
                    rows.append({"name": target.name, "backend": target.backend, "platform": target.platform,
                                 "arch": target.arch, "layout": target.layout,
                                 "installation_features": sorted(spec.installation_features) if spec else ["license_file"],
                                 "kind": spec.kind if spec else "custom", "output": str(config.output / target.name)})
                if args.json:
                    print(json.dumps(rows, indent=2))
                else:
                    listing = Console(args.color, sys.stdout)
                    for row in rows:
                        listing.write(f"{row['name']}: {row['backend']} {row['platform']}/{row['arch']} ({row['kind']})")
                return 0
            if args.json:
                raise SetupError("--json is only supported by list")
            console = get_console()
            started = monotonic()
            failures = 0
            console.write(f"{args.command.upper()} {len(targets)} target(s) | configuration: {config.path}")
            for index, target in enumerate(targets, start=1):
                console.progress(index - 1, len(targets), f"Target {index}/{len(targets)}: {target.name}")
                if args.command == "check":
                    # No workspace creation and no project Hook import.
                    work = config.workspace / f"check-{target.name}"
                    ctx = BuildContext(config, target, work, work / "build", work / "root", CommandRunner())
                    errors = check_requirements(backend_for(target, config.path.parent), ctx)
                    for error in errors:
                        console.write(f"    MISSING [{target.name}] {error}", "error")
                    if not errors:
                        console.write(f"    READY [{target.name}] requirements satisfied", "success")
                    failures += bool(errors)
                    console.progress(index, len(targets), f"Checked {target.name}", "warning" if errors else "success")
                else:
                    try:
                        run_target(config, target)
                    except (SetupError, OSError):
                        console.progress(index - 1, len(targets),
                                         f"RUN stopped at {target.name}; {len(targets) - index} target(s) not started", "error")
                        raise
                    console.progress(index, len(targets), f"Completed target {target.name}", "success")
            console.write(f"{args.command.upper()} complete: {len(targets)} target(s), {failures} failed ({console.elapsed(started)})",
                          "error" if failures else "success")
            return 1 if failures else 0
        except (SetupError, OSError) as exc:
            get_console().write(f"ERROR wingsetup: {exc}", "error")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
