#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"

cd "$SCRIPT_DIR"
exec python -m uvicorn main:app \
    --host "$API_HOST" \
    --port "$API_PORT" \
    --reload