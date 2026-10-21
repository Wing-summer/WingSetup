# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Expose the AppImage and Flatpak backend implementations."""
from .appimage import AppImageBackend
from .flatpak import FlatpakBackend

#: Public symbols intentionally exported by this package.
__all__ = ["AppImageBackend", "FlatpakBackend"]
