#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Compatibility entry point for Python makefile generation.
set -e
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/setup-makefiles.py" "$@"
