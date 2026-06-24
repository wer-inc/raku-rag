#!/usr/bin/env bash
# Serve Kakuto LP locally. Open http://127.0.0.1:8080/
set -euo pipefail
cd "$(dirname "$0")"
PORT="${1:-8080}"
echo "Kakuto LP → http://127.0.0.1:${PORT}/"
python3 -m http.server "$PORT"
