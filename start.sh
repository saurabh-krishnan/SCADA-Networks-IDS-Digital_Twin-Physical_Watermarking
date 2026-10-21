#!/usr/bin/env bash
# One-command startup (Git Bash / Linux / macOS). Serves API + UI from one Uvicorn process.
set -e
root="$(cd "$(dirname "$0")" && pwd)"

py="$root/backend/.venv/Scripts/python.exe"
[ -x "$py" ] || py="$root/backend/.venv/bin/python"
if [ ! -x "$py" ]; then
  echo "Creating Python virtual environment..."
  python -m venv "$root/backend/.venv"
  py="$root/backend/.venv/Scripts/python.exe"; [ -x "$py" ] || py="$root/backend/.venv/bin/python"
  "$py" -m pip install --upgrade pip
  "$py" -m pip install -r "$root/backend/requirements.txt"
fi

if [ ! -f "$root/frontend/dist/index.html" ]; then
  echo "Building frontend..."
  ( cd "$root/frontend" && { [ -d node_modules ] || npm install; } && npm run build )
fi

echo ""
echo "Starting SCADA platform on http://127.0.0.1:8000  (Ctrl+C to stop)"
echo ""
cd "$root/backend"
exec "$py" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
