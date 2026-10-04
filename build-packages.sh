#!/usr/bin/env bash
# Package existing out-<arch> trees using the shared one-click build pipeline.
# Legacy invocation still builds all formats: ./build-packages.sh x64
# Select formats and cache/staging paths with the same options as auto-build.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/auto-build.sh" --only package --formats all "$@"
