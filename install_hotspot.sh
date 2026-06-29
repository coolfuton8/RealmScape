#!/usr/bin/env bash
# install_hotspot.sh — RealmScape Hotspot Daemon installer (Linux)
# Checks Python, installs hostapd/dnsmasq/iw if missing, and verifies
# that a WiFi adapter capable of AP mode is present.
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo " RealmScape Hotspot Daemon — Linux Installer"
echo "============================================================"
echo

# ── Check that the main app is installed ─────────────────────────
if [ ! -f ".venv/bin/python" ]; then
    echo "ERROR: Main RealmScape app is not installed."
    echo "       Run ./install.sh first, then re-run this script."
    exit 1
fi
echo "[OK] Main app virtual environment found."

# ── Verify Python works ───────────────────────────────────────────
PY_VER=$(.venv/bin/python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
echo "[OK] Python $PY_VER in virtual environment."

# ── Check hotspot_daemon.py is present ───────────────────────────
if [ ! -f "hotspot_daemon.py" ]; then
    echo "ERROR: hotspot_daemon.py not found in this directory."
    exit 1
fi
echo "[OK] hotspot_daemon.py found."

# ── Detect package manager ───────────────────────────────────────
PKG_MGR=""
if   command -v apt    &>/dev/null; then PKG_MGR="apt"
elif command -v dnf    &>/dev/null; then PKG_MGR="dnf"
elif command -v pacman &>/dev/null; then PKG_MGR="pacman"
fi

# ── Check and install required system tools ───────────────────────
echo
echo "Checking system packages for hotspot support..."

MISSING=()
command -v hostapd &>/dev/null || MISSING+=("hostapd")
command -v dnsmasq &>/dev/null || MISSING+=("dnsmasq")
command -v iw      &>/dev/null || MISSING+=("iw")
command -v ip      &>/dev/null || MISSING+=("iproute2")

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "  Missing: ${MISSING[*]}"
    if [ -z "$PKG_MGR" ]; then
        echo
        echo "WARNING: Cannot detect package manager."
        echo "         Please install the following manually: ${MISSING[*]}"
    else
        echo "  Installing via $PKG_MGR (requires sudo)..."
        if [ "$PKG_MGR" = "apt" ]; then
            sudo apt update -qq && sudo apt install -y "${MISSING[@]}"
        elif [ "$PKG_MGR" = "dnf" ]; then
            sudo dnf install -y "${MISSING[@]}"
        elif [ "$PKG_MGR" = "pacman" ]; then
            sudo pacman -S --noconfirm "${MISSING[@]}"
        fi
        echo "  [OK] Packages installed."
    fi
else
    echo "[OK] hostapd, dnsmasq, iw, ip — all present."
fi

# ── Check for a wireless interface ───────────────────────────────
echo
echo "Checking for a WiFi adapter..."
if command -v iw &>/dev/null; then
    IFACE=$(iw dev 2>/dev/null | awk '/Interface/{print $2}' | head -1)
    if [ -n "$IFACE" ]; then
        echo "[OK] Wireless interface found: $IFACE"
    else
        echo "[WARN] No wireless interface detected."
        echo "       Plug in a WiFi adapter that supports AP mode and re-run."
    fi
else
    echo "[WARN] iw not available yet — skipping interface check."
fi

# ── Note about systemd-resolved port conflict ─────────────────────
if systemctl is-active --quiet systemd-resolved 2>/dev/null; then
    echo
    echo "[NOTE] systemd-resolved is running and occupies port 53."
    echo "       If dnsmasq fails to start, run:"
    echo "         sudo systemctl stop systemd-resolved"
    echo "       or configure /etc/systemd/resolved.conf to use a stub listener."
fi

echo
echo "============================================================"
echo " Setup check complete!"
echo
echo " To start the hotspot daemon, run:"
echo "   ./run_hotspot.sh"
echo
echo " Root privileges are obtained automatically via sudo."
echo " A new random WiFi password is generated each time it starts."
echo
echo " Optional arguments:"
echo "   --ssid NAME    Change the network name  (default: RealmScape-DM)"
echo "   --port PORT    Change the app port      (default: 5000)"
echo "   --channel N    Change the WiFi channel  (default: 6)"
echo "============================================================"
