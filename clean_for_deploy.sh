#!/usr/bin/env bash
# clean_for_deploy.sh — Remove personal data and dev artifacts before sharing RealmScape
# Keeps: all source code, static assets, default campaign (example), manual, scripts
# Removes: secrets, personal campaigns, audio cache, bytecode, backup files
cd "$(dirname "$0")"

echo "============================================================"
echo " RealmScape — Deployment Cleaner"
echo "============================================================"
echo
echo "The following will be PERMANENTLY deleted from this folder:"
echo
echo "  [Secrets]"
echo "    campaigns/.web_secret"
echo "    campaigns/.app_lock"
echo "    spotify_auth.json"
echo
echo "  [Personal / runtime state]"
echo "    campaigns/active.json"
echo "    characters.db"
echo "    All campaign folders except \"default\""
echo
echo "  [Cache and generated files]"
echo "    cache/audio/  (downloaded MP3s)"
echo "    __pycache__/  (Python bytecode)"
echo
echo "  [Dev artifacts]"
echo "    *.bak"
echo "    *.org"
echo
echo "  The \"default\" campaign folder will NOT be touched."
echo
read -rp "Type YES to proceed: " CONFIRM
if [ "$CONFIRM" != "YES" ]; then
    echo "Cancelled."
    exit 0
fi
echo

remove_file() {
    if [ -f "$1" ]; then
        rm -f "$1" && echo "Removed: $1"
    else
        echo "Already gone: $1"
    fi
}

remove_dir() {
    if [ -d "$1" ]; then
        rm -rf "$1" && echo "Removed: $1/"
    else
        echo "Already gone: $1/"
    fi
}

# ── Secrets ──────────────────────────────────────────────────
remove_file "campaigns/.web_secret"
remove_file "campaigns/.app_lock"
remove_file "spotify_auth.json"

# ── Runtime state ────────────────────────────────────────────
remove_file "campaigns/active.json"
remove_file "characters.db"

# ── Non-default campaign folders ─────────────────────────────
for dir in campaigns/*/; do
    name=$(basename "$dir")
    if [ "$name" != "default" ]; then
        rm -rf "$dir"
        echo "Removed campaign: $name"
    fi
done

# ── Audio cache ───────────────────────────────────────────────
remove_dir "cache/audio"

# ── Python bytecode ──────────────────────────────────────────
find . -type d -name "__pycache__" | while read -r d; do
    rm -rf "$d" && echo "Removed: $d"
done

# ── Dev artifacts ────────────────────────────────────────────
find . -maxdepth 1 \( -name "*.bak" -o -name "*.org" \) | while read -r f; do
    rm -f "$f" && echo "Removed: $f"
done

echo
echo "============================================================"
echo " Done. Repo is clean for deployment."
echo "============================================================"
