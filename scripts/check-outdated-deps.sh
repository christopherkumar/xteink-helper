#!/usr/bin/env bash
# Fail the commit if any direct dependency in uv.lock is behind the latest PyPI release.
# Bypass once with: SKIP=check-outdated-deps git commit ...
set -euo pipefail

outdated=$(uv tree --outdated --depth 1 --no-dev 2>/dev/null | grep "(latest:" || true)
if [[ -n "$outdated" ]]; then
    echo "Outdated direct dependencies:"
    echo "$outdated"
    echo "Bump the floor in pyproject.toml and run: uv lock --upgrade"
    exit 1
fi
