"""
Per-campaign lock-state and PIN management.

Each campaign has its own PIN, stored as a SHA-256 hash inside that
campaign's own folder (campaigns/<name>/.pin) — it travels naturally with
export/import/rename since those already operate on the whole folder.
The 'default' campaign can never have a PIN.

Both main.py (pygame) and server.py (Flask) import this module. Because
Python modules are singletons within a process, 'locked' and the tracked
active-campaign name are genuinely shared — no IPC or queue needed.

main.py calls set_active_campaign(name) once at startup and again on every
switch_campaign(); this automatically re-locks whenever the newly active
campaign has a PIN, and leaves it unlocked when it doesn't (or is default).
"""
import os, json, hashlib

locked           = False        # session state — shared between pygame and Flask threads
_active_campaign = 'default'    # kept in sync by main.py; determines whose PIN applies


# ── Internal ──────────────────────────────────────────────────────────────────

def _hash(pin: str) -> str:
    return hashlib.sha256(f'realmscape-lock-{pin}'.encode()).hexdigest()


def _pin_file(name: str) -> str:
    import campaigns
    return os.path.join(campaigns.campaign_path(name), '.pin')


# ── PIN storage (per campaign) ────────────────────────────────────────────────

def has_pin(name: str = None) -> bool:
    name = name or _active_campaign
    if name == 'default':
        return False
    try:
        with open(_pin_file(name)) as f:
            return bool(json.load(f).get('h'))
    except Exception:
        return False


def set_pin(name: str, pin: str) -> bool:
    """Set (or replace) a campaign's PIN. Refuses 'default'. Returns success."""
    if name == 'default' or not name:
        return False
    path = _pin_file(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump({'h': _hash(pin)}, f)
    return True


def verify_pin(pin: str, name: str = None) -> bool:
    name = name or _active_campaign
    if not has_pin(name):
        return False
    try:
        with open(_pin_file(name)) as f:
            return json.load(f).get('h') == _hash(pin)
    except Exception:
        return False


def clear_pin(name: str) -> None:
    try:
        os.remove(_pin_file(name))
    except FileNotFoundError:
        pass


# ── Session lock ──────────────────────────────────────────────────────────────

def set_active_campaign(name: str) -> None:
    """Called whenever the active campaign changes (including at startup).
    Automatically (re-)locks if the new campaign has a PIN, and unlocks if
    it doesn't — a campaign with no PIN is never lockable."""
    global _active_campaign, locked
    _active_campaign = name
    locked = has_pin(name)


def lock() -> None:
    """Manually re-lock the active campaign. No-op if it has no PIN."""
    global locked
    if has_pin(_active_campaign):
        locked = True


def unlock() -> None:
    global locked
    locked = False
