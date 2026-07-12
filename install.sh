#!/usr/bin/env bash
# install.sh — RealmScape installer
# Requires Python 3.10-3.12. Python 3.13+ is not compatible with skia-python
# (used by the optional DungeonGen integration).
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo " RealmScape — Linux Installer"
echo "============================================================"
echo

# ── Locate Python 3.10-3.12 ───────────────────────────────────
find_python() {
    for cmd in python3.12 python3.11 python3.10 python3 python; do
        if command -v "$cmd" &>/dev/null; then
            major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo 0)
            minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo 0)
            if [ "$major" -eq 3 ] && [ "$minor" -ge 10 ] && [ "$minor" -le 12 ]; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON=$(find_python || true)
if [ -z "$PYTHON" ]; then
    echo "ERROR: No compatible Python found (3.10, 3.11, or 3.12 required)."
    echo "       Python 3.13+ is not compatible with the DungeonGen integration"
    echo "       library (skia-python has no 3.13 wheels)."
    echo "       Install Python 3.12 from your package manager or https://www.python.org/"
    exit 1
fi

PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
echo "Using Python $PY_VER  ($PYTHON)"
echo

# ── System packages ───────────────────────────────────────────
echo "Checking system packages..."

MISSING_SYS=()

for pkg in libsdl2-2.0-0 libsdl2-mixer-2.0-0 libsdl2-image-2.0-0; do
    dpkg -s "$pkg" &>/dev/null 2>&1 || MISSING_SYS+=("$pkg")
done

command -v dbus-send &>/dev/null || MISSING_SYS+=("dbus-bin")

if [ ${#MISSING_SYS[@]} -gt 0 ]; then
    echo "  The following system packages are recommended:"
    for p in "${MISSING_SYS[@]}"; do echo "    $p"; done
    echo "  Install them with:"
    echo "    sudo apt install ${MISSING_SYS[*]}"
    echo "  (continuing anyway — pygame ships its own SDL2 in the pip wheel)"
    echo
fi

# ── Virtual environment ───────────────────────────────────────
if [ -f ".venv/bin/python" ]; then
    echo "Virtual environment already exists, skipping creation."
    echo
else
    echo "Creating virtual environment..."
    if ! "$PYTHON" -m venv .venv; then
        PYVER_MM=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        echo
        echo "ERROR: Failed to create the virtual environment."
        echo "       This usually means the 'venv' module isn't installed."
        echo "       On Linux Mint / Ubuntu, install it with:"
        echo "         sudo apt install python${PYVER_MM}-venv"
        exit 1
    fi
    echo "Done."
    echo
fi

# ── Install dependencies ──────────────────────────────────────
echo "Installing dependencies..."
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt

echo
echo "============================================================"
echo " Installation complete!"
echo
echo " To start RealmScape, run:"
echo "   ./run.sh"
echo "============================================================"
