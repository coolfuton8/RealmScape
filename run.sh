#!/usr/bin/env bash
# run.sh — Start RealmScape
cd "$(dirname "$0")"

# Kill any leftover instance holding port 5000 (e.g. from a previous crash).
fuser -k 5000/tcp 2>/dev/null || true
sleep 0.3

if [ -f ".venv/bin/python" ]; then
    ".venv/bin/python" main.py
else
    python3 main.py
fi
