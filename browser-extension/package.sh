#!/bin/zsh
# Packages the tracker for Mozilla AMO signing. The resulting XPI is unsigned
# until uploaded to AMO as an unlisted/self-distributed add-on.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT="$ROOT/outputs/lifey-youtube-tracker-0.1.3.xpi"
mkdir -p "$ROOT/outputs"
rm -f "$OUTPUT"
cd "$ROOT/browser-extension"
/usr/bin/zip -q "$OUTPUT" manifest.json background.js content.js
echo "Created $OUTPUT"
