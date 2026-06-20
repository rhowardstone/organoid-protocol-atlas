#!/usr/bin/env bash
# Serve the Organoid Protocol Atlas (Datasette + custom templates, static, plugins).
# The ask-proxy plugin (/-/ask) calls a LOCAL ollama model — no API, no keys.
#
#   ./serve/run.sh [PORT]
#
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${1:-8002}"
DB="data/kg/atlas.db"

if [ ! -f "$DB" ]; then
  echo "building knowledge graph ($DB) ..."
  python pipeline/build_kg.py
fi

exec datasette serve "$DB" \
  --metadata serve/metadata.yaml \
  --template-dir serve/templates \
  --static static:serve/static \
  --plugins-dir serve/plugins \
  --port "$PORT"
