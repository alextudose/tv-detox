#!/bin/sh
# Undo everything vidaa-detox changed, newest first. Nothing is ever uninstalled,
# so this puts settings, DNS blocks, the home tile and the relay back.
#   sh vidaa/restore.sh --dry-run    show what would be undone
#   sh vidaa/restore.sh              undo it (asks you to confirm the menu steps)
#   sh vidaa/restore.sh --only dns   one part only: relay, home, dns, settings
set -eu
cd "$(dirname "$0")"
exec uv run --project . python -m detox restore "$@"
