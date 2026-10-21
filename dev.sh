#!/usr/bin/env bash
# Development mode: backend (:8000) + Vite dev server with HMR (:5173).
set -e
root="$(cd "$(dirname "$0")" && pwd)"
py="$root/backend/.venv/Scripts/python.exe"; [ -x "$py" ] || py="$root/backend/.venv/bin/python"
( cd "$root/backend" && "$py" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload ) &
BE=$!
trap "kill $BE 2>/dev/null" EXIT
( cd "$root/frontend" && npm run dev )
