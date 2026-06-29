#!/usr/bin/env bash
# run_hotspot.sh — Start the RealmScape Hotspot Daemon (Linux)
# Automatically re-executes with sudo if not already root.
cd "$(dirname "$0")"

# ── Elevate to root if needed ─────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo "Requesting root privileges for hotspot daemon..."
    exec sudo "$0" "$@"
fi

# ── Running as root ───────────────────────────────────────────────
echo
echo "============================================================"
echo " RealmScape Hotspot Daemon"
echo "============================================================"
echo

# ── Disconnect any active WiFi connection ─────────────────────────
WIFI_DEV=$(nmcli -t -f DEVICE,TYPE,STATE device 2>/dev/null \
    | awk -F: '$2=="wifi" && $3=="connected" {print $1; exit}')
if [ -n "$WIFI_DEV" ]; then
    echo "Disconnecting WiFi ($WIFI_DEV)..."
    nmcli device disconnect "$WIFI_DEV"
    echo "WiFi disconnected."
    echo
else
    echo "No active WiFi connection found, proceeding."
    echo
fi

if [ ! -f "hotspot_daemon.py" ]; then
    echo "ERROR: hotspot_daemon.py not found."
    echo "       Make sure you are running this from the RealmScape directory."
    exit 1
fi

if [ -f ".venv/bin/python" ]; then
    exec ".venv/bin/python" hotspot_daemon.py "$@"
else
    exec python3 hotspot_daemon.py "$@"
fi
