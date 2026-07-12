#!/usr/bin/env bash
# run.sh — Start RealmScape
cd "$(dirname "$0")"

# Kill any leftover instance holding port 5000 (e.g. from a previous crash).
fuser -k 5000/tcp 2>/dev/null || true
sleep 0.3

if [ -f ".venv/bin/python" ]; then
    exec ".venv/bin/python" main.py
else
    echo "ERROR: Virtual environment not found (.venv/bin/python missing)."
    echo "       Run ./install.sh first to set up dependencies."
    exit 1
fi
