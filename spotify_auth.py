# spotify_auth.py — Spotify Web API OAuth2 + playback control
# Uses only stdlib (urllib) — no extra pip install required.
#
# One-time setup:
#   1. developer.spotify.com/dashboard → Create App
#   2. Add redirect URI:  http://127.0.0.1:5000/spotify-callback
#   3. Copy Client ID and Client Secret into the web setup page at
#      http://localhost:5000/spotify-setup
#   4. Click "Connect" and approve in the browser that opens.
#   Tokens are stored in spotify_auth.json beside this file.  All future
#   plays are silent Web API calls — the Spotify window never appears.

import json
import os
import time
import base64
import secrets
import urllib.parse
import urllib.request
import urllib.error

_CONFIG_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'spotify_auth.json')
_SCOPES       = 'user-modify-playback-state user-read-playback-state'
_REDIRECT_URI = 'http://127.0.0.1:5000/spotify-callback'

_cfg: dict = {}   # client_id, client_secret, access_token, refresh_token, expires_at


# ── Persistence ───────────────────────────────────────────────────────────────

def load():
    global _cfg
    if os.path.isfile(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE) as f:
                _cfg = json.load(f)
        except Exception:
            _cfg = {}

def _save():
    try:
        with open(_CONFIG_FILE, 'w') as f:
            json.dump(_cfg, f, indent=2)
    except Exception as e:
        print(f'[Spotify] could not save config: {e}')


# ── Status helpers ────────────────────────────────────────────────────────────

def is_configured() -> bool:
    return bool(_cfg.get('client_id') and _cfg.get('client_secret'))

def is_authed() -> bool:
    return bool(_cfg.get('refresh_token'))

def status() -> dict:
    return {
        'configured': is_configured(),
        'authed':     is_authed(),
        'client_id':  _cfg.get('client_id', ''),
    }


# ── OAuth flow ────────────────────────────────────────────────────────────────

def get_auth_url(client_id: str, client_secret: str) -> str:
    """Save credentials and return the Spotify authorization URL."""
    _cfg['client_id']     = client_id.strip()
    _cfg['client_secret'] = client_secret.strip()
    _save()
    params = urllib.parse.urlencode({
        'client_id':     _cfg['client_id'],
        'response_type': 'code',
        'redirect_uri':  _REDIRECT_URI,
        'scope':         _SCOPES,
        'state':         secrets.token_urlsafe(12),
    })
    return f'https://accounts.spotify.com/authorize?{params}'

def handle_callback(code: str) -> tuple[bool, str]:
    """Exchange the auth code for tokens.  Returns (success, message)."""
    creds_b64 = base64.b64encode(
        f"{_cfg.get('client_id','')}:{_cfg.get('client_secret','')}".encode()
    ).decode()
    data = urllib.parse.urlencode({
        'grant_type':   'authorization_code',
        'code':         code,
        'redirect_uri': _REDIRECT_URI,
    }).encode()
    req = urllib.request.Request(
        'https://accounts.spotify.com/api/token',
        data=data,
        headers={
            'Authorization': f'Basic {creds_b64}',
            'Content-Type':  'application/x-www-form-urlencoded',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read())
        _cfg['access_token']  = d['access_token']
        _cfg['refresh_token'] = d.get('refresh_token', _cfg.get('refresh_token', ''))
        _cfg['expires_at']    = time.time() + d['expires_in'] - 30
        _save()
        return True, 'OK'
    except urllib.error.HTTPError as e:
        return False, f'HTTP {e.code}: {e.read().decode()}'
    except Exception as e:
        return False, str(e)


# ── Token management ──────────────────────────────────────────────────────────

def _refresh() -> bool:
    creds_b64 = base64.b64encode(
        f"{_cfg.get('client_id','')}:{_cfg.get('client_secret','')}".encode()
    ).decode()
    data = urllib.parse.urlencode({
        'grant_type':    'refresh_token',
        'refresh_token': _cfg.get('refresh_token', ''),
    }).encode()
    req = urllib.request.Request(
        'https://accounts.spotify.com/api/token',
        data=data,
        headers={
            'Authorization': f'Basic {creds_b64}',
            'Content-Type':  'application/x-www-form-urlencoded',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read())
        _cfg['access_token'] = d['access_token']
        _cfg['expires_at']   = time.time() + d['expires_in'] - 30
        if 'refresh_token' in d:
            _cfg['refresh_token'] = d['refresh_token']
        _save()
        return True
    except Exception:
        return False

def _get_token() -> str | None:
    if time.time() >= _cfg.get('expires_at', 0):
        if not _refresh():
            return None
    return _cfg.get('access_token')


# ── API helper ────────────────────────────────────────────────────────────────

def _api(method: str, path: str, body=None) -> tuple[int | None, str | None]:
    token = _get_token()
    if not token:
        return None, 'No valid token — re-authenticate at /spotify-setup'
    headers = {'Authorization': f'Bearer {token}'}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(
        f'https://api.spotify.com/v1{path}',
        data=data, headers=headers, method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return None, str(e)


# ── Playback control ──────────────────────────────────────────────────────────

def _get_device_id() -> str | None:
    """Return the ID of any available Spotify device, preferring the active one."""
    token = _get_token()
    if not token:
        return None
    req = urllib.request.Request(
        'https://api.spotify.com/v1/me/player/devices',
        headers={'Authorization': f'Bearer {token}'},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            devices = json.loads(resp.read()).get('devices', [])
        for d in devices:
            if d.get('is_active'):
                return d['id']
        return devices[0]['id'] if devices else None
    except Exception:
        return None


def play(uri: str) -> tuple[bool, str]:
    """Start playback of a Spotify URI.  Caller should run this in a thread.

    Returns (success, message).
    """
    if not is_authed():
        return False, 'Not authenticated — visit http://localhost:5000/spotify-setup'

    body = {'uris': [uri]} if ':track:' in uri else {'context_uri': uri}
    code, err = _api('PUT', '/me/player/play', body)

    if code == 404:
        # No currently active device — find any available one and address it directly.
        # Spotify may have just been launched by ensure_running(); give it up to
        # 15 s to appear in the devices list before giving up.
        device_id = None
        for _wait in (0, 3, 5, 7):
            if _wait:
                time.sleep(_wait)
            device_id = _get_device_id()
            if device_id:
                break
        if not device_id:
            return False, ('No Spotify device found. Open Spotify on any device '
                           '(desktop, phone, web player) and try again.')
        token = _get_token()
        if not token:
            return False, 'No valid token'
        data = json.dumps(body).encode()
        req2 = urllib.request.Request(
            f'https://api.spotify.com/v1/me/player/play?device_id={device_id}',
            data=data,
            headers={'Authorization': f'Bearer {token}',
                     'Content-Type': 'application/json'},
            method='PUT',
        )
        try:
            with urllib.request.urlopen(req2, timeout=10) as resp:
                code, err = resp.status, None
        except urllib.error.HTTPError as e:
            code, err = e.code, e.read().decode()
        except Exception as e:
            return False, str(e)

    if code is None:
        return False, f'Request failed: {err}'
    if code == 403:
        return False, 'Spotify Premium required for playback control via Web API'
    if code not in (200, 204):
        return False, f'API error {code}: {err}'

    # Set repeat mode so the track/context loops
    repeat = 'track' if ':track:' in uri else 'context'
    _api('PUT', f'/me/player/repeat?state={repeat}')
    return True, 'OK'

def stop():
    """Pause playback on the active device.  Silently ignores errors."""
    if not is_authed():
        return
    _api('PUT', '/me/player/pause')


def ensure_running():
    """If authenticated and Spotify is not already running, launch it minimized.

    Intended to be called once at app startup from a background thread so the
    Web API always has a device to target without the user having to open Spotify
    manually.
    """
    if not is_authed():
        return
    import subprocess
    # Check whether a Spotify process is already alive.
    try:
        r = subprocess.run(['pgrep', '-xi', 'spotify'],
                           capture_output=True, timeout=2)
        if r.returncode == 0:
            return  # already running
    except Exception:
        return  # pgrep unavailable; skip check
    # Not running — try common install layouts (deb/snap, then Flatpak).
    candidates = [
        ['spotify', '--minimized'],
        ['flatpak', 'run', 'com.spotify.Client', '--minimized'],
    ]
    launched = False
    for cmd in candidates:
        try:
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            print(f'[Spotify] Launched in background: {cmd[0]}')
            launched = True
            break
        except FileNotFoundError:
            continue
        except Exception as e:
            print(f'[Spotify] Could not launch ({cmd[0]}): {e}')
            return
    if not launched:
        print('[Spotify] Spotify not found — install it for silent playback')
        return

    # Poll for the Spotify window and minimize it (--minimized is unreliable
    # on some distros/versions; xdotool is the fallback).
    deadline = time.time() + 20
    time.sleep(2)  # give Spotify a head start before polling
    while time.time() < deadline:
        try:
            r = subprocess.run(
                ['xdotool', 'search', '--class', 'Spotify'],
                capture_output=True, timeout=3, text=True,
            )
            if r.returncode == 0 and r.stdout.strip():
                for wid in r.stdout.strip().split():
                    subprocess.run(
                        ['xdotool', 'windowminimize', wid],
                        capture_output=True, timeout=2,
                    )
                print('[Spotify] Minimized Spotify window')
                return
        except FileNotFoundError:
            return  # xdotool not installed; --minimized flag must suffice
        except Exception:
            return
        time.sleep(1)


# Load saved config on import
load()
