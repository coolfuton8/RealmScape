"""
Shared lock-state and PIN management.

Both main.py (pygame) and server.py (Flask) import this module.
Because Python modules are singletons within a process, the 'locked'
variable is genuinely shared — no IPC or queue needed for lock state.

PIN is stored as a SHA-256 hash in campaigns/.app_lock (not an obvious
location, no plaintext).  The session lock flag is in-memory only and
resets on app restart.
"""
import os, json, hashlib

_BASE     = os.path.dirname(os.path.abspath(__file__))
_PIN_FILE = os.path.join(_BASE, 'campaigns', '.app_lock')

locked = False   # session state — shared between pygame and Flask threads


# ── Internal ──────────────────────────────────────────────────────────────────

def _hash(pin: str) -> str:
    return hashlib.sha256(f'realmscape-lock-{pin}'.encode()).hexdigest()


# ── PIN storage ───────────────────────────────────────────────────────────────

def has_pin() -> bool:
    try:
        with open(_PIN_FILE) as f:
            return bool(json.load(f).get('h'))
    except Exception:
        return False


def set_pin(pin: str) -> None:
    os.makedirs(os.path.dirname(_PIN_FILE), exist_ok=True)
    with open(_PIN_FILE, 'w') as f:
        json.dump({'h': _hash(pin)}, f)


def verify_pin(pin: str) -> bool:
    if not has_pin():
        return False
    try:
        with open(_PIN_FILE) as f:
            return json.load(f).get('h') == _hash(pin)
    except Exception:
        return False


def clear_pin() -> None:
    try:
        os.remove(_PIN_FILE)
    except FileNotFoundError:
        pass


# ── Session lock ──────────────────────────────────────────────────────────────

def lock() -> None:
    global locked
    locked = True


def unlock() -> None:
    global locked
    locked = False
