#!/bin/sh
# Snapshot the TV (app list, inputs, device info) into a new run before changing anything.
set -eu
cd "$(dirname "$0")"
exec uv run --project . python -m detox backup "$@"
