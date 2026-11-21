#!/usr/bin/env bash
# Start backend (API + workers) and the Vite dev server; Ctrl+C stops both.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$root/backend" && uv run clipforge dev) &
backend=$!
trap 'kill $backend 2>/dev/null || true' EXIT
cd "$root/frontend" && npm run dev
