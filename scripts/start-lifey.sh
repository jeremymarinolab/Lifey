#!/bin/zsh
# Starts Lifey after you log in. This script is intentionally local-first.
set -euo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$HOME/Library/Logs/Lifey"
mkdir -p "$LOG_DIR"

# Tailscale is optional now. Lifey starts on the local network by default.
# Set LIFEY_START_TAILSCALE=1 in the launch agent only if you want the
# Tailscale fallback opened automatically.
if [[ "${LIFEY_START_TAILSCALE:-0}" == "1" && -d "/Applications/Tailscale.app" ]]; then
  /usr/bin/open -gja "Tailscale" || true
fi

# Traccar is optional fallback infrastructure. If Docker exists and a Traccar
# container is already configured, resume it in the background. Lifey itself
# does not wait for this job, and does not require it for the iPhone app.
(
  DOCKER="$(command -v docker || true)"
  [[ -n "$DOCKER" ]] || exit 0
  if "$DOCKER" container inspect traccar >/dev/null 2>&1 && [[ -d "/Applications/Docker.app" ]]; then
    /usr/bin/open -gja "Docker" || true
  else
    exit 0
  fi
  for _ in {1..30}; do
    if "$DOCKER" info >/dev/null 2>&1; then
      "$DOCKER" start traccar >/dev/null 2>&1 || true
      exit 0
    fi
    sleep 2
  done
) >> "$LOG_DIR/traccar-startup.log" 2>&1 &

cd "$ROOT"
NPM="$(command -v npm)"
exec "$NPM" run start:lan
