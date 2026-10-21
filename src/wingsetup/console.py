# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Render colored, append-only progress without changing machine-readable output."""

from __future__ import annotations

import os
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from threading import Event
from typing import Generator, Literal, TextIO

#: Supported color policies exposed by the command-line interface.
ColorMode = Literal["auto", "always", "never"]
#: Severity names selecting a fixed, emoji-free text palette.
Level = Literal["info", "success", "warning", "error", "detail"]
#: ANSI control sequences removed from redirected child output and saved logs.
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)")
#: Foreground codes used only when terminal color is enabled.
_PALETTE: dict[Level, str] = {"info": "36", "success": "32", "warning": "33",
                              "error": "31", "detail": "90"}
#: Presentation scope isolated between nested CLI invocations and concurrent tasks.
_ACTIVE: ContextVar[Console | None] = ContextVar("wingsetup_console", default=None)


def plain_text(text: str) -> str:
    """Remove ANSI control sequences from text saved to nonterminal logs.

    Args:
        text: Tool output or diagnostic message that may contain terminal codes.

    Returns:
        Text with terminal escape sequences removed.
    """
    return _ANSI.sub("", text)


class Console:
    """Provide deterministic progress lines for terminals, pipes, and GitHub CI.

    Progress counts completed lifecycle stages rather than estimating build time.
    Output is append-only, so command output never competes with a redrawn bar.
    """

    def __init__(self, color: ColorMode = "auto", stream: TextIO | None = None) -> None:
        """Configure presentation without retaining a stale redirected stream.

        Args:
            color: Automatic detection, unconditional ANSI, or plain text.
            stream: Optional output destination; None resolves current stderr.
        """
        #: Requested color policy, independent of command execution and JSON data.
        self.color = color
        #: Explicit stream override, or None to follow redirected stderr dynamically.
        self.stream = stream

    @property
    def destination(self) -> TextIO:
        """Return the explicit stream or the current standard-error stream."""
        return self.stream if self.stream is not None else sys.stderr

    @property
    def colored(self) -> bool:
        """Return whether the current destination should receive ANSI colors."""
        if self.color != "auto":
            return self.color == "always"
        if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
            return False
        force = os.environ.get("FORCE_COLOR")
        if force is not None:
            return force != "0"
        return self.destination.isatty() or os.environ.get("GITHUB_ACTIONS") == "true"

    def write(self, text: str, level: Level = "info") -> None:
        """Write a flushed status line with an optional severity color.

        Args:
            text: Human-readable message; no emoji or carriage-return animation is added.
            level: Severity selecting the text palette.
        """
        clean = plain_text(text)
        rendered = f"\x1b[{_PALETTE[level]}m{clean}\x1b[0m" if self.colored else clean
        print(rendered, file=self.destination, flush=True)

    def progress(self, completed: int, total: int, label: str,
                 level: Level = "info") -> None:
        """Render completed work units as an ASCII bar and explicit numeric count.

        Args:
            completed: Number of successfully completed stages or targets.
            total: Total work units; no percentage is inferred for unknown totals.
            label: Target, stage, or operation associated with this update.
            level: Severity used for this progress line.

        Raises:
            ValueError: Completed units or the total do not describe valid progress.
        """
        if total <= 0 or not 0 <= completed <= total:
            raise ValueError("Progress requires 0 <= completed <= total and total > 0")
        filled = completed * 20 // total
        self.write(f"[{'=' * filled}{'.' * (20 - filled)}] {completed}/{total} {label}", level)

    def child(self, text: str) -> None:
        """Print a child-process line without contaminating its captured return value.

        Args:
            text: Original process line, with its trailing newline when present.
        """
        self.write("    | " + plain_text(text).rstrip("\r\n"), "detail")

    def heartbeat(self, stop: Event, label: str, started: float) -> None:
        """Report continued execution when an external command remains quiet.

        Args:
            stop: Event ending periodic messages when the command exits.
            label: Executable name identifying the operation still in progress.
            started: Monotonic timestamp used to report elapsed time.
        """
        while not stop.wait(15):
            self.write(f"    RUNNING {label} ({self.elapsed(started)} elapsed)", "detail")

    def elapsed(self, started: float) -> str:
        """Format elapsed monotonic time for a command, stage, or target.

        Args:
            started: Monotonic timestamp recorded at operation start.

        Returns:
            Duration in milliseconds or seconds without promising a completion estimate.
        """
        elapsed = max(0.0, monotonic() - started)
        return f"{elapsed * 1000:.0f}ms" if elapsed < 1 else f"{elapsed:.1f}s"


def get_console() -> Console:
    """Return the active presentation policy or an automatically detected console.

    Returns:
        Console selected for the current invocation.
    """
    return _ACTIVE.get() or Console()


@contextmanager
def console_scope(console: Console) -> Generator[None, None, None]:
    """Apply a presentation policy and restore it after success or failure.

    Args:
        console: Output policy used by pipeline and command execution messages.

    Yields:
        Control to the operation using the selected console.
    """
    token = _ACTIVE.set(console)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
