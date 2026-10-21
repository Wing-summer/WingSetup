#!/bin/sh
# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.
set -eu
# An explicit opt-in invocation installs this demonstration without replacing data.
prefix=${WINGSETUP_PREFIX:-"$HOME/.local/opt/WingSetupHello"}
if [ -e "$prefix" ]; then
    echo "Refusing to overwrite existing path: $prefix" >&2
    exit 1
fi
mkdir -p "$prefix"
cp ./hello "$prefix/hello"
printf 'Installed: %s/hello\n' "$prefix"
