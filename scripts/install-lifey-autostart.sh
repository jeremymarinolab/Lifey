#!/bin/zsh
# One-time installer for Lifey's macOS login agent.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.lifey.dashboard"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/Lifey"
cp "$ROOT/$LABEL.plist" "$TARGET"
/bin/launchctl bootout "$DOMAIN" "$TARGET" >/dev/null 2>&1 || true
/bin/launchctl bootstrap "$DOMAIN" "$TARGET"
/bin/launchctl kickstart -k "$DOMAIN/$LABEL"

echo "Lifey will now start automatically whenever you log in."
echo "Open http://127.0.0.1:4173 once the server is ready."
