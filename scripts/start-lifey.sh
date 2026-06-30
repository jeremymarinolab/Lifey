#!/bin/zsh
# Starts Lifey after you log in. This script is intentionally local-first.
set -euo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$HOME/Library/Logs/Lifey"
mkdir -p "$LOG_DIR"

# Tailscale is responsible for its own sign-in and login item. Opening it here
# makes the private iPhone URL available again after a Mac restart.
if [[ -d "/Applications/Tailscale.app" ]]; then
  /usr/bin/open -gja "Tailscale" || true
fi

# Start Docker Desktop and then resume the existing Traccar container when it
# becomes available. Lifey itself does not wait for this background job.
(
  if [[ -d "/Applications/Docker.app" ]]; then
    /usr/bin/open -gja "Docker" || true
  fi
  for _ in {1..30}; do
    if /usr/local/bin/docker info >/dev/null 2>&1; then
      /usr/local/bin/docker start traccar >/dev/null 2>&1 || true
      exit 0
    fi
    sleep 2
  done
) >> "$LOG_DIR/traccar-startup.log" 2>&1 &

cd "$ROOT"
exec /usr/local/bin/npm start
