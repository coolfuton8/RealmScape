"""
DM remote panel server.

Runs as a daemon thread inside the pygame process.
The pygame main loop drains cmd_queue each frame, applies the commands,
then calls broadcast_state() so all connected DM browsers get the new state.

Install deps:  pip install flask flask-socketio
"""
import queue
import threading
import os
import io
import shutil
import tempfile
import secrets as _secrets
import pin_manager

cmd_queue: queue.Queue = queue.Queue()

# ── Tabletop Audio track list (cached after first load) ───────────────────────
_tta_cache = None   # list of {'title', 'url'} dicts, None until first load
_TTA_JS_URL = 'https://tabletopaudio.com/bootstrap/js/tta4XFADE3_min.js'
_TTA_CDN    = 'https://sounds.tabletopaudio.com/'

def _load_tta_tracks() -> list:
    global _tta_cache
    if _tta_cache is not None:
        return _tta_cache
    import urllib.request, re
    try:
        req = urllib.request.Request(
            _TTA_JS_URL,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; RealmScape/1.0)'})
        with urllib.request.urlopen(req, timeout=20) as r:
            js = r.read().decode('utf-8', errors='ignore')
        entries = re.findall(r'song_(\d+):\{title:"([^"]+)",artist:\w+,mp3:\w\+"([^"]+)"', js)
        _tta_cache = sorted(
            [{'title': title, 'url': _TTA_CDN + fname} for _, title, fname in entries],
            key=lambda x: x['title'].lower()
        )
    except Exception as e:
        print(f'[server] TTA load failed: {e}')
        _tta_cache = []
    return _tta_cache

def _get_web_secret() -> str:
    """Return a stable random secret for Flask sessions (generated once, stored to disk)."""
    _sf = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'campaigns', '.web_secret')
    try:
        if os.path.exists(_sf):
            s = open(_sf).read().strip()
            if len(s) >= 32:
                return s
    except Exception:
        pass
    s = _secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(_sf), exist_ok=True)
        open(_sf, 'w').write(s)
    except Exception:
        pass
    return s
_bg_path_holder: list = ['']   # mutable so main.py can update without re-importing

try:
    from flask import Flask, send_from_directory, send_file, make_response, abort
    from flask_socketio import SocketIO
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    Flask = SocketIO = None

# Pick the best async backend available: eventlet > gevent > threading.
# threading alone cannot handle WebSocket upgrades in Werkzeug's dev server.
def _best_async_mode() -> str:
    try:
        import gevent  # noqa: F401
        return 'gevent'
    except ImportError:
        pass
    return 'threading'

_ASYNC_MODE = _best_async_mode()

_dm_client_count = 0   # authenticated SocketIO connections currently open


def dm_connected() -> bool:
    """True when at least one authenticated GM browser is connected via SocketIO."""
    return _dm_client_count > 0


if _AVAILABLE:
    from flask import request, jsonify
    _app = Flask(__name__, static_folder='static')
    _app.config['SECRET_KEY'] = _get_web_secret()
    _sio = SocketIO(_app, cors_allowed_origins='*', async_mode=_ASYNC_MODE,
                    logger=False, engineio_logger=False)

    # ── Web access gate ────────────────────────────────────────────────────────
    # There is no separate login page — each campaign's PIN (if it has one) is
    # set once, via the "Save" flow, and gates BOTH the desktop touchscreen and
    # this web panel through the single shared pin_manager.locked flag. A
    # campaign with no PIN (including 'default') is never locked at all: the
    # main page and static assets always load; dm.html's own in-page lock
    # overlay (driven by `locked` in the state broadcast) blocks interaction,
    # and this guard blocks the API calls that would let a locked-out session
    # actually manipulate anything.
    _LOCK_EXEMPT_API = {'/api/pin-status', '/api/unlock'}

    @_app.before_request
    def _guard():
        if not pin_manager.locked:
            return None
        if request.path.startswith('/socket.io') or request.path.startswith('/manual/'):
            return None
        if request.path.startswith('/api/') and request.path not in _LOCK_EXEMPT_API:
            return make_response(jsonify({'error': 'Locked — enter the PIN to continue'}), 401)
        return None

    @_app.route('/')
    def _index():
        return send_from_directory('static', 'dm.html')

    @_app.route('/favicon.ico')
    def _favicon():
        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'icon.png')
        if os.path.exists(icon):
            return send_file(icon, mimetype='image/png')
        abort(404)

    @_app.route('/map-image')
    def _map_image():
        path = _bg_path_holder[0]
        if path and os.path.isfile(path):
            try:
                return send_file(path)
            except Exception:
                pass
        import base64
        data = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQ'
            'AABjkB6QAAAABJRU5ErkJggg=='
        )
        resp = make_response(bytes(data))
        resp.headers['Content-Type'] = 'image/png'
        return resp

    # ── Sound zone REST API ───────────────────────────────────────────────────

    @_app.route('/api/sound-zones', methods=['GET'])
    def _sz_list():
        try:
            import db as _db
            scene_id = int(request.args.get('scene_id', 0))
            rows = _db.get_sound_zones(scene_id)
            return jsonify([{'id':r[0],'name':r[1],'x':r[2],'y':r[3],'w':r[4],
                             'h':r[5],'track':r[6],'color':r[7],'scene_id':r[8]}
                            for r in rows])
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @_app.route('/api/sound-zones', methods=['POST'])
    def _sz_create():
        try:
            import db as _db
            d = request.get_json() or {}
            new_id = _db.add_sound_zone(
                d.get('name','Zone'), float(d.get('x',0)), float(d.get('y',0)),
                float(d.get('w',200)), float(d.get('h',200)),
                d.get('track',''), d.get('color','#4488ff'), int(d.get('scene_id',0))
            )
            cmd_queue.put({'type': 'reload_sound_zones'})
            return jsonify({'ok': True, 'id': new_id})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @_app.route('/api/sound-zones/<int:zid>', methods=['PATCH'])
    def _sz_update(zid):
        try:
            import db as _db
            d = request.get_json() or {}
            _db.update_sound_zone(zid, d.get('name','Zone'), d.get('track',''), d.get('color','#4488ff'))
            cmd_queue.put({'type': 'reload_sound_zones'})
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ── Spotify OAuth setup ───────────────────────────────────────────────────

    _SP_CSS = """
      body{font-family:sans-serif;background:#111;color:#e5e7eb;
           display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
      .box{background:#1c1c2e;border:1px solid #1db954;border-radius:10px;
           padding:32px;width:480px;max-width:95vw}
      h2{color:#1db954;margin-top:0}
      label{font-size:13px;color:#9ca3af;display:block;margin-top:14px}
      input{width:100%;box-sizing:border-box;margin-top:4px;padding:8px 10px;
            border-radius:5px;border:1px solid #374151;background:#2d2d44;
            color:#fff;font-size:13px}
      .btn{display:inline-block;margin-top:16px;padding:10px 24px;
           background:#1db954;color:#000;border:none;border-radius:6px;
           font-size:14px;font-weight:bold;cursor:pointer}
      .btn:hover{background:#17a349}
      .btn-sec{background:#374151;color:#fff;margin-left:8px}
      .btn-sec:hover{background:#4b5563}
      .note{font-size:12px;color:#6b7280;margin-top:8px;line-height:1.6}
      .uri{font-family:monospace;background:#0f172a;color:#93c5fd;padding:4px 8px;
           border-radius:4px;user-select:all;cursor:pointer;display:inline-block;margin:4px 0}
      .sep{border:none;border-top:1px solid #374151;margin:20px 0}
      #msg{color:#f87171;font-size:12px;min-height:16px;margin-top:8px}
    """

    @_app.route('/spotify-setup')
    def _spotify_setup():
        import spotify_auth as _sp
        s = _sp.status()
        badge = ('<span style="color:#4ade80">&#10003; Connected</span>'
                 if s['authed'] else
                 '<span style="color:#f87171">&#10007; Not connected</span>')
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Spotify Setup</title>
<style>{_SP_CSS}</style></head><body><div class="box">
  <h2>&#9835; Spotify Setup</h2>
  <div style="font-size:13px;margin-bottom:16px">Status: {badge}</div>

  <p class="note" style="color:#e5e7eb;margin-top:0">
    <b>Step 1</b> — <a href="https://developer.spotify.com/dashboard" target="_blank"
    style="color:#1db954">developer.spotify.com/dashboard</a>
    → Create app → Settings → Redirect URIs → add exactly:
  </p>
  <div class="uri" onclick="navigator.clipboard.writeText(this.textContent)"
       title="Click to copy">http://127.0.0.1:5000/spotify-callback</div>
  <p class="note">Click the URI above to copy it, paste into Spotify, click Add, then Save.</p>

  <hr class="sep">
  <p class="note" style="color:#e5e7eb"><b>Step 2</b> — Enter your app credentials:</p>
  <label>Client ID</label>
  <input id="cid" type="text" value="{s['client_id']}" placeholder="Client ID from Spotify dashboard">
  <label>Client Secret</label>
  <input id="csec" type="password" placeholder="Client Secret from Spotify dashboard">
  <div>
    <button class="btn" onclick="connect()">Connect to Spotify</button>
  </div>
  <p id="msg"></p>

  <hr class="sep">
  <p class="note" style="color:#e5e7eb">
    <b>Manual fallback</b> — if the browser shows an error after authorising,
    copy the full URL from the address bar and paste it here:
  </p>
  <input id="manual-url" type="text" placeholder="http://127.0.0.1:5000/spotify-callback?code=...">
  <button class="btn btn-sec" onclick="manualCode()" style="margin-top:10px">Complete Setup</button>

  <p class="note" style="margin-top:20px">
    Credentials are stored in <code>spotify_auth.json</code> and refresh automatically.
    This is a one-time setup.
  </p>
</div>
<script>
async function connect() {{
  const cid  = document.getElementById('cid').value.trim();
  const csec = document.getElementById('csec').value.trim();
  const msg  = document.getElementById('msg');
  if (!cid || !csec) {{ msg.textContent = 'Enter both Client ID and Client Secret.'; return; }}
  msg.textContent = '';
  const r = await fetch('/spotify-get-auth-url', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{client_id: cid, client_secret: csec}})
  }});
  const d = await r.json();
  if (d.auth_url) window.location.href = d.auth_url;
  else msg.textContent = d.error || 'Error getting auth URL.';
}}
async function manualCode() {{
  const raw = document.getElementById('manual-url').value.trim();
  const msg = document.getElementById('msg');
  if (!raw) {{ msg.textContent = 'Paste the redirect URL first.'; return; }}
  msg.textContent = '';
  const r = await fetch('/spotify-manual-code', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{url: raw}})
  }});
  const d = await r.json();
  if (d.ok) {{ msg.style.color='#4ade80'; msg.textContent = '✓ Connected! You can close this tab.'; }}
  else {{ msg.style.color='#f87171'; msg.textContent = d.error || 'Failed.'; }}
}}
</script>
</body></html>"""

    @_app.route('/spotify-get-auth-url', methods=['POST'])
    def _spotify_get_auth_url():
        import spotify_auth as _sp
        d   = request.get_json() or {}
        cid  = d.get('client_id', '').strip()
        csec = d.get('client_secret', '').strip()
        if not cid or not csec:
            return jsonify({'error': 'client_id and client_secret required'}), 400
        url = _sp.get_auth_url(cid, csec)
        return jsonify({'auth_url': url})

    def _finish_spotify_auth(code):
        import spotify_auth as _sp
        ok, msg = _sp.handle_callback(code)
        if ok:
            try:
                import sys as _sys_mod
                _main = _sys_mod.modules.get('__main__')
                if _main is not None:
                    _main._spotify_setup_shown = False
            except Exception:
                pass
        return ok, msg

    @_app.route('/spotify-callback')
    def _spotify_callback():
        code  = request.args.get('code')
        error = request.args.get('error')
        if error:
            return (f'<html><body style="font-family:sans-serif;background:#111;color:#f87171">'
                    f'<h2>Spotify denied: {error}</h2>'
                    f'<a href="/spotify-setup" style="color:#1db954">Back to setup</a>'
                    f'</body></html>'), 400
        if not code:
            return (f'<html><body style="font-family:sans-serif;background:#111;color:#f87171">'
                    f'<h2>No code received — try again.</h2>'
                    f'<a href="/spotify-setup" style="color:#1db954">Back to setup</a>'
                    f'</body></html>'), 400
        ok, msg_txt = _finish_spotify_auth(code)
        if ok:
            return f"""<html><head><style>{_SP_CSS}</style></head><body>
              <div class="box" style="text-align:center">
              <h2>&#10003; Spotify Connected!</h2>
              <p>Music will now play silently on this machine.</p>
              <a href="/spotify-setup" style="color:#1db954">Back to setup</a>
              </div></body></html>"""
        return (f'<html><body style="font-family:sans-serif;background:#111;color:#f87171">'
                f'<h2>Error: {msg_txt}</h2>'
                f'<a href="/spotify-setup" style="color:#1db954">Try again</a>'
                f'</body></html>'), 500

    @_app.route('/spotify-manual-code', methods=['POST'])
    def _spotify_manual_code():
        """Extract the auth code from a pasted redirect URL and exchange it for tokens."""
        import urllib.parse, spotify_auth as _sp
        d   = request.get_json() or {}
        raw = d.get('url', '').strip()
        if not raw:
            return jsonify({'error': 'No URL provided'}), 400
        try:
            params = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)
            code   = (params.get('code') or [''])[0]
            error  = (params.get('error') or [''])[0]
        except Exception as e:
            return jsonify({'error': f'Could not parse URL: {e}'}), 400
        if error:
            return jsonify({'error': f'Spotify denied: {error}'}), 400
        if not code:
            return jsonify({'error': 'No code found in URL. Make sure you copied the full address bar URL.'}), 400
        ok, msg_txt = _finish_spotify_auth(code)
        if ok:
            return jsonify({'ok': True})
        return jsonify({'error': msg_txt}), 500

    @_app.route('/api/spotify-status')
    def _spotify_status():
        import spotify_auth as _sp
        return jsonify(_sp.status())

    # ── Music enabled ─────────────────────────────────────────────────────────

    @_app.route('/api/music-enabled', methods=['POST'])
    def _music_enabled():
        try:
            d = request.get_json() or {}
            enabled = bool(d.get('enabled', True))
            cmd_queue.put({'type': 'set_music_enabled', 'enabled': enabled})
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @_app.route('/api/default-zone', methods=['GET'])
    def _dz_get():
        try:
            import db as _db
            scene_id = int(request.args.get('scene_id', 0))
            row = _db.get_default_zone(scene_id)
            if not row:
                return jsonify(None)
            return jsonify({'id': row[0], 'name': row[1], 'track': row[6], 'color': row[7]})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @_app.route('/api/default-zone', methods=['POST'])
    def _dz_set():
        try:
            import db as _db
            d = request.get_json() or {}
            _db.set_default_zone(
                int(d.get('scene_id', 0)),
                d.get('name', 'Ambient'),
                d.get('track', ''),
                d.get('color', '#4488ff')
            )
            cmd_queue.put({'type': 'reload_sound_zones'})
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @_app.route('/api/default-zone', methods=['DELETE'])
    def _dz_delete():
        try:
            import db as _db
            scene_id = int(request.args.get('scene_id', 0))
            _db.clear_default_zone(scene_id)
            cmd_queue.put({'type': 'reload_sound_zones'})
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @_app.route('/api/sound-zones/<int:zid>', methods=['DELETE'])
    def _sz_delete(zid):
        try:
            import db as _db
            _db.delete_sound_zone(zid)
            cmd_queue.put({'type': 'reload_sound_zones'})
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @_app.route('/api/tta-tracks')
    def _tta_tracks():
        tracks = _load_tta_tracks()
        return jsonify(tracks=tracks)

    @_app.route('/api/sound-zone-audio/<int:zid>')
    def _sz_audio(zid):
        try:
            import db as _db
            rows = _db.get_sound_zones(0)   # fetch all; cheap
            conn = _db._conn(); cur = conn.cursor()
            cur.execute('SELECT track FROM sound_zones WHERE id=?', (zid,))
            row = cur.fetchone(); conn.close()
            if not row or not row[0]:
                abort(404)
            path = row[0]
            if not os.path.isfile(path):
                abort(404)
            return send_file(path, mimetype='audio/mpeg')
        except Exception:
            abort(404)

    # ── Entity image endpoint ─────────────────────────────────────────────────

    @_app.route('/api/entity-image/<kind>/<int:eid>')
    def _entity_image(kind, eid):
        try:
            import db as _db
            if kind not in ('character', 'enemy'):
                abort(404)
            table = 'characters' if kind == 'character' else 'enemies'
            conn = _db._conn()
            cur  = conn.cursor()
            cur.execute(f'SELECT image_path FROM {table} WHERE id=?', (eid,))
            row  = cur.fetchone()
            conn.close()
            if not row or not row[0]:
                abort(404)
            path = row[0]
            if not os.path.isfile(path):
                abort(404)
            return send_file(path)
        except Exception:
            abort(404)

# ── Campaign REST API ──────────────────────────────────────────────────────

    @_app.route('/api/campaigns', methods=['GET'])
    def _api_campaigns_list():
        try:
            import campaigns as cm
            return jsonify({'campaigns': cm.list_campaigns(), 'active': cm.get_active()})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @_app.route('/api/campaigns', methods=['POST'])
    def _api_campaigns_create():
        try:
            import campaigns as cm
            data = request.get_json() or {}
            name = (data.get('name') or '').strip()
            if not name or not cm.is_valid_name(name):
                return jsonify({'error': f'Invalid campaign name "{name}". Avoid: \\ / : * ? " < > |'}), 400
            if name in cm.list_campaigns():
                return jsonify({'error': 'Campaign already exists'}), 409
            cm.create(name)
            if data.get('switch'):
                cmd_queue.put({'type': 'create_campaign', 'name': name})
            return jsonify({'ok': True, 'name': name})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @_app.route('/api/campaigns/<name>', methods=['PATCH'])
    def _api_campaigns_rename(name):
        try:
            import campaigns as cm
            data = request.get_json() or {}
            new_name = (data.get('new_name') or '').strip()
            if not new_name or not cm.is_valid_name(new_name):
                return jsonify({'error': f'Invalid campaign name "{new_name}". Avoid: \\ / : * ? " < > |'}), 400
            if new_name in cm.list_campaigns():
                return jsonify({'error': 'A campaign with that name already exists'}), 409
            if name not in cm.list_campaigns():
                return jsonify({'error': 'Campaign not found'}), 404
            # Queue for the pygame main thread — it controls the DB connection,
            # so it's the only safe place to rename while the DB is in use.
            cmd_queue.put({'type': 'rename_campaign', 'old': name, 'new': new_name})
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @_app.route('/api/campaigns/<name>', methods=['DELETE'])
    def _api_campaigns_delete(name):
        try:
            import campaigns as cm
            if name == cm.get_active():
                return jsonify({'error': 'Cannot delete the active campaign'}), 400
            if name == 'default':
                return jsonify({'error': 'Cannot delete the default campaign'}), 400
            ok = cm.delete(name)
            cmd_queue.put({'type': 'delete_campaign', 'name': name})
            return jsonify({'ok': ok})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @_app.route('/api/campaigns/<name>/export', methods=['GET'])
    def _api_campaigns_export(name):
        try:
            import campaigns as cm
            if name == 'default':
                return jsonify({'error': 'Cannot export the default campaign'}), 400
            if name not in cm.list_campaigns():
                return jsonify({'error': 'Campaign not found'}), 404
            if not pin_manager.has_pin(name):
                return jsonify({'error': 'Set a PIN for this campaign before saving it'}), 400
            data = cm.export_zip(name)
            return send_file(io.BytesIO(data), as_attachment=True,
                             download_name=f'{name}.zip', mimetype='application/zip')
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @_app.route('/api/campaigns/import', methods=['POST'])
    def _api_campaigns_import():
        try:
            import campaigns as cm
            name      = (request.form.get('name') or '').strip()
            overwrite = request.form.get('overwrite') == 'true'
            f = request.files.get('file')
            if not f or f.filename == '':
                return jsonify({'error': 'No file uploaded'}), 400
            if not name or not cm.is_valid_name(name):
                return jsonify({'error': f'Invalid campaign name "{name}". Avoid: \\ / : * ? " < > |'}), 400
            if name == 'default':
                return jsonify({'error': 'Cannot import as the default campaign'}), 400

            exists = name in cm.list_campaigns()
            if exists and not overwrite:
                return jsonify({'error': 'A campaign with that name already exists'}), 409

            tmp_dir  = tempfile.mkdtemp(prefix='realmscape_import_')
            zip_path = os.path.join(tmp_dir, 'upload.zip')
            f.save(zip_path)
            try:
                cm.validate_campaign_zip(zip_path)
            except ValueError as e:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return jsonify({'error': str(e)}), 400

            if exists:
                # Might be the active campaign (or become it before this is
                # processed) — let the pygame main thread make the call, since
                # it alone controls the DB connection and in-memory state.
                cmd_queue.put({'type': 'import_campaign', 'name': name, 'zip_path': zip_path})
            else:
                cm.import_zip(name, zip_path)
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return jsonify({'ok': True, 'name': name})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @_app.route('/api/pin-status')
    def _api_pin_status():
        return jsonify({'has_pin': pin_manager.has_pin(), 'locked': pin_manager.locked})

    @_app.route('/api/lock', methods=['POST'])
    def _api_lock():
        if not pin_manager.has_pin():
            return jsonify({'error': 'No PIN configured — set a PIN first.'}), 400
        pin_manager.lock()
        return jsonify({'ok': True, 'locked': True})

    @_app.route('/api/unlock', methods=['POST'])
    def _api_unlock():
        data = request.get_json(silent=True) or {}
        pin  = str(data.get('pin', ''))
        if pin_manager.verify_pin(pin):
            pin_manager.unlock()
            return jsonify({'ok': True, 'locked': False})
        return jsonify({'error': 'Incorrect PIN'}), 401

    @_app.route('/api/campaigns/<name>/set-pin', methods=['POST'])
    def _api_campaigns_set_pin(name):
        """First-time PIN setup for a campaign, required before it can be
        Saved (exported). Refuses 'default' and refuses to overwrite an
        existing PIN — there is no "change PIN" flow, by design."""
        try:
            import campaigns as cm
            if name == 'default':
                return jsonify({'error': 'The default campaign can never have a PIN'}), 400
            if name not in cm.list_campaigns():
                return jsonify({'error': 'Campaign not found'}), 404
            if pin_manager.has_pin(name):
                return jsonify({'error': 'This campaign already has a PIN'}), 409
            data = request.get_json(silent=True) or {}
            pin  = str(data.get('pin', ''))
            if len(pin) < 4:
                return jsonify({'error': 'PIN must be at least 4 digits'}), 400
            pin_manager.set_pin(name, pin)
            # Deliberately does NOT lock immediately — the DM just typed this
            # PIN in order to Save right now; it only takes effect (requires
            # entry) the next time this campaign is loaded/switched to.
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ── User Manual ───────────────────────────────────────────────────────────

    @_app.route('/manual/<path:filename>')
    def _manual_asset(filename):
        """Serve images and other assets from the manual/ folder."""
        manual_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'manual')
        return send_from_directory(manual_dir, filename)

    @_app.route('/manual')
    def _manual():
        manual_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'user_manual.md')
        try:
            import markdown as _md
        except ImportError:
            return (
                '<h2>Manual unavailable</h2>'
                '<p>Install the <code>markdown</code> package:<br>'
                '<code>pip install markdown</code></p>'
                '<p>Then restart RealmScape.</p>'
            ), 500
        try:
            with open(manual_path, encoding='utf-8') as f:
                raw = f.read()
        except FileNotFoundError:
            return '<h2>user_manual.md not found.</h2>', 404

        import re as _re
        def _slugify(value, sep):
            # Treat em/en dash (with surrounding spaces) as a double separator,
            # matching the -- style used in the manual's TOC links.
            value = _re.sub(r'\s*[—–]\s*', sep * 2, value)
            value = _re.sub(r'[^\w\s-]', '', value).strip().lower()
            value = _re.sub(r'\s+', sep, value)
            return value

        body = _md.markdown(raw, extensions=['tables', 'fenced_code', 'toc'],
                            extension_configs={'toc': {'slugify': _slugify}})
        html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RealmScape — User Manual</title>
  <style>
    :root {{
      --bg:      #1a1d2e;
      --surface: #23273a;
      --border:  #383d56;
      --accent:  #7b68ee;
      --gold:    #e6c84a;
      --text:    #dde1f0;
      --muted:   #8a91b0;
      --code-bg: #141620;
      --link:    #64b0ff;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.7;
      padding: 0 0 60px;
    }}
    /* Sticky header */
    header {{
      position: sticky; top: 0; z-index: 100;
      background: #0f1120;
      border-bottom: 2px solid var(--accent);
      padding: 14px 40px;
      display: flex; align-items: center; gap: 16px;
    }}
    header h1 {{ font-size: 1.2rem; color: var(--gold); letter-spacing: .04em; }}
    header span {{ color: var(--muted); font-size: .9rem; }}
    /* Layout */
    .wrap {{
      max-width: 900px;
      margin: 0 auto;
      padding: 40px 32px 0;
    }}
    /* Typography */
    h1 {{ font-size: 2rem;   color: var(--gold);   margin: 36px 0 12px; border-bottom: 2px solid var(--border); padding-bottom: 8px; }}
    h2 {{ font-size: 1.5rem; color: var(--accent);  margin: 32px 0 10px; }}
    h3 {{ font-size: 1.15rem; color: #a0b8ff; margin: 24px 0 8px; }}
    h4 {{ font-size: 1rem;   color: var(--muted);  margin: 18px 0 6px; text-transform: uppercase; letter-spacing: .06em; }}
    p  {{ margin: 10px 0; }}
    a  {{ color: var(--link); text-decoration: underline; }}
    a:hover {{ color: #fff; }}
    ul, ol {{ margin: 10px 0 10px 28px; }}
    li {{ margin: 4px 0; }}
    /* Blockquotes (tips/notes) */
    blockquote {{
      background: var(--surface);
      border-left: 4px solid var(--gold);
      border-radius: 0 6px 6px 0;
      margin: 14px 0;
      padding: 12px 16px;
      color: var(--text);
    }}
    blockquote strong {{ color: var(--gold); }}
    /* Tables */
    table {{
      width: 100%; border-collapse: collapse;
      margin: 16px 0; font-size: .93rem;
    }}
    th {{
      background: var(--surface); color: var(--accent);
      padding: 10px 14px; text-align: left;
      border-bottom: 2px solid var(--border);
    }}
    td {{ padding: 8px 14px; border-bottom: 1px solid var(--border); }}
    tr:hover td {{ background: #1e2236; }}
    /* Code */
    code {{
      background: var(--code-bg); color: #a8d0ff;
      padding: 2px 6px; border-radius: 4px;
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: .88em;
    }}
    pre {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 14px 18px;
      overflow-x: auto;
      margin: 14px 0;
    }}
    pre code {{ background: none; padding: 0; }}
    /* Screenshot placeholders */
    p:has(strong:first-child) strong:first-child {{
      display: inline;
    }}
    /* HR */
    hr {{ border: none; border-top: 1px solid var(--border); margin: 36px 0; }}
    /* Checklist */
    li input[type=checkbox] {{ margin-right: 6px; accent-color: var(--accent); }}
  </style>
</head>
<body>
  <header>
    <h1>&#9876; RealmScape</h1>
    <span>User Manual</span>
  </header>
  <div class="wrap">
    {body}
  </div>
</body>
</html>'''
        return html

    @_sio.on('connect')
    def _on_connect():
        global _dm_client_count
        _dm_client_count += 1
        cmd_queue.put({'type': '_request_state'})

    @_sio.on('disconnect')
    def _on_disconnect():
        global _dm_client_count
        _dm_client_count = max(0, _dm_client_count - 1)

    @_sio.on('command')
    def _on_command(data):
        if pin_manager.locked and data.get('type') != '_request_state':
            return   # silently drop all control commands when locked
        cmd_queue.put(data)


def set_bg_path(path: str):
    _bg_path_holder[0] = path or ''


def broadcast_state(state: dict):
    if _AVAILABLE:
        _sio.emit('state', state)


def start_server(port: int = 5000):
    if not _AVAILABLE:
        print('[DM Server] flask / flask-socketio not installed — DM panel disabled.')
        print('[DM Server] Run:  pip install flask flask-socketio')
        return
    def _run():
        kwargs = {'host': '0.0.0.0', 'port': port, 'log_output': False}
        if _ASYNC_MODE == 'threading':
            kwargs['allow_unsafe_werkzeug'] = True
        _sio.run(_app, **kwargs)
    t = threading.Thread(target=_run, daemon=True, name='dm-server')
    t.start()
    import socket
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = '127.0.0.1'
    print(f'[DM Server] Listening on  http://{ip}:{port}  (LAN)')
    print(f'[DM Server] Also reachable at  http://localhost:{port}')
