# main.py  –  RealmScape
import sys as _sys
import os

# Force SDL2 software renderer on Linux — bypass Cinnamon compositor's GL
# context and avoid X11 BadAccess when the browser competes for the GPU.
if _sys.platform != 'win32':
    os.environ['SDL_RENDER_DRIVER'] = 'software'
    os.environ['SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR'] = '1'

import pygame
import random, math, queue, subprocess, re as _re, threading, hashlib, webbrowser, socket, shutil

def _detect_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

_LOCAL_IP  = _detect_local_ip()
_GM_URL    = f'http://{_LOCAL_IP}:5000'

if _sys.platform == 'win32':
    from pygame._sdl2.video import Window as _SDLWindow
else:
    _SDLWindow = None

from constants import *
from entities  import Layer, Character, SceneMarker, SoundZone
from ui        import Toolbar, ContextMenu, InitiativePanel, HPPopup, ConditionsPopup, CharacterDialog, EnemyDialog, SizePopup, NotesPanel, StatBlockPanel, NumberInputPopup, ScenePickerPopup, CampaignDialog, SoundZoneDialog, TabletopAudioBrowserDialog, HiddenItemDialog, TrapDialog, DCRollPopup, DCResultPopup, LockOverlay, HintPopup, ConfirmPopup, GroupHPPopup, NewSceneChoicePopup, DungeonGenDialog, DungeonGenProgressPopup, DungeonGenPreviewPopup
import pin_manager
from tools     import FogOfWar, AoeTool, MeasureTool
import db
from feedback  import sound_fx, press_fx
import campaigns as campaigns_mod
import server as dm_server
import updater
import telemetry

# ── Campaign init (must happen before db.init_db) ────────────────────────────
campaigns_mod.migrate_legacy_db()

if campaigns_mod.is_demo_mode():
    for _purged_name in campaigns_mod.purge_stale_campaigns(days=30):
        print(f'[Demo Mode] Purged stale campaign (no PIN, unused 30+ days): {_purged_name}')
    active_campaign = 'default'
    campaigns_mod.set_active(active_campaign)
else:
    active_campaign = campaigns_mod.get_active()

if active_campaign not in campaigns_mod.list_campaigns():
    campaigns_mod.create(active_campaign)
db.set_db_path(campaigns_mod.db_path(active_campaign))
campaigns_mod.touch_last_loaded(active_campaign)
pin_manager.set_active_campaign(active_campaign)

# ── DB init ───────────────────────────────────────────────────────────────────
db.init_db()
_orphan_counts = db.cleanup_orphaned_records()
if _orphan_counts:
    print(f'[Startup] Removed orphaned records: { {k: v for k, v in _orphan_counts.items()} }')
window_state = db.get_window_state()
os.environ['SDL_VIDEO_WINDOW_POS'] = f"{window_state['x']},{window_state['y']}"
cam_x, cam_y = db.get_current_location()
camera_x, camera_y = float(cam_x), float(cam_y)

# ── Pygame init ───────────────────────────────────────────────────────────────
# Belt-and-suspenders: also set the SDL2 hint via C API so it takes effect
# even if SDL_Init() processed env vars before our os.environ assignment.
if _sys.platform != 'win32':
    try:
        import ctypes as _ctypes
        _sdl2 = _ctypes.CDLL('libSDL2-2.0.so.0')
        _sdl2.SDL_SetHint(b'SDL_RENDER_DRIVER', b'software')
        _sdl2.SDL_SetHint(b'SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR', b'1')
    except Exception:
        pass

pygame.init()
WIDTH, HEIGHT = window_state['width'], window_state['height']
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
try:
    # Maximize on every launch, then immediately adopt the resulting size so
    # layout code below (layers, toolbar, etc.) never runs against the stale
    # pre-maximize dimensions while waiting for a resize event to catch up.
    from pygame._sdl2.video import Window as _StartupWindow
    _startup_win = _StartupWindow.from_display_module()
    _startup_win.maximize()
    WIDTH, HEIGHT = _startup_win.size
    window_state['width'], window_state['height'] = WIDTH, HEIGHT
except Exception:
    pass   # not fatal — window just opens at its last saved size if this fails
pygame.display.set_caption(f"RealmScape — {active_campaign}  |  GM Panel: {_GM_URL}")
_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'icon.png')
if os.path.exists(_icon_path):
    pygame.display.set_icon(pygame.image.load(_icon_path))
try:
    pygame.scrap.init()
except Exception:
    pass

font       = pygame.font.Font(None, 24)
small_font = pygame.font.Font(None, 16)
tb_font    = pygame.font.Font(None, 22)
big_font   = pygame.font.Font(None, 48)

# ── Helpers ───────────────────────────────────────────────────────────────────

def draw_grid(surface, cam_x, cam_y, screen_w, screen_h, tb_h):
    """Draw a world-aligned scrolling grid directly onto surface."""
    overlay = pygame.Surface((screen_w, screen_h - tb_h), pygame.SRCALPHA)
    col0 = int(cam_x // GRID_SIZE)
    row0 = int(cam_y // GRID_SIZE)
    for col in range(col0, col0 + screen_w // GRID_SIZE + 2):
        sx = int(col * GRID_SIZE - cam_x)
        pygame.draw.line(overlay, (255, 255, 255, 50), (sx, 0), (sx, screen_h - tb_h))
    for row in range(row0, row0 + screen_h // GRID_SIZE + 2):
        sy = int(row * GRID_SIZE - cam_y)
        pygame.draw.line(overlay, (255, 255, 255, 50), (0, sy), (screen_w, sy))
    surface.blit(overlay, (0, tb_h))

def load_bg(path, w, h, zoom=1.0):
    if path:
        path = campaigns_mod.resolve_image_path(path)
    if path and os.path.exists(path):
        try:
            img = pygame.image.load(path).convert()
            if zoom != 1.0:
                nw = max(1, int(img.get_width()  * zoom))
                nh = max(1, int(img.get_height() * zoom))
                img = pygame.transform.smoothscale(img, (nw, nh))
            big = pygame.Surface((max(w, img.get_width()), max(h, img.get_height())))
            big.fill(BLACK)
            # Left/top-justified, not centered — token world coordinates are
            # relative to the image's own (0,0), so centering it inside a
            # larger canvas (e.g. a maximized window bigger than the image)
            # would shift the map out from under every token's stored position.
            big.blit(img, (0, 0))
            return big
        except pygame.error:
            pass
    surf = pygame.Surface((max(w, 2000), max(h, 2000)))
    surf.fill((50, 50, 50))
    return surf

def rebuild_layers(bg_path, w, h, zoom=1.0):
    bg = load_bg(bg_path, w, h, zoom)
    return [Layer(bg, 1)]

def snap(v, size):
    return round(v / size) * size

# ── Entities ──────────────────────────────────────────────────────────────────
db.ensure_default_characters()
db.ensure_default_enemies()

def load_entity(row, is_enemy):
    if is_enemy:
        id_, name, x, y, color_hex, size, img_path, hp, max_hp, cond_str, initiative, sc_id = row[:12]
        is_npc_val = False
        init_bonus = 0
    else:
        id_, name, x, y, color_hex, size, img_path, hp, max_hp, cond_str, initiative, is_npc_val, sc_id = row[:13]
        init_bonus = row[13] if len(row) > 13 else 0
    ent = Character(x, y, pygame.Color(color_hex), size, name,
                    id=id_, is_enemy=is_enemy)
    ent.hp = hp or 10; ent.max_hp = max_hp or 10
    ent.initiative = initiative or 0
    ent.init_bonus = init_bonus or 0
    ent.scene_id = sc_id if sc_id is not None else 0
    ent.is_npc = bool(is_npc_val)
    ent.load_conditions(cond_str or '')
    ent.image_path = img_path or ''
    if img_path:
        ent.set_image(img_path)
    return ent

# ── Scenes ────────────────────────────────────────────────────────────────────
scenes           = db.get_all_scenes()   # list of (id, name, image_path, cam_x, cam_y)
start_scene_id   = db.get_start_scene_id()   # 0 = "use first scene"
current_scene_idx = next(
    (i for i, s in enumerate(scenes) if s[0] == start_scene_id),
    0
) if scenes else 0

def current_scene():
    return scenes[current_scene_idx] if scenes else None

def scene_id():
    s = current_scene()
    return s[0] if s else 0

def scene_name():
    s = current_scene()
    return s[1] if s else '— no scene —'

def reload_enemies():
    global enemies
    enemies = [load_entity(r, True) for r in db.load_enemies_from_db(scene_id())]

_transient_markers = {}   # {scene_id: [SceneMarker, ...]} — in-memory return portals


def _add_transient_marker(marker):
    """Register a transient (id=None) return portal in the persistent in-memory store."""
    sid = scene_id()
    bucket = _transient_markers.setdefault(sid, [])
    if not any(m.to_scene_id == marker.to_scene_id for m in bucket):
        bucket.append(marker)


def reload_markers():
    global scene_markers
    scene_markers = []
    sid = scene_id()
    if not sid:
        return
    scene_name_map = {s[0]: s[1] for s in scenes}
    for mid, to_sid, mx, my in db.get_scene_markers(sid):
        name = scene_name_map.get(to_sid, '???')
        scene_markers.append(SceneMarker(mid, mx, my, to_sid, name))
    # Restore in-memory transient return portals for this scene
    for tm in _transient_markers.get(sid, []):
        if not any(m.to_scene_id == tm.to_scene_id for m in scene_markers):
            scene_markers.append(tm)

def reload_scene_npcs():
    """Drop NPCs from the previous scene, load NPCs for the current scene.
    Global party members (scene_id=0) are left untouched."""
    global characters
    characters = [c for c in characters if not getattr(c, 'is_npc', False)]
    sid = scene_id()
    if sid:
        characters.extend(load_entity(r, False) for r in db.load_scene_npcs(sid))
    rebuild_initiative()

characters = [load_entity(r, False) for r in db.load_global_characters()]
reload_enemies()
reload_markers()

# ── Sound zones ───────────────────────────────────────────────────────────────
sound_zones    = []
default_zone   = None    # ambient fallback, no bounds
active_zone_id      = None
show_zones          = True    # toolbar toggle
music_enabled       = True    # per-campaign flag
build_mode          = False   # when True: all DM objects visible regardless of fog/game state
_pre_build_fog      = None    # saved fog state while build mode is active

def reload_sound_zones():
    global sound_zones, default_zone, music_enabled
    rows = db.get_sound_zones(scene_id())
    sound_zones = [SoundZone(*r) for r in rows]
    dr = db.get_default_zone(scene_id())
    default_zone = SoundZone(*dr) if dr else None
    music_enabled = db.get_music_enabled()

reload_sound_zones()


# ── Hidden items & traps data classes ─────────────────────────────────────────

class HiddenItem:
    __slots__ = ('id','scene_id','x','y','radius','dc','description','found')
    def __init__(self, id, scene_id, x, y, radius, dc, description, found):
        self.id = id; self.scene_id = scene_id
        self.x = float(x); self.y = float(y); self.radius = float(radius)
        self.dc = int(dc); self.description = description; self.found = bool(found)

class SceneTrap:
    __slots__ = ('id','scene_id','x','y','radius','description','triggered')
    def __init__(self, id, scene_id, x, y, radius, description, triggered):
        self.id = id; self.scene_id = scene_id
        self.x = float(x); self.y = float(y); self.radius = float(radius)
        self.description = description; self.triggered = bool(triggered)

hidden_items      = []
scene_traps_list  = []
dc_roll_popup     = None
dc_result_popup   = None
trap_flash_timer  = 0
_item_cooldowns   = {}
_place_item_mode  = False
_place_trap_mode  = False
_place_item_dialog = None
_place_trap_dialog = None
_place_pending_pos = None
_edit_item_dialog  = None
_edit_trap_dialog  = None
_edit_item_obj     = None
_edit_trap_obj     = None

# ── Hidden items & traps loader ────────────────────────────────────────────────

def reload_hidden_items():
    global hidden_items
    hidden_items = [HiddenItem(*r) for r in db.get_scene_items(scene_id())]

def reload_scene_traps():
    global scene_traps_list
    scene_traps_list = [SceneTrap(*r) for r in db.get_scene_traps(scene_id())]

reload_hidden_items()
reload_scene_traps()


_SP_RE               = _re.compile(
    r'open\.spotify\.com/(track|playlist|album|artist)/([A-Za-z0-9]+)')
_tta_songlist        = None   # {N: {'title': str, 'url': str}} once loaded, {} on failure

# Application-level audio cache (shared across all campaigns)
_AUDIO_CACHE_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache', 'audio')
_pending_music    = None      # set by download thread; main loop loads & plays it
_pending_music_lock = threading.Lock()


def _audio_cache_path(url):
    """Stable local path for a remote audio URL, keyed by MD5 of the URL."""
    ext = os.path.splitext(url.split('?')[0])[-1].lower()
    if ext not in ('.mp3', '.ogg', '.wav', '.flac'):
        ext = '.mp3'
    return os.path.join(_AUDIO_CACHE_DIR, hashlib.md5(url.encode()).hexdigest() + ext)


def _is_direct_audio(url):
    """True when the URL is a directly downloadable audio file."""
    from urllib.parse import urlparse
    path = urlparse(url).path.lower()
    return any(path.endswith(e) for e in ('.mp3', '.ogg', '.wav', '.flac'))


def _download_and_signal(url, referrer=None):
    """Download *url* to the shared cache (if not already present) then signal
    the main loop to start playing it.  Always runs in a background thread."""
    global _pending_music
    os.makedirs(_AUDIO_CACHE_DIR, exist_ok=True)
    cache_path = _audio_cache_path(url)
    if not os.path.isfile(cache_path):
        print(f'[Audio] downloading → {cache_path}')
        import urllib.request
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; RealmScape/1.0)'}
            if referrer:
                headers['Referer'] = referrer
            req = urllib.request.Request(url, headers=headers)
            tmp = cache_path + '.part'
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, 'wb') as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
            os.replace(tmp, cache_path)
            print(f'[Audio] cached: {os.path.basename(cache_path)}')
        except Exception as e:
            print(f'[Audio] download failed: {e}')
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
            return
    else:
        print(f'[Audio] cache hit: {os.path.basename(cache_path)}')
    with _pending_music_lock:
        _pending_music = cache_path

# Suppress console windows on Windows for all child processes
def _dbus_spotify(method, *args):
    """Fire a D-Bus method on the running Spotify MPRIS interface (Linux only)."""
    subprocess.run(
        ['dbus-send', '--type=method_call',
         '--dest=org.mpris.MediaPlayer2.spotify',
         '/org/mpris/MediaPlayer2', method] + list(args),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, timeout=3)


_TTA_JS_URL  = 'https://tabletopaudio.com/bootstrap/js/tta4XFADE3_min.js'
_TTA_CDN     = 'https://sounds.tabletopaudio.com/'
_TTA_REFERER = 'https://tabletopaudio.com/'


def _load_tta_songlist():
    """Fetch and parse the TTA JS bundle. Caches result in _tta_songlist. Thread-safe read."""
    global _tta_songlist
    if _tta_songlist is not None:
        return _tta_songlist
    import urllib.request, re
    try:
        req = urllib.request.Request(
            _TTA_JS_URL,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; RealmScape/1.0)'})
        with urllib.request.urlopen(req, timeout=20) as r:
            js = r.read().decode('utf-8', errors='ignore')
        # Pattern inside the bundle: song_N:{title:"TITLE",artist:i,mp3:e+"FILENAME.mp3"}
        entries = _re.findall(
            r'song_(\d+):\{title:"([^"]+)",artist:\w+,mp3:\w\+"([^"]+)"', js)
        _tta_songlist = {
            int(n): {'title': title, 'url': _TTA_CDN + fname}
            for n, title, fname in entries
        }
        print(f'[Audio] TTA: loaded {len(_tta_songlist)} tracks')
    except Exception as e:
        print(f'[Audio] TTA songlist load failed: {e}')
        _tta_songlist = {}
    return _tta_songlist


def _resolve_tta_url(page_url):
    """Resolve a tabletopaudio.com ?N URL to the direct CDN MP3 URL."""
    m = _re.search(r'\?(\d+)$', page_url)
    if not m:
        print(f'[Audio] TTA: unrecognised URL format: {page_url}')
        return None
    idx      = int(m.group(1))
    songlist = _load_tta_songlist()
    entry    = songlist.get(idx)
    if entry:
        print(f'[Audio] TTA: {entry["title"]} → {entry["url"]}')
        return entry['url']
    print(f'[Audio] TTA: track {idx} not found in songlist ({len(songlist)} tracks loaded)')
    return None


def _zone_play(zone):
    """Play the zone's track on this machine without touching the GUI.

    • Local MP3/OGG/WAV  → pygame.mixer.music (in-process)
    • Spotify URL        → Web API call in daemon thread
    • TTA / direct URL  → cached download then pygame.mixer.music
    """
    if not zone or not zone.track:
        return
    track = zone.track.strip()

    # ── Local file ────────────────────────────────────────────────────────────
    if os.path.isfile(track):
        try:
            pygame.mixer.music.load(track)
            pygame.mixer.music.play(-1)
        except Exception as e:
            print(f'[Audio] local: {e}')
        return

    # ── Spotify URI → running Spotify instance (no auth required) ────────────
    sp = _SP_RE.search(track)
    if sp:
        uri      = f"spotify:{sp.group(1)}:{sp.group(2)}"
        is_track = sp.group(1) == 'track'
        def _open_spotify():
            try:
                if _sys.platform == 'win32':
                    import os as _os
                    _os.startfile(uri)          # passes URI to running Spotify silently
                    # Spotify Web API is the only way to set repeat on Windows;
                    # try it silently — skips gracefully if not authenticated.
                    try:
                        import spotify_auth as _sp_auth
                        if _sp_auth.is_authed():
                            repeat = 'track' if is_track else 'context'
                            _sp_auth._api('PUT', f'/me/player/repeat?state={repeat}')
                    except Exception:
                        pass
                else:
                    # Prefer Web API (silent HTTP, no window focus) over D-Bus
                    try:
                        import spotify_auth as _sp_auth
                        if _sp_auth.is_authed():
                            ok, msg = _sp_auth.play(uri)
                            if ok:
                                return
                            print(f'[Spotify] Web API: {msg}')
                    except Exception as _e:
                        print(f'[Spotify] Web API error: {_e}')
                    # Fall back to D-Bus MPRIS if Web API failed or not authed
                    _dbus_spotify('org.mpris.MediaPlayer2.Player.OpenUri',
                                  f'string:{uri}')
                    loop_val = 'Track' if is_track else 'Playlist'
                    subprocess.run(
                        ['dbus-send', '--type=method_call',
                         '--dest=org.mpris.MediaPlayer2.spotify',
                         '/org/mpris/MediaPlayer2',
                         'org.freedesktop.DBus.Properties.Set',
                         'string:org.mpris.MediaPlayer2.Player',
                         'string:LoopStatus',
                         f'variant:string:{loop_val}'],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=3)
            except Exception as e:
                print(f'[Audio] Spotify open failed: {e}')
        threading.Thread(target=_open_spotify, daemon=True, name='spotify-play').start()
        return

    # ── Tabletop Audio / direct audio URL ────────────────────────────────────
    def _launch_url():
        play_url = track
        if 'tabletopaudio.com' in track:
            resolved = _resolve_tta_url(track)
            if resolved:
                play_url = resolved
                print(f'[Audio] TTA resolved: {resolved}')
        if _is_direct_audio(play_url):
            is_tta   = 'sounds.tabletopaudio.com' in play_url
            referrer = _TTA_REFERER if is_tta else None
            _download_and_signal(play_url, referrer=referrer)
        else:
            print(f'[Audio] unsupported URL (only direct audio files and TTA are supported): {play_url}')
    threading.Thread(target=_launch_url, daemon=True, name='audio-launch').start()


def _spotify_stop_all():
    """Stop Spotify via Web API; fall back to platform methods only if API fails."""
    _api_stopped = False
    try:
        import spotify_auth as _sp_auth
        _sp_auth.stop()   # Web API pause
        _api_stopped = True
    except Exception:
        pass
    if _api_stopped:
        return   # Web API handled it
    # Web API unavailable — use platform-specific fallback
    try:
        if _sys.platform == 'win32':
            # Send stop only to the Spotify window
            import ctypes
            HWND_BROADCAST = 0xFFFF
            WM_APPCOMMAND  = 0x0319
            APPCOMMAND_MEDIA_STOP = 8
            # FindWindowW returns 0 if Spotify isn't open — safe to call
            hwnd = ctypes.windll.user32.FindWindowW('SpotifyMainWindow', None)
            if hwnd:
                ctypes.windll.user32.SendMessageW(
                    hwnd, WM_APPCOMMAND, 0, APPCOMMAND_MEDIA_STOP << 16)
        else:
            _dbus_spotify('org.mpris.MediaPlayer2.Player.Pause')
            subprocess.run(
                ['dbus-send', '--type=method_call',
                 '--dest=org.mpris.MediaPlayer2.spotify',
                 '/org/mpris/MediaPlayer2',
                 'org.freedesktop.DBus.Properties.Set',
                 'string:org.mpris.MediaPlayer2.Player',
                 'string:LoopStatus',
                 'variant:string:None'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=3)
    except Exception:
        pass


def _zone_stop():
    """Stop all audio without blocking the game loop."""
    global _pending_music
    with _pending_music_lock:
        _pending_music = None   # discard any download that hasn't loaded yet
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass
    threading.Thread(target=_spotify_stop_all, daemon=True, name='spotify-stop').start()


def _stop_all_audio_sync():
    """Synchronous audio shutdown — for use at app exit only."""
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass
    t = threading.Thread(target=_spotify_stop_all, daemon=True, name='spotify-stop-exit')
    t.start()
    t.join(timeout=3)

def check_zone_detection():
    """Check which sound zone (if any) contains a player. Falls back to default_zone."""
    global active_zone_id
    for zone in sound_zones:
        for char in characters:
            if zone.contains(char.x, char.y):
                if zone.id != active_zone_id:
                    active_zone_id = zone.id
                    _zone_stop()
                    if music_enabled:
                        _zone_play(zone)
                return
    # No positional zone matched — use default ambient if available
    default_id = default_zone.id if default_zone else None
    if active_zone_id != default_id:
        active_zone_id = default_id
        _zone_stop()
        if music_enabled and default_zone:
            _zone_play(default_zone)

def _apply_music_enabled(enabled):
    """Toggle music on/off, saving to DB and triggering immediate playback change."""
    global music_enabled, active_zone_id
    music_enabled = enabled
    db.set_music_enabled(enabled)
    if enabled:
        # Force re-trigger so the correct track starts immediately
        active_zone_id = None
        check_zone_detection()
    else:
        _zone_stop()

# Init pygame.mixer for local audio
try:
    pygame.mixer.init()
    sound_fx.init()
except Exception:
    pass

# Zone draw mode state
zone_draw_mode         = False
zone_draw_start        = None   # (world_x, world_y)
zone_draw_cur          = None   # (world_x, world_y)  – live cursor position
zone_dialog            = None
zone_dialog_is_default = False   # True when dialog is editing the default ambient track

# ── Initiative order ──────────────────────────────────────────────────────────
initiative_order: list = []
current_turn_idx: int  = 0

def rebuild_initiative():
    global initiative_order, current_turn_idx
    all_ents = characters + enemies
    initiative_order = sorted(all_ents, key=lambda e: e.initiative, reverse=True)
    current_turn_idx = 0

rebuild_initiative()

# ── Initial layers ────────────────────────────────────────────────────────────
_s0          = scenes[current_scene_idx] if scenes else None
bg_path      = (_s0[2] if _s0 and _s0[2] else window_state.get('image_path', ''))
# Also restore the start scene's saved camera position
if _s0:
    camera_x, camera_y = float(_s0[3]), float(_s0[4])
current_zoom = db.get_scene_zoom(scene_id()) if scenes else 1.0
layers       = rebuild_layers(bg_path, WIDTH, HEIGHT, current_zoom)
for layer in layers:
    layer.x = -camera_x
    layer.y = -camera_y
    layer.clamp(WIDTH, HEIGHT - TOOLBAR_HEIGHT)
if layers:
    camera_x, camera_y = -layers[0].x, -layers[0].y

# ── DM remote server ─────────────────────────────────────────────────────────
dm_server.set_bg_path(bg_path)
dm_server.start_server(port=5000)
_dm_tick = 0           # frame counter for periodic state broadcast

# ── Spotify startup check ─────────────────────────────────────────────────────
if _sys.platform != 'win32':
    def _spotify_ensure():
        import spotify_auth as _sp
        _sp.ensure_running()
    threading.Thread(target=_spotify_ensure, daemon=True,
                     name='spotify-ensure').start()

# ── Hotspot status overlay ────────────────────────────────────────────────────
import json as _json

_HOTSPOT_STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    'campaigns', '.hotspot_status.json')
_HOTSPOT_STATUS: dict = {}
_HOTSPOT_POLL_T: float = 0.0
_HOTSPOT_STALE_S = 15   # seconds before a missed heartbeat is considered dead


def _poll_hotspot_status() -> dict:
    """Read the daemon status file at most once every 5 seconds."""
    global _HOTSPOT_STATUS, _HOTSPOT_POLL_T
    import time as _time
    now = _time.time()
    if now - _HOTSPOT_POLL_T < 5:
        return _HOTSPOT_STATUS
    _HOTSPOT_POLL_T = now
    try:
        with open(_HOTSPOT_STATUS_FILE) as _f:
            data = _json.load(_f)
        if now - data.get('heartbeat', 0) > _HOTSPOT_STALE_S:
            _HOTSPOT_STATUS = {}
        else:
            _HOTSPOT_STATUS = data if data.get('status') == 'active' else {}
    except (FileNotFoundError, _json.JSONDecodeError, OSError):
        _HOTSPOT_STATUS = {}
    return _HOTSPOT_STATUS


def _effective_gm_url() -> str:
    """Return the GM URL using the hotspot IP when the daemon is active."""
    info = _HOTSPOT_STATUS
    if info.get('status') == 'active':
        return f"http://{info['ip']}:{info.get('port', 5000)}"
    return _GM_URL


def draw_hotspot_overlay(surface, fnt, small_fnt):
    """Draw SSID / password / URL when the hotspot is active and GM not yet connected."""
    info = _poll_hotspot_status()
    if not info:
        return
    if dm_server.dm_connected():
        return  # GM is connected — no need to show credentials
    ssid = info.get('ssid', '')
    pw   = info.get('password', '')
    ip   = info.get('ip', '')
    port = info.get('port', 5000)
    lines = [
        (fnt,       'Private Hotspot'),
        (small_fnt, f'SSID : {ssid}'),
        (small_fnt, f'PW   : {pw}'),
        (small_fnt, f'URL  : http://{ip}:{port}'),
    ]
    pad  = 8
    lh   = [f.get_height() for f, _ in lines]
    tw   = [f.size(t)[0]   for f, t in lines]
    W    = max(tw) + pad * 2
    H    = sum(lh) + pad * 2 + (len(lines) - 1) * 3
    x    = surface.get_width() - W - 6
    y    = TOOLBAR_HEIGHT + 6
    bg   = pygame.Surface((W, H), pygame.SRCALPHA)
    bg.fill((15, 25, 50, 210))
    surface.blit(bg, (x, y))
    pygame.draw.rect(surface, (80, 140, 255), (x, y, W, H), 1)
    cy = y + pad
    for (f, text), h in zip(lines, lh):
        s = f.render(text, True, WHITE)
        surface.blit(s, (x + pad, cy))
        cy += h + 3


# ── Legend geometry ───────────────────────────────────────────────────────────
LEGEND_MARGIN  = 10
LEGEND_WIDTH   = 200
LEGEND_HEIGHT  = 120

def _legend_size():
    party = [c for c in characters if not getattr(c, 'is_npc', False)]
    if not party:
        return 200, 120
    mw = max(font.size(c.name)[0] for c in party)
    return mw + 70, len(party) * 30 + 10

legend_surface = pygame.Surface((LEGEND_WIDTH, LEGEND_HEIGHT))

def draw_char_legend(renaming=None, new_name=''):
    global legend_surface, LEGEND_WIDTH, LEGEND_HEIGHT
    w, h = _legend_size()
    if w != LEGEND_WIDTH or h != LEGEND_HEIGHT:
        LEGEND_WIDTH, LEGEND_HEIGHT = w, h
        legend_surface = pygame.Surface((w, h))
    legend_surface.fill(GRAY)
    pygame.draw.rect(legend_surface, WHITE, (0, 0, LEGEND_WIDTH, LEGEND_HEIGHT), 2)
    ROW_H   = 30
    GAP     = 6
    party   = [c for c in characters if not getattr(c, 'is_npc', False)]
    max_tw  = max((font.size(c.name)[0] for c in party), default=0)
    block_w = 20 + GAP + max_tw
    ico_x   = (LEGEND_WIDTH - block_w) // 2   # all icons share this x
    txt_x   = ico_x + 20 + GAP                # text left-justified to icon column
    y = 5
    for char in party:
        if char == renaming:
            txt = font.render(new_name + '|', True, WHITE)
        else:
            txt = font.render(char.name, True, WHITE)
        ico_y = y + (ROW_H - 20) // 2
        txt_y = y + (ROW_H - txt.get_height()) // 2
        if char.image:
            legend_surface.blit(pygame.transform.scale(char.image, (20, 20)), (ico_x, ico_y))
        else:
            pygame.draw.circle(legend_surface, char.color, (ico_x + 10, ico_y + 10), 10)
        if char.selected:
            pygame.draw.circle(legend_surface, YELLOW, (ico_x + 10, ico_y + 10), 12, 2)
        legend_surface.blit(txt, (txt_x, txt_y))
        y += ROW_H
    screen.blit(legend_surface,
                (LEGEND_MARGIN, HEIGHT - LEGEND_HEIGHT - LEGEND_MARGIN))

def char_legend_rect():
    return pygame.Rect(LEGEND_MARGIN, HEIGHT - LEGEND_HEIGHT - LEGEND_MARGIN,
                       LEGEND_WIDTH, LEGEND_HEIGHT)

def char_in_legend(pos):
    local_y = pos[1] - (HEIGHT - LEGEND_HEIGHT - LEGEND_MARGIN)
    idx = local_y // 30
    party = [c for c in characters if not getattr(c, 'is_npc', False)]
    return party[idx] if 0 <= idx < len(party) else None

# ── Fog radius presets (cells × GRID_SIZE = px) ───────────────────────────────
_FOG_R_BTNS = ('fog_r15', 'fog_r30', 'fog_r45', 'fog_r60')
_FOG_R_CELLS = {15: 'fog_r15', 30: 'fog_r30', 45: 'fog_r45', 60: 'fog_r60'}
_FOG_R_PX    = {'fog_r15': 3*GRID_SIZE, 'fog_r30': 6*GRID_SIZE,
                'fog_r45': 9*GRID_SIZE, 'fog_r60': 12*GRID_SIZE}

def _apply_fog_settings(fog_on, fog_radius_cells):
    """Push persisted fog settings into the toolbar active state."""
    toolbar.active['fog_on'] = fog_on
    for btn in _FOG_R_BTNS:
        toolbar.active[btn] = False
    btn = _FOG_R_CELLS.get(fog_radius_cells, 'fog_r30')
    toolbar.active[btn] = True

def _current_vision_radius():
    for btn, px in _FOG_R_PX.items():
        if toolbar.active.get(btn):
            return px
    return 6 * GRID_SIZE   # fallback 30 ft

def _current_fog_radius_cells():
    for btn, px in _FOG_R_PX.items():
        if toolbar.active.get(btn):
            return px // GRID_SIZE
    return 6

def _is_fog_hidden(ent):
    """True when fog is on and this enemy is outside all player vision circles."""
    if not fog.edit or not ent.is_enemy:
        return False
    vr = _current_vision_radius()
    party = [c for c in characters if not getattr(c, 'is_npc', False)]
    return not any(math.hypot(ent.x - c.x, ent.y - c.y) <= vr for c in party)

def _visible_initiative():
    """Return (filtered_list, adjusted_current_idx) excluding fog-hidden enemies."""
    visible = [e for e in initiative_order if not _is_fog_hidden(e)]
    cur_ent = initiative_order[current_turn_idx] if initiative_order else None
    idx = visible.index(cur_ent) if cur_ent in visible else 0
    return visible, idx

# ── DM remote panel ───────────────────────────────────────────────────────────

def _ent_color_hex(ent):
    c = ent.color
    return f'#{c.r:02x}{c.g:02x}{c.b:02x}'

def _get_dm_state():
    mw, mh = (layers[0].img.get_size() if layers else (2000, 2000))
    return {
        'scenes':           [{'id': s[0], 'name': s[1]} for s in scenes],
        'current_scene_id': scene_id(),
        'start_scene_id':   start_scene_id,
        'fog_on':           fog.edit,
        'current_turn_idx': current_turn_idx,
        'map_width':        mw,
        'map_height':       mh,
        'camera_x':         camera_x,
        'camera_y':         camera_y,
        'view_w':           WIDTH,
        'view_h':           HEIGHT - TOOLBAR_HEIGHT,
        'characters': [
            {'id': c.id, 'name': c.name, 'x': c.x, 'y': c.y,
             'hp': c.hp, 'max_hp': c.max_hp, 'color': _ent_color_hex(c),
             'initiative': c.initiative, 'size': c.size,
             'is_npc': getattr(c, 'is_npc', False),
             'conditions': list(c.conditions),
             'img_key': os.path.basename(getattr(c, 'image_path', '') or '')}
            for c in characters
        ],
        'enemies': [
            {'id': e.id, 'name': e.name, 'x': e.x, 'y': e.y,
             'hp': e.hp, 'max_hp': e.max_hp, 'color': _ent_color_hex(e),
             'initiative': e.initiative, 'size': e.size,
             'conditions': list(e.conditions),
             'img_key': os.path.basename(getattr(e, 'image_path', '') or '')}
            for e in enemies
        ],
        'initiative_order': [
            {'id': e.id, 'is_enemy': e.is_enemy, 'name': e.name,
             'initiative': e.initiative, 'hp': e.hp, 'max_hp': e.max_hp}
            for e in initiative_order
        ],
        'visible_initiative_order': [
            {'id': e.id, 'is_enemy': e.is_enemy, 'name': e.name,
             'initiative': e.initiative, 'hp': e.hp, 'max_hp': e.max_hp,
             'is_npc': getattr(e, 'is_npc', False)}
            for e in _visible_initiative()[0]
        ],
        'markers': [
            {'id': m.id, 'x': m.x, 'y': m.y,
             'to_scene_id': m.to_scene_id, 'to_scene_name': m.to_scene_name}
            for m in scene_markers
        ],
        'campaign': {
            'active':  active_campaign,
            'all':     campaigns_mod.list_campaigns(),
            'has_pin': {n: pin_manager.has_pin(n) for n in campaigns_mod.list_campaigns()},
        },
        'sound_zones': [
            {'id': z.id, 'name': z.name, 'x': z.x, 'y': z.y,
             'w': z.w, 'h': z.h, 'track': z.track, 'color': z.color_hex}
            for z in sound_zones
        ],
        'default_zone': {'id': default_zone.id, 'name': default_zone.name,
                         'track': default_zone.track, 'color': default_zone.color_hex}
                        if default_zone else None,
        'active_zone_id':  active_zone_id,
        'music_enabled':   music_enabled,
        'scene_notes':     db.get_notes(scene_id()),
        'locked':          pin_manager.locked,
        'vision_radius':   _current_vision_radius(),
        'vision_dim':      VISION_DIM_PX,
        'hidden_items': [
            {'id': i.id, 'x': i.x, 'y': i.y, 'radius': i.radius,
             'dc': i.dc, 'description': i.description}
            for i in hidden_items if not i.found
        ],
        'traps': [
            {'id': t.id, 'x': t.x, 'y': t.y, 'radius': t.radius,
             'description': t.description, 'triggered': t.triggered}
            for t in scene_traps_list
        ],
    }

def _handle_dm_command(cmd):
    global current_turn_idx, enemies, active_campaign, active_zone_id
    t = cmd.get('type')

    if t == '_request_state':
        dm_server.broadcast_state(_get_dm_state())
        return

    elif t == 'switch_scene':
        idx = next((i for i, s in enumerate(scenes) if s[0] == cmd.get('scene_id')), None)
        if idx is not None and idx != current_scene_idx:
            _ws_from_sid = scene_id()
            switch_scene(idx)
            if cmd.get('from_marker'):
                _ws_dest = scene_id()
                if (_ws_dest and _ws_from_sid
                        and _ws_dest != _ws_from_sid
                        and _ws_dest != start_scene_id):
                    if not any(m.to_scene_id == _ws_from_sid for m in scene_markers):
                        _ws_rx, _ws_ry = _return_marker_pos()
                        _ws_name = next((s[1] for s in scenes if s[0] == _ws_from_sid), '???')
                        _tm = SceneMarker(None, _ws_rx, _ws_ry, _ws_from_sid, _ws_name)
                        scene_markers.append(_tm)
                        _add_transient_marker(_tm)
            dm_server.broadcast_state(_get_dm_state())

    elif t == 'move_marker':
        mid      = cmd.get('marker_id')   # None for transient markers
        to_sid   = cmd.get('to_scene_id')
        nx, ny   = float(cmd.get('x', 0)), float(cmd.get('y', 0))
        mk = next((m for m in scene_markers if m.to_scene_id == to_sid), None)
        if mk:
            mk.x, mk.y = nx, ny
            if mk.id is not None:
                db.update_scene_marker_pos(mk.id, nx, ny)
            dm_server.broadcast_state(_get_dm_state())  # confirm new position immediately

    elif t == 'move_entity':
        pool = enemies if cmd.get('is_enemy') else characters
        for ent in pool:
            if ent.id == cmd.get('entity_id'):
                ent.x, ent.y = float(cmd['x']), float(cmd['y'])
                if cmd.get('is_enemy'):
                    db.update_enemy_position(ent.id, ent.x, ent.y)
                else:
                    db.update_character_position(ent.id, ent.x, ent.y)
                break

    elif t == 'set_hp':
        pool = enemies if cmd.get('is_enemy') else characters
        for ent in pool:
            if ent.id == cmd.get('entity_id'):
                ent.hp = max(0, min(ent.max_hp, int(cmd.get('hp', ent.hp))))
                if cmd.get('is_enemy'):
                    db.update_enemy_hp(ent.id, ent.hp)
                else:
                    db.update_character_hp(ent.id, ent.hp)
                break
        dm_server.broadcast_state(_get_dm_state())

    elif t == 'group_hp':
        amount    = max(0, int(cmd.get('amount', 0)))
        is_damage = bool(cmd.get('is_damage', True))
        for tgt in cmd.get('targets', []):
            pool = enemies if tgt.get('is_enemy') else characters
            for ent in pool:
                if ent.id == tgt.get('entity_id'):
                    if is_damage: ent.hp = max(0, ent.hp - amount)
                    else:         ent.hp = min(ent.max_hp, ent.hp + amount)
                    if ent.is_enemy: db.update_enemy_hp(ent.id, ent.hp)
                    else:            db.update_character_hp(ent.id, ent.hp)
                    break
        dm_server.broadcast_state(_get_dm_state())

    elif t == 'delete_enemy':
        for ent in enemies:
            if ent.id == cmd.get('entity_id'):
                db.delete_enemy(ent.id)
                enemies.remove(ent)
                rebuild_initiative()
                if target_entity is ent:
                    target_entity = None
                break

    elif t == 'set_initiative':
        pool = enemies if cmd.get('is_enemy') else characters
        for ent in pool:
            if ent.id == cmd.get('entity_id'):
                ent.initiative = int(cmd.get('value', 0))
                if cmd.get('is_enemy'):
                    db.update_enemy_initiative(ent.id, ent.initiative)
                else:
                    db.update_character_initiative(ent.id, ent.initiative)
                rebuild_initiative()
                break

    elif t == 'roll_initiative':
        print('[Initiative Roll]')
        for ent in enemies:
            roll = random.randint(1, 20)
            ent.initiative = roll
            db.update_enemy_initiative(ent.id, ent.initiative)
            print(f'  {ent.name}: d20({roll}) = {ent.initiative}')
        for ent in characters:
            roll  = random.randint(1, 20)
            bonus = getattr(ent, 'init_bonus', 0)
            ent.initiative = roll + bonus
            db.update_character_initiative(ent.id, ent.initiative)
            bonus_str = f' + bonus({bonus:+d})' if bonus else ''
            print(f'  {ent.name}: d20({roll}){bonus_str} = {ent.initiative}')
        rebuild_initiative()
        dm_server.broadcast_state(_get_dm_state())

    elif t == 'next_turn':
        if initiative_order:
            for _ in range(len(initiative_order)):
                current_turn_idx = (current_turn_idx + 1) % len(initiative_order)
                if not _is_fog_hidden(initiative_order[current_turn_idx]):
                    break
        dm_server.broadcast_state(_get_dm_state())

    elif t == 'prev_turn':
        if initiative_order:
            for _ in range(len(initiative_order)):
                current_turn_idx = (current_turn_idx - 1) % len(initiative_order)
                if not _is_fog_hidden(initiative_order[current_turn_idx]):
                    break
        dm_server.broadcast_state(_get_dm_state())

    elif t == 'toggle_fog':
        new_fog = not toolbar.active.get('fog_on', False)
        toolbar.active['fog_on'] = new_fog
        fog.edit = new_fog
        _fog_radius = db.get_scene_fog(scene_id())[1]
        db.save_scene_fog(scene_id(), new_fog, _fog_radius)

    elif t == 'move_party':
        party = [c for c in characters if not getattr(c, 'is_npc', False)]
        if party:
            tx, ty = float(cmd.get('x', 0)), float(cmd.get('y', 0))
            cx = sum(c.x for c in party) / len(party)
            cy = sum(c.y for c in party) / len(party)
            dx, dy = tx - cx, ty - cy
            for ch in party:
                ch.x += dx
                ch.y += dy
                db.update_character_position(ch.id, ch.x, ch.y)

    elif t == 'move_camera':
        global camera_x, camera_y
        camera_x = max(0.0, float(cmd.get('x', camera_x)))
        camera_y = max(0.0, float(cmd.get('y', camera_y)))
        for layer in layers:
            layer.x = -camera_x
            layer.y = -camera_y
            layer.clamp(WIDTH, HEIGHT - TOOLBAR_HEIGHT)
        if layers:
            camera_x, camera_y = -layers[0].x, -layers[0].y
        db.update_current_location(int(camera_x), int(camera_y))
        _s = current_scene()
        if _s:
            db.update_scene_camera(_s[0], int(camera_x), int(camera_y))
        dm_server.broadcast_state(_get_dm_state())

    elif t == 'toggle_condition':
        eid      = cmd.get('entity_id')
        is_enemy = cmd.get('is_enemy', False)
        code     = cmd.get('code', '')
        elist    = enemies if is_enemy else characters
        ent      = next((e for e in elist if e.id == eid), None)
        if ent and code:
            if code in ent.conditions:
                ent.conditions.discard(code)
            else:
                ent.conditions.add(code)
            cs = ent.conditions_str()
            if is_enemy:
                db.update_enemy_conditions(ent.id, cs)
            else:
                db.update_character_conditions(ent.id, cs)

    elif t == 'reload_sound_zones':
        reload_sound_zones()
        active_zone_id = None   # force re-detection so new zone plays immediately
        check_zone_detection()

    elif t == 'preview_track':
        url = cmd.get('url', '').strip()
        if url:
            import types as _types
            _zone_play(_types.SimpleNamespace(track=url))

    elif t == 'stop_preview':
        _zone_stop()

    elif t == 'set_music_enabled':
        _apply_music_enabled(bool(cmd.get('enabled', True)))
        toolbar.active['music_enabled'] = music_enabled

    elif t == 'switch_campaign':
        name = cmd.get('name', '')
        if name and name in campaigns_mod.list_campaigns() and name != active_campaign:
            switch_campaign(name)
            return   # switch_campaign already broadcasts

    elif t == 'create_campaign':
        name = cmd.get('name', '')
        if name and campaigns_mod.is_valid_name(name):
            campaigns_mod.create(name)
            switch_campaign(name)
            return

    elif t == 'delete_campaign':
        name = cmd.get('name', '')
        if name and name != active_campaign:
            campaigns_mod.delete(name)

    elif t == 'rename_campaign':
        old, new = cmd.get('old', ''), cmd.get('new', '')
        if old and new and campaigns_mod.is_valid_name(new):
            if campaigns_mod.rename(old, new):
                if old == active_campaign:
                    active_campaign = new
                    db.set_db_path(campaigns_mod.db_path(new))  # release old handle first
                    pygame.display.set_caption(f"RealmScape — {new}  |  GM Panel: {_GM_URL}")
                campaigns_mod.remove_dir(old)  # now safe — no open handles to old folder

    elif t == 'import_campaign':
        name     = cmd.get('name', '')
        zip_path = cmd.get('zip_path', '')
        try:
            if name and name == active_campaign:
                # Overwriting the campaign currently in use — detach from it
                # first (flushes + releases the DB handle), replace its
                # folder on disk, then switch back into the fresh import.
                switch_campaign('default')
                campaigns_mod.import_zip(name, zip_path)
                switch_campaign(name)
                return   # switch_campaign already broadcasts
            elif name:
                campaigns_mod.import_zip(name, zip_path)
        except Exception as exc:
            print(f'[Campaign import error] {exc}')
        finally:
            if zip_path:
                shutil.rmtree(os.path.dirname(zip_path), ignore_errors=True)



    dm_server.broadcast_state(_get_dm_state())

# ── Toolbar & UI ──────────────────────────────────────────────────────────────
toolbar          = Toolbar(tb_font)
toolbar.zoom_level = current_zoom
init_panel       = InitiativePanel(font, small_font)
fog              = FogOfWar()
if scenes:
    _apply_fog_settings(*db.get_scene_fog(scene_id()))
toolbar.active['music_enabled'] = db.get_music_enabled()
toolbar.active['show_grid']     = db.get_scene_grid(scene_id()) if scenes else True
if not db.has_scene_snapshot(scene_id()) if scenes else True:
    toolbar.disabled_btns.add('scene_revert')

_INIT_MSG_WELCOME = (
    "Thank you so much for trying my software.  I hope you enjoy it!\n\n"
    "                                        — Mike"
)

def _init_msg_path(campaign=None):
    name = campaign or active_campaign
    return os.path.join(campaigns_mod.campaign_path(name), 'initial_message.txt')

def _ensure_init_msg_file(campaign=None):
    path = _init_msg_path(campaign)
    if not os.path.isfile(path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(_INIT_MSG_WELCOME + '\n')
        except Exception:
            pass

def _load_init_msg(campaign=None):
    _ensure_init_msg_file(campaign)
    path = _init_msg_path(campaign)
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read().strip()
        return text if text else None
    except Exception:
        return None

init_msg_popup      = None
_init_msg_pending   = db.get_hints_enabled()   # show after first map frame
build_mode_hint     = None                     # one-shot build-mode reminder

aoe_tool         = AoeTool()
measure_tool     = MeasureTool()
notes_panel      = NotesPanel(font, small_font)
notes_panel.set_text(db.get_notes(scene_id()))
context_menu      = None
hp_popup          = None
conditions_popup  = None
char_dialog       = None
enemy_dialog      = None
size_popup        = None
stat_block_panel  = None
target_entity     = None   # entity with targeting reticle
num_input_popup   = None   # NumberInputPopup for damage / heal
confirm_popup        = None   # ConfirmPopup for destructive actions
group_hp_popup       = None   # GroupHPPopup for batch damage/heal
scene_picker         = None   # ScenePickerPopup for dropping markers
new_scene_popup      = None   # NewSceneChoicePopup (blank vs generate)
dungeon_gen_dialog   = None   # DungeonGenDialog when open
_gen_queue: queue.Queue = queue.Queue()   # thread → main: generation result
_pending_gen_path: str = ''               # path of last generated PNG
dragged_marker       = None   # SceneMarker being repositioned
marker_drag_start    = None   # screen (x,y) where the marker drag began
_map_panning         = False  # True while left-drag panning the map
_pan_last_pos        = None   # previous mouse pos during a pan
campaign_dialog      = None   # CampaignDialog when open
zone_dialog          = None   # SoundZoneDialog when open
tta_browser          = None   # TabletopAudioBrowserDialog when open
lock_overlay         = None   # LockOverlay when session is locked


# ── Restore scene-specific character positions and centre camera on players ───
if scenes:
    _pos = db.load_character_positions(scene_id())
    _missing = []
    for _i, _ch in enumerate(characters):
        if _ch.id in _pos:
            _ch.x, _ch.y = _pos[_ch.id]
        else:
            _missing.append((_ch.id, _ch.x, _ch.y))
    if _missing:
        db.seed_character_positions(scene_id(), _missing)
if characters:
    _avg_x = sum(c.x for c in characters) / len(characters)
    _avg_y = sum(c.y for c in characters) / len(characters)
    camera_x = max(0.0, _avg_x - WIDTH  // 2)
    camera_y = max(0.0, _avg_y - (HEIGHT - TOOLBAR_HEIGHT) // 2)
    for layer in layers:
        layer.x = -camera_x
        layer.y = -camera_y
        layer.clamp(WIDTH, HEIGHT - TOOLBAR_HEIGHT)
    if layers:
        camera_x, camera_y = -layers[0].x, -layers[0].y

# ── Run-time state ────────────────────────────────────────────────────────────
speed         = 5
dragging      = False
dragged_ent   = None
renaming_char   = None
new_name        = ''
renaming_scene  = False
scene_new_name  = ''
undo_stack    = []        # list of (entity, old_x, old_y)
MAX_UNDO      = 20

# Touch tracking
touch_fingers = {}   # finger_id -> {start, last, start_time, moved, fired_lp}

# ── Scene switching ───────────────────────────────────────────────────────────

def _save_current_scene_state():
    s = current_scene()
    if not s:
        return
    db.update_scene_camera(s[0], int(camera_x), int(camera_y))
    # When build mode is active toolbar fog_on is forced False; save the real pre-build value instead
    real_fog = _pre_build_fog if (build_mode and _pre_build_fog is not None) else toolbar.active.get('fog_on', True)
    db.save_scene_fog(s[0], real_fog, _current_fog_radius_cells())
    db.save_scene_zoom(s[0], current_zoom)
    db.save_scene_grid(s[0], toolbar.active.get('show_grid', True))
    db.save_notes(s[0], notes_panel.text)
    db.save_character_positions(s[0], [(c.id, c.x, c.y) for c in characters])

def _accept_generated_scene():
    """Import the accepted dungeon PNG as a new scene and switch to it."""
    path  = _pending_gen_path
    sname = dungeon_gen_dialog.result.get('scene_name', 'Generated Dungeon') \
            if dungeon_gen_dialog and dungeon_gen_dialog.result else 'Generated Dungeon'
    rel    = campaigns_mod.make_relative_path(path)
    new_id = db.add_scene(sname, rel, int(camera_x), int(camera_y))
    scenes.append((new_id, sname, rel, int(camera_x), int(camera_y)))
    db.seed_character_positions(new_id, [(ch.id, ch.x, ch.y) for ch in characters])
    switch_scene(len(scenes) - 1)

def _create_blank_scene():
    """Add a blank scene to DB and switch to it (original + button behaviour)."""
    new_id = db.add_scene(f'Scene {len(scenes)+1}', '', int(camera_x), int(camera_y))
    scenes.append((new_id, f'Scene {len(scenes)+1}', '', int(camera_x), int(camera_y)))
    db.seed_character_positions(new_id, [(ch.id, ch.x, ch.y) for ch in characters])
    switch_scene(len(scenes) - 1)

def _run_dungeon_gen(params: dict, out_path: str):
    """Background thread: generate dungeon, render to PNG, push result to queue."""
    try:
        from dungeongen.layout.generator import DungeonGenerator
        from dungeongen.layout.params import (GenerationParams, DungeonSize,
                                              DungeonArchetype, SymmetryType)
        from dungeongen.webview.adapter import convert_dungeon

        size_map = {
            'TINY': DungeonSize.TINY, 'SMALL': DungeonSize.SMALL,
            'MEDIUM': DungeonSize.MEDIUM, 'LARGE': DungeonSize.LARGE,
            'XLARGE': DungeonSize.XLARGE,
        }
        arch_map = {
            'CLASSIC': DungeonArchetype.CLASSIC, 'WARREN': DungeonArchetype.WARREN,
            'TEMPLE': DungeonArchetype.TEMPLE,   'CRYPT': DungeonArchetype.CRYPT,
            'CAVERN': DungeonArchetype.CAVERN,   'FORTRESS': DungeonArchetype.FORTRESS,
            'LAIR': DungeonArchetype.LAIR,
        }
        sym_map = {
            'NONE': SymmetryType.NONE,       'BILATERAL': SymmetryType.BILATERAL,
            'RADIAL_2': SymmetryType.RADIAL_2, 'RADIAL_4': SymmetryType.RADIAL_4,
            'PARTIAL': SymmetryType.PARTIAL,
        }
        gen_params = GenerationParams(
            size                    = size_map[params['size']],
            archetype               = arch_map[params['archetype']],
            symmetry                = sym_map[params['symmetry']],
            density                 = params['density'],
            room_size_bias          = params['room_size_bias'],
            round_room_chance       = params['round_room_chance'],
            hall_chance             = params['hall_chance'],
            linearity               = params['linearity'],
            loop_factor             = params['loop_factor'],
            winding                 = params['winding'],
            extra_room_connections  = params['extra_room_connections'],
            extra_passage_junctions = params['extra_passage_junctions'],
            stair_frequency         = params['stair_frequency'],
            symmetry_break          = params['symmetry_break'],
            water_enabled           = params['water_enabled'],
            water_threshold         = params['water_threshold'],
            passage_width           = params['passage_width'],
            levels                  = params['levels'],
        )
        dungeon = DungeonGenerator(gen_params).generate(seed=params.get('seed'))
        water_depth = 0.4 if params['water_enabled'] else 0.0
        map_obj = convert_dungeon(dungeon, water_depth=water_depth)
        map_obj.render_to_png(out_path, width=2048, height=2048)
        _gen_queue.put({'status': 'ok', 'path': out_path,
                        'scene_name': params['scene_name'], 'params': params})
    except Exception as exc:
        _gen_queue.put({'status': 'error', 'error': str(exc)})

def _ensure_turn_entity_visible():
    """Pan the camera so the current-turn entity is on screen if it isn't already."""
    global camera_x, camera_y
    if not initiative_order:
        return
    ent = initiative_order[current_turn_idx]
    map_h = HEIGHT - TOOLBAR_HEIGHT
    sx = ent.x - camera_x
    sy = ent.y - camera_y
    margin = GRID_SIZE * 2
    if 0 <= sx <= WIDTH and 0 <= sy <= map_h:
        return  # already visible
    camera_x = max(0.0, ent.x - WIDTH  / 2)
    camera_y = max(0.0, ent.y - map_h  / 2)
    for layer in layers:
        layer.update(camera_x, camera_y)
        layer.clamp(WIDTH, map_h)
    if layers:
        camera_x, camera_y = -layers[0].x, -layers[0].y
    db.update_scene_camera(current_scene()[0], int(camera_x), int(camera_y))

def _load_current_scene():
    """Reload all scene state from DB for the current current_scene_idx."""
    global camera_x, camera_y, layers, fog, current_zoom, _pre_build_fog, group_hp_popup
    group_hp_popup = None
    if not scenes:
        return
    s = current_scene()
    camera_x, camera_y = float(s[3]), float(s[4])
    current_zoom = db.get_scene_zoom(s[0])
    toolbar.zoom_level = current_zoom
    layers = rebuild_layers(s[2], WIDTH, HEIGHT, current_zoom)
    for layer in layers:
        layer.update(camera_x, camera_y)
        layer.clamp(WIDTH, HEIGHT - TOOLBAR_HEIGHT)
    if layers:
        camera_x, camera_y = -layers[0].x, -layers[0].y
    dm_server.set_bg_path(s[2] or '')
    fog = FogOfWar()
    _new_fog_on, _new_fog_radius = db.get_scene_fog(s[0])
    if build_mode:
        # Keep fog forced off; update saved state to reflect the new scene
        _pre_build_fog = _new_fog_on
        _apply_fog_settings(False, _new_fog_radius)
    else:
        _apply_fog_settings(_new_fog_on, _new_fog_radius)
    toolbar.active['show_grid'] = db.get_scene_grid(s[0])
    notes_panel.set_text(db.get_notes(s[0]))
    reload_enemies()
    reload_markers()
    reload_scene_npcs()
    # Restore per-scene character positions; seed defaults for any missing entries
    positions = db.load_character_positions(s[0])
    missing = []
    cx_center = camera_x + WIDTH // 2
    cy_center = camera_y + (HEIGHT - TOOLBAR_HEIGHT) // 2
    for i, ch in enumerate(characters):
        if ch.id in positions:
            ch.x, ch.y = positions[ch.id]
        else:
            # Spread characters horizontally across scene center
            offset = (i - len(characters) / 2) * (GRID_SIZE * 2)
            ch.x = cx_center + offset
            ch.y = cy_center
            missing.append((ch.id, ch.x, ch.y))
    if missing:
        db.seed_character_positions(s[0], missing)
    rebuild_initiative()
    _update_snapshot_btn()
    _ensure_turn_entity_visible()

def switch_scene(new_idx):
    global current_scene_idx, active_zone_id
    if not scenes:
        return
    _save_current_scene_state()
    current_scene_idx = new_idx % len(scenes)
    _load_current_scene()
    reload_sound_zones()
    reload_hidden_items()
    reload_scene_traps()
    _item_cooldowns.clear()
    active_zone_id = None
    _zone_stop()

def switch_campaign(name: str):
    """Save current state, swap the DB, and reload everything from the new campaign."""
    global active_campaign, characters, enemies, scenes, scene_markers
    global current_scene_idx, start_scene_id, current_zoom, bg_path
    global camera_x, camera_y, layers, fog, initiative_order, current_turn_idx
    global target_entity, init_msg_popup, _init_msg_pending
    target_entity = None
    _transient_markers.clear()

    _save_current_scene_state()

    campaigns_mod.set_active(name)
    campaigns_mod.touch_last_loaded(name)
    active_campaign = name
    db.set_db_path(campaigns_mod.db_path(name))
    pin_manager.set_active_campaign(name)
    db.init_db()
    db.cleanup_orphaned_records()

    scenes = db.get_all_scenes()
    start_scene_id = db.get_start_scene_id()
    current_scene_idx = next(
        (i for i, s in enumerate(scenes) if s[0] == start_scene_id), 0
    ) if scenes else 0

    characters[:] = [load_entity(r, False) for r in db.load_global_characters()]
    reload_enemies()
    toolbar.active['music_enabled'] = db.get_music_enabled()

    _s = scenes[current_scene_idx] if scenes else None
    bg_path = (_s[2] if _s and _s[2] else '')
    camera_x, camera_y = (float(_s[3]), float(_s[4])) if _s else (0.0, 0.0)
    current_zoom = db.get_scene_zoom(scene_id()) if scenes else 1.0
    toolbar.zoom_level = current_zoom
    layers[:] = rebuild_layers(bg_path, WIDTH, HEIGHT, current_zoom)
    for layer in layers:
        layer.x = -camera_x
        layer.y = -camera_y
        layer.clamp(WIDTH, HEIGHT - TOOLBAR_HEIGHT)
    if layers:
        camera_x, camera_y = -layers[0].x, -layers[0].y

    fog = FogOfWar()
    if _s:
        _apply_fog_settings(*db.get_scene_fog(_s[0]))
        _pos = db.load_character_positions(_s[0])
        _missing = []
        for ch in characters:
            if ch.id in _pos:
                ch.x, ch.y = _pos[ch.id]
            else:
                _missing.append((ch.id, ch.x, ch.y))
        if _missing:
            db.seed_character_positions(_s[0], _missing)
        if characters:
            _ax = sum(c.x for c in characters) / len(characters)
            _ay = sum(c.y for c in characters) / len(characters)
            camera_x = max(0.0, _ax - WIDTH // 2)
            camera_y = max(0.0, _ay - (HEIGHT - TOOLBAR_HEIGHT) // 2)
            for layer in layers:
                layer.x = -camera_x
                layer.y = -camera_y
                layer.clamp(WIDTH, HEIGHT - TOOLBAR_HEIGHT)
            if layers:
                camera_x, camera_y = -layers[0].x, -layers[0].y

    reload_markers()
    reload_sound_zones()
    reload_hidden_items()
    reload_scene_traps()
    _item_cooldowns.clear()
    rebuild_initiative()
    toolbar.active['music_enabled'] = music_enabled
    _zone_stop()
    active_zone_id = None
    dm_server.set_bg_path(bg_path)
    pygame.display.set_caption(f"RealmScape — {name}  |  GM Panel: {_GM_URL}")
    if db.get_hints_enabled():
        _init_msg_pending = True
        init_msg_popup    = None

    # A campaign with zero scenes has nowhere to persist a dropped background
    # image or anything else scene-specific — set_bg_image() and friends
    # silently no-op without a current scene, so anything added before the
    # first scene exists would vanish the moment layers get rebuilt (e.g. by
    # the zoom slider). Guarantee every loaded campaign has at least one.
    if not scenes:
        _create_blank_scene()

def set_bg_image(path):
    global layers, camera_x, camera_y
    layers = rebuild_layers(path, WIDTH, HEIGHT, current_zoom)
    layers[0].update(camera_x, camera_y)
    layers[0].clamp(WIDTH, HEIGHT - TOOLBAR_HEIGHT)
    camera_x, camera_y = -layers[0].x, -layers[0].y
    db.update_current_location(int(camera_x), int(camera_y))
    if current_scene():
        rel = campaigns_mod.import_asset(path, active_campaign)
        db.update_scene_image(scene_id(), rel)
        s = scenes[current_scene_idx]
        scenes[current_scene_idx] = (s[0], s[1], rel, s[3], s[4])

# ── Targeting reticle ─────────────────────────────────────────────────────────

def draw_targeting_reticle(surface, ent, cam_x, cam_y):
    cx  = int(ent.x - cam_x)
    cy  = int(ent.y - cam_y + TOOLBAR_HEIGHT)
    t   = pygame.time.get_ticks()
    r   = ent.size + 10 + int(math.sin(t * 0.004) * 4)   # pulsing radius
    col = (255, 60, 60) if ent.is_enemy else (255, 210, 40)
    ang_off = (t / 800.0) * 45   # slow rotation (45 °/s)
    gap = 22                      # degrees cut from each arc segment

    # 4 rotating arc segments
    steps = 18
    for i in range(4):
        a_start = i * 90 + gap * 0.5 + ang_off
        a_end   = (i + 1) * 90 - gap * 0.5 + ang_off
        pts = []
        for s in range(steps + 1):
            a   = math.radians(a_start + (a_end - a_start) * s / steps)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        for p1, p2 in zip(pts, pts[1:]):
            pygame.draw.line(surface, col,
                             (int(p1[0]), int(p1[1])),
                             (int(p2[0]), int(p2[1])), 2)

    # Tick marks at cardinal points
    for i in range(4):
        a  = math.radians(i * 90 + ang_off)
        x1 = cx + int((r + 5)  * math.cos(a))
        y1 = cy + int((r + 5)  * math.sin(a))
        x2 = cx + int((r + 13) * math.cos(a))
        y2 = cy + int((r + 13) * math.sin(a))
        pygame.draw.line(surface, col, (x1, y1), (x2, y2), 2)

# ── Context menu builder ──────────────────────────────────────────────────────

def open_context_menu(screen_x, screen_y):
    global context_menu, target_entity
    wx = screen_x + camera_x
    wy = screen_y + camera_y - TOOLBAR_HEIGHT
    # Find entity under cursor
    target = None
    for ent in enemies + characters:
        if ent.is_clicked((screen_x, screen_y - TOOLBAR_HEIGHT), camera_x, camera_y):
            target = ent
            break
    if target:
        target_entity = target
        items = [
            ('damage',     'Damage...'),
            ('heal',       'Heal...'),
            (None,         '---'),
            ('rename',     'Rename'),
            ('set_hp',     'Set HP'),
            ('conditions', 'Conditions'),
            ('set_init',   'Set Initiative'),
            (None,         '---'),
            ('clear_reticle', 'Clear Reticle'),
        ]
        # Scene-assignment toggle — only meaningful when scenes exist
        if target.is_enemy and scenes:
            items.append((None, '---'))
            if target.scene_id == 0:
                items.append(('pin_to_scene',
                               f'Pin to "{scene_name()}"'))
            else:
                items.append(('make_global', 'Make Global (all scenes)'))
        if not target.is_enemy:
            items.insert(0, ('char_settings', 'Character Settings'))
        else:
            items.insert(0, ('enemy_settings', 'Enemy Settings'))
        items += [(None, '---'), ('set_size', 'Set Size'),
                  ('stat_block', 'Stat Block'), ('remove', 'Remove')]
        if not target.is_enemy and getattr(target, 'is_npc', False):
            items.append(('remove_from_scene', 'Remove from current scene'))
    else:
        # Check if cursor is over an existing hidden item or trap indicator
        hit_item = next((it for it in hidden_items
                         if not it.found and
                         math.hypot(wx - it.x, wy - it.y) <= max(it.radius * 0.15, 8)), None)
        hit_trap = next((tr for tr in scene_traps_list
                         if math.hypot(wx - tr.x, wy - tr.y) <= max(tr.radius * 0.15, 8)), None)
        if hit_item:
            items = [
                ('edit_item',   'Edit Hidden Item'),
                ('remove_item', 'Remove Hidden Item'),
            ]
            context_menu = ContextMenu((screen_x, screen_y), items, font)
            context_menu._target   = None
            context_menu._wx       = wx
            context_menu._wy       = wy
            context_menu._hit_item = hit_item
            context_menu._hit_trap = None
            context_menu.reposition(WIDTH, HEIGHT)
            sound_fx.play('menu_open')
            return
        elif hit_trap:
            items = [
                ('edit_trap',   'Edit Trap'),
            ]
            if hit_trap.triggered:
                items.append(('reset_trap', 'Reset Trap'))
            items.append(('remove_trap', 'Remove Trap'))
            context_menu = ContextMenu((screen_x, screen_y), items, font)
            context_menu._target   = None
            context_menu._wx       = wx
            context_menu._wy       = wy
            context_menu._hit_item = None
            context_menu._hit_trap = hit_trap
            context_menu.reposition(WIDTH, HEIGHT)
            sound_fx.play('menu_open')
            return
        else:
            items = [
                ('add_enemy',        'Add Enemy here'),
                ('add_character',    'Add Character here'),
                ('clear_aoe',        'Clear AoE templates'),
                (None,               '---'),
                ('place_item',       'Place Hidden Item here'),
                ('place_trap',       'Place Trap here'),
                (None,               '---'),
                ('drop_scene_marker','Drop Scene Marker'),
                (None,               '---'),
                ('group_damage',     'Group Damage...'),
                ('group_heal',       'Group Heal...'),
            ]
    context_menu = ContextMenu((screen_x, screen_y), items, font)
    context_menu._target = target
    context_menu._wx     = wx
    context_menu._wy     = wy
    context_menu.reposition(WIDTH, HEIGHT)
    sound_fx.play('menu_open')

# ── Apply campaign dialog result ──────────────────────────────────────────────

def _apply_zone_dialog(res):
    global zone_dialog, zone_dialog_is_default, tta_browser
    if res == 'browse_tta':
        # Open the in-game TTA track browser; keep zone_dialog open behind it
        def _tta_preview(url):
            threading.Thread(
                target=_download_and_signal,
                args=(url, _TTA_REFERER),
                daemon=True, name='tta-preview').start()
        tta_browser = TabletopAudioBrowserDialog(font, WIDTH, HEIGHT,
                                                 stop_audio=_zone_stop,
                                                 play_audio=_tta_preview)
        if _tta_songlist is None:
            threading.Thread(target=_load_tta_songlist, daemon=True, name='tta-load').start()
        return
    if res == 'close':
        zone_dialog = None
        zone_dialog_is_default = False
    elif res == 'confirm' and zone_dialog and zone_dialog.result:
        global build_mode_hint
        d = zone_dialog.result
        is_def = zone_dialog_is_default
        zone_dialog = None
        zone_dialog_is_default = False
        sid = scene_id()
        if is_def:
            db.set_default_zone(sid, d['name'], d['track'], d['color'])
        else:
            db.add_sound_zone(d['name'], d['x'], d['y'], d['w'], d['h'],
                              d['track'], d['color'], sid)
            if not build_mode:
                build_mode_hint = HintPopup(font, small_font, WIDTH, HEIGHT,
                    "Sound Zone created — but its boundary won't be visible yet!\n\n"
                    "Sound zone outlines only appear on the screen when"
                    "Build Mode is active.\n\n"
                    "Enable it now via Map > Build Mode.",
                    title='Important Message')
        reload_sound_zones()
        dm_server.broadcast_state(_get_dm_state())


def _build_hints_map() -> dict:
    """Read hints_enabled from every campaign's DB for the Campaign dialog."""
    result = {}
    for name in campaigns_mod.list_campaigns():
        if name == active_campaign:
            result[name] = db.get_hints_enabled()
        else:
            result[name] = db.get_hints_enabled_for(campaigns_mod.db_path(name))
    return result

def _campaign_dialog_refresh():
    """Re-open the campaign dialog with fresh per-campaign hints values."""
    global campaign_dialog
    campaign_dialog = CampaignDialog(
        campaigns_mod.list_campaigns(), active_campaign, tb_font, WIDTH, HEIGHT,
        hints_map=_build_hints_map()
    )

def _apply_campaign_dialog(action):
    global campaign_dialog, active_campaign
    if not action:
        return
    kind = action.get('action')
    name = action.get('name', '')
    if kind == 'close':
        campaign_dialog = None
    elif kind == 'toggle_hints':
        target   = action.get('campaign', active_campaign)
        enabled  = action.get('enabled', True)
        if target == active_campaign:
            db.set_hints_enabled(enabled)
        else:
            db.set_hints_enabled_for(campaigns_mod.db_path(target), enabled)
    elif kind == 'switch' and name:
        campaign_dialog = None
        switch_campaign(name)
        dm_server.broadcast_state(_get_dm_state())
    elif kind == 'create' and name:
        if campaigns_mod.is_valid_name(name):
            campaigns_mod.create(name)
            campaign_dialog = None
            switch_campaign(name)
            dm_server.broadcast_state(_get_dm_state())
    elif kind == 'delete' and name:
        if name != active_campaign:
            campaigns_mod.delete(name)
            _campaign_dialog_refresh()

    elif kind == 'rename':
        old, new = action.get('old', ''), action.get('new', '')
        if old and new and campaigns_mod.is_valid_name(new):
            if campaigns_mod.rename(old, new):
                if old == active_campaign:
                    active_campaign = new
                    db.set_db_path(campaigns_mod.db_path(new))  # release old handle first
                    pygame.display.set_caption(f"RealmScape — {new}  |  GM Panel: {_GM_URL}")
                campaigns_mod.remove_dir(old)  # now safe — no open handles to old folder
                _campaign_dialog_refresh()
                dm_server.broadcast_state(_get_dm_state())

# ── Apply character dialog result ─────────────────────────────────────────────

def apply_char_dialog(result):
    """Create a new player character (create mode) or update an existing one (edit mode)."""
    global char_dialog, characters
    if char_dialog is None:
        return
    sound_fx.play('confirm')
    img_path = result.get('image_path', '')
    rel_img  = campaigns_mod.import_asset(img_path, active_campaign) if img_path else ''
    if char_dialog.mode == 'create':
        # Spawn near existing party members; fall back to screen centre
        party = [c for c in characters if not getattr(c, 'is_npc', False)]
        if party:
            cx = sum(c.x for c in party) / len(party)
            cy = sum(c.y for c in party) / len(party)
            wx, wy = int(cx) + GRID_SIZE * 2, int(cy)
        else:
            wx = int(getattr(char_dialog, '_wx', camera_x + WIDTH  // 2))
            wy = int(getattr(char_dialog, '_wy', camera_y + HEIGHT // 2))
        is_npc   = result.get('is_npc', False)
        npc_scene = scene_id() if is_npc else 0
        new_id = db.insert_character(result['name'], wx, wy,
                                     result['color'], result['size'],
                                     result['max_hp'], result['max_hp'],
                                     is_npc=is_npc, scene_id=npc_scene)
        ent = Character(wx, wy, pygame.Color(result['color']),
                        result['size'], result['name'], id=new_id, is_enemy=False)
        ent.hp = ent.max_hp = result['max_hp']
        ent.is_npc   = is_npc
        ent.scene_id = npc_scene
        if img_path:
            ent.set_image(img_path)
            ent.image_path = rel_img
            db.update_character_image_path(new_id, rel_img)
        characters.append(ent)
        # NPCs only need a position for their own scene; party members seed all scenes
        if is_npc:
            db.seed_character_positions(npc_scene, [(new_id, wx, wy)])
        else:
            for sc_id in db.get_all_scene_ids():
                db.seed_character_positions(sc_id, [(new_id, wx, wy)])
        rebuild_initiative()
    else:
        ent = char_dialog.entity
        was_npc    = getattr(ent, 'is_npc', False)
        ent.name       = result['name']
        ent.color      = pygame.Color(result['color'])
        ent.size       = result['size']
        ent.max_hp     = result['max_hp']
        ent.init_bonus = result.get('init_bonus', 0)
        ent.is_npc     = result.get('is_npc', False)
        db.update_character_name(ent.id, result['name'])
        db.update_character_color(ent.id, result['color'])
        db.update_character_size(ent.id, result['size'])
        db.update_character_max_hp(ent.id, result['max_hp'])
        db.update_character_init_bonus(ent.id, ent.init_bonus)
        db.update_character_is_npc(ent.id, ent.is_npc)
        if was_npc and not ent.is_npc:
            # Promoted to full party member — make global and seed all scenes
            ent.scene_id = 0
            db.update_character_scene_id(ent.id, 0)
            for sc_id in db.get_all_scene_ids():
                db.seed_character_positions(sc_id, [(ent.id, ent.x, ent.y)])
        if img_path != getattr(ent, 'image_path', ''):
            ent.set_image(img_path) if img_path else None
            ent.image_path = rel_img
            db.update_character_image_path(ent.id, rel_img)
    char_dialog = None

def apply_enemy_dialog(result):
    global enemy_dialog
    if enemy_dialog is None:
        return
    sound_fx.play('confirm')
    ent      = enemy_dialog.entity
    img_path = result.get('image_path', '')
    rel_img  = campaigns_mod.import_asset(img_path, active_campaign) if img_path else ''
    ent.name   = result['name']
    ent.color  = pygame.Color(result['color'])
    ent.size   = result['size']
    ent.max_hp = result['max_hp']
    db.update_enemy_name(ent.id, result['name'])
    db.update_enemy_color(ent.id, result['color'])
    db.update_enemy_size(ent.id, result['size'])
    db.update_enemy_max_hp(ent.id, result['max_hp'])
    if img_path != getattr(ent, 'image_path', ''):
        ent.set_image(img_path) if img_path else None
        ent.image_path = rel_img
        db.update_enemy_image_path(ent.id, rel_img)
    enemy_dialog = None

# ── Zoom helper ───────────────────────────────────────────────────────────────

def _apply_zoom(new_zoom, save=True):
    global current_zoom, camera_x, camera_y
    current_zoom = max(0.1, min(5.0, round(new_zoom, 2)))
    toolbar.zoom_level = current_zoom
    s = current_scene()
    bg_path = s[2] if s else ''
    layers[:] = rebuild_layers(bg_path, WIDTH, HEIGHT, current_zoom)
    if layers:
        layers[0].update(camera_x, camera_y)
        layers[0].clamp(WIDTH, HEIGHT - TOOLBAR_HEIGHT)
        # Re-clamping the new (differently-sized) canvas can move the layer
        # to a position that no longer matches camera_x/camera_y — resync,
        # or every token/fog draw (which uses camera_x/camera_y directly)
        # would drift out of alignment with the repositioned background.
        camera_x, camera_y = -layers[0].x, -layers[0].y
    if save and s:
        db.save_scene_zoom(s[0], current_zoom)

# ── Scene snapshot / revert ───────────────────────────────────────────────────

def _build_scene_snapshot(sid: int) -> dict:
    snapshot = {'scene_id': sid, 'enemies': [], 'npcs': [], 'items': [], 'traps': [], 'markers': []}
    for eid, name, x, y, color, size, img, hp, max_hp, cond, init in db.get_scene_enemies_full(sid):
        snapshot['enemies'].append({
            'name': name, 'x': x, 'y': y, 'color': color, 'size': size,
            'image_path': img, 'hp': hp, 'max_hp': max_hp,
            'conditions': cond, 'initiative': init,
            'stat_block': db.get_stat_block('enemy', eid),
        })
    for cid, name, x, y, color, size, img, hp, max_hp, cond, init, init_bonus, is_npc in db.get_scene_npcs_full(sid):
        snapshot['npcs'].append({
            'name': name, 'x': x, 'y': y, 'color': color, 'size': size,
            'image_path': img, 'hp': hp, 'max_hp': max_hp,
            'conditions': cond, 'initiative': init, 'init_bonus': init_bonus,
            'is_npc': bool(is_npc), 'stat_block': db.get_stat_block('character', cid),
        })
    for row in db.get_scene_items(sid):  # id, scene_id, x, y, radius, dc, description, found
        snapshot['items'].append({'x': row[2], 'y': row[3], 'radius': row[4],
                                  'dc': row[5], 'description': row[6]})
    for row in db.get_scene_traps(sid):  # id, scene_id, x, y, radius, description, triggered
        snapshot['traps'].append({'x': row[2], 'y': row[3], 'radius': row[4],
                                  'description': row[5]})
    for mid, to_sid, mx, my in db.get_scene_markers(sid):  # permanent markers only
        snapshot['markers'].append({'to_scene_id': to_sid, 'x': mx, 'y': my})
    return snapshot

def _reset_scene_to_snapshot(sid: int, snapshot: dict):
    """Core restore: update DB and in-memory entity lists for one scene."""
    global enemies, characters
    enemies    = [e for e in enemies    if e.scene_id != sid]
    characters = [c for c in characters if c.scene_id != sid]
    db.delete_scene_enemies(sid)
    db.delete_scene_npcs(sid)
    db.delete_all_scene_items(sid)
    db.delete_all_scene_traps(sid)
    db.delete_scene_markers(sid)
    for ed in snapshot['enemies']:
        new_id = db.restore_enemy(
            ed['name'], ed['x'], ed['y'], ed['color'], ed['size'],
            ed['hp'], ed['max_hp'], ed.get('conditions', ''), ed.get('initiative', 0),
            ed.get('image_path'), sid)
        ent = Character(ed['x'], ed['y'], pygame.Color(ed['color']), ed['size'],
                        ed['name'], id=new_id, is_enemy=True)
        ent.hp = ed['hp']; ent.max_hp = ed['max_hp']
        ent.load_conditions(ed.get('conditions', ''))
        ent.initiative = ed.get('initiative', 0)
        ent.scene_id   = sid
        if ed.get('image_path'):
            ent.set_image(ed['image_path'])
        if ed.get('stat_block'):
            db.save_stat_block('enemy', new_id, ed['stat_block'])
        enemies.append(ent)
    for nd in snapshot['npcs']:
        new_id = db.restore_character(
            nd['name'], nd['x'], nd['y'], nd['color'], nd['size'],
            nd['hp'], nd['max_hp'], nd.get('conditions', ''), nd.get('initiative', 0),
            nd.get('init_bonus', 0), nd.get('is_npc', True), sid,
            nd.get('image_path'))
        ent = Character(nd['x'], nd['y'], pygame.Color(nd['color']), nd['size'],
                        nd['name'], id=new_id, is_enemy=False)
        ent.hp = nd['hp']; ent.max_hp = nd['max_hp']
        ent.load_conditions(nd.get('conditions', ''))
        ent.initiative = nd.get('initiative', 0)
        ent.init_bonus = nd.get('init_bonus', 0)
        ent.scene_id   = sid
        if nd.get('image_path'):
            ent.set_image(nd['image_path'])
        if nd.get('stat_block'):
            db.save_stat_block('character', new_id, nd['stat_block'])
        characters.append(ent)
    for it in snapshot['items']:
        db.add_scene_item(sid, it['x'], it['y'], it['radius'], it['dc'], it['description'])
    for tr in snapshot['traps']:
        db.add_scene_trap(sid, tr['x'], tr['y'], tr['radius'], tr['description'])
    for mk in snapshot.get('markers', []):
        db.add_scene_marker(sid, mk['to_scene_id'], mk['x'], mk['y'])

def _apply_scene_snapshot(sid: int):
    """Revert one scene and refresh the current scene's in-memory view."""
    snapshot = db.get_scene_snapshot(sid)
    if not snapshot:
        return
    _reset_scene_to_snapshot(sid, snapshot)
    reload_hidden_items()
    reload_scene_traps()
    reload_markers()
    rebuild_initiative()
    dm_server.broadcast_state(_get_dm_state())

def _apply_campaign_reset():
    """Revert every scene that has a saved initial state."""
    sids = db.get_snapshot_scene_ids()
    for sid in sids:
        snapshot = db.get_scene_snapshot(sid)
        if snapshot:
            _reset_scene_to_snapshot(sid, snapshot)
    reload_hidden_items()
    reload_scene_traps()
    reload_markers()
    rebuild_initiative()
    dm_server.broadcast_state(_get_dm_state())

def _update_snapshot_btn():
    """Enable/disable the Revert Scene button based on whether a snapshot exists."""
    if db.has_scene_snapshot(scene_id()):
        toolbar.disabled_btns.discard('scene_revert')
    else:
        toolbar.disabled_btns.add('scene_revert')

# ── Confirmation popup actions ────────────────────────────────────────────────

def _apply_confirm(pending):
    global scenes, current_scene_idx, _update_apply_in_progress
    if pending == 'scene_del':
        if scenes:
            db.delete_scene(scene_id())
            scenes.pop(current_scene_idx)
            if not scenes:
                current_scene_idx = 0
            else:
                current_scene_idx = min(current_scene_idx, len(scenes) - 1)
            _load_current_scene()
    elif pending == 'scene_revert':
        _apply_scene_snapshot(scene_id())
        _update_snapshot_btn()
    elif pending == 'campaign_reset':
        _apply_campaign_reset()
    elif pending == 'app_update':
        if not _update_apply_in_progress:
            _update_apply_in_progress = True
            threading.Thread(target=_bg_apply_update, daemon=True,
                             name='update-apply').start()

# ── Self-update (check GitHub, download, and apply in place) ─────────────────

_update_check_queue      = queue.Queue()   # thread → main: (latest, error, startup)
_update_apply_queue      = queue.Queue()   # thread → main: (success, message)
_update_check_in_progress = False
_update_apply_in_progress = False
_pending_update_notice    = None   # startup "update available" notice, shown once
                                    # init_msg_popup is free (won't clobber the
                                    # campaign's Initial Message popup)

def _bg_check_for_update(startup=False):
    latest, err = updater.check_for_update()
    _update_check_queue.put({'latest': latest, 'error': err, 'startup': startup})

def _bg_apply_update():
    success, message = updater.download_and_apply_update()
    _update_apply_queue.put({'success': success, 'message': message})

# ── Handle toolbar action ─────────────────────────────────────────────────────

def handle_toolbar(btn_id):
    global context_menu, hp_popup, conditions_popup, char_dialog, enemy_dialog, size_popup, group_hp_popup
    global current_turn_idx, camera_x, camera_y, scenes, current_scene_idx
    global renaming_scene, scene_new_name, scene_picker, confirm_popup
    global _place_item_dialog, _place_trap_dialog, _place_pending_pos
    global _edit_item_dialog, _edit_trap_dialog, _edit_item_obj, _edit_trap_obj
    global dc_roll_popup, dc_result_popup, trap_flash_timer, init_msg_popup, _init_msg_pending
    global build_mode, _pre_build_fog
    global _update_check_in_progress

    if btn_id == 'add_enemy':
        mx, my = pygame.mouse.get_pos()
        wx = int(mx + camera_x)
        wy = int(my - TOOLBAR_HEIGHT + camera_y)
        sid = scene_id()
        new_id = db.insert_enemy('New Enemy', wx, wy, sid)
        ent = Character(wx, wy, pygame.Color('#c0392b'), 15, 'New Enemy',
                        id=new_id, is_enemy=True)
        ent.hp = ent.max_hp = 10
        ent.scene_id = sid
        enemies.append(ent)
        rebuild_initiative()

    elif btn_id == 'add_char':
        dlg = CharacterDialog(font, small_font, WIDTH, HEIGHT)
        dlg._wx = int(camera_x + WIDTH  // 2)
        dlg._wy = int(camera_y + HEIGHT // 2)
        char_dialog = dlg

    elif btn_id == 'roll_init':
        for ent in enemies:
            roll = random.randint(1, 20)
            ent.initiative = roll
            db.update_enemy_initiative(ent.id, ent.initiative)
        for ent in characters:
            roll  = random.randint(1, 20)
            bonus = getattr(ent, 'init_bonus', 0)
            ent.initiative = roll + bonus
            db.update_character_initiative(ent.id, ent.initiative)
        rebuild_initiative()
        dm_server.broadcast_state(_get_dm_state())

    elif btn_id == 'prev_turn':
        if initiative_order:
            for _ in range(len(initiative_order)):
                current_turn_idx = (current_turn_idx - 1) % len(initiative_order)
                if not _is_fog_hidden(initiative_order[current_turn_idx]):
                    break

    elif btn_id == 'next_turn':
        if initiative_order:
            for _ in range(len(initiative_order)):
                current_turn_idx = (current_turn_idx + 1) % len(initiative_order)
                if not _is_fog_hidden(initiative_order[current_turn_idx]):
                    break

    elif btn_id == 'clear_all':
        for ent in characters + enemies:
            ent.targeted = False
            ent.selected = False

    elif btn_id in ('fog_on',) + _FOG_R_BTNS:
        if build_mode:
            return  # fog settings are locked while build mode is active
        if btn_id in _FOG_R_BTNS:
            for b in _FOG_R_BTNS:
                toolbar.active[b] = (b == btn_id)
        s = current_scene()
        if s:
            db.save_scene_fog(s[0], toolbar.active.get('fog_on', True),
                              _current_fog_radius_cells())
        dm_server.broadcast_state(_get_dm_state())

    elif btn_id == 'show_init':
        init_panel.visible = toolbar.active.get('show_init', False)

    elif btn_id == 'notes':
        notes_panel.visible = toolbar.active.get('notes', False)
        if notes_panel.visible:
            notes_panel.focused = True   # auto-focus on open


    elif btn_id == 'add_zone':
        global zone_draw_mode, zone_draw_start, zone_draw_cur
        zone_draw_mode  = True
        zone_draw_start = None
        zone_draw_cur   = None
        pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_CROSSHAIR)

    elif btn_id == 'music_enabled':
        _apply_music_enabled(toolbar.active.get('music_enabled', True))
        dm_server.broadcast_state(_get_dm_state())

    elif btn_id == 'show_zones':
        global show_zones
        show_zones = toolbar.active.get('show_zones', True)

    elif btn_id == 'build_mode':
        build_mode = toolbar.active.get('build_mode', False)
        if build_mode:
            _pre_build_fog = toolbar.active.get('fog_on', False)  # save live toolbar state
            toolbar.active['fog_on'] = False
            toolbar.disabled_btns = set(_FOG_R_BTNS) | {'fog_on'}
        else:
            toolbar.disabled_btns.clear()
            if _pre_build_fog is not None:
                toolbar.active['fog_on'] = _pre_build_fog
                s = current_scene()
                if s:
                    db.save_scene_fog(s[0], _pre_build_fog, _current_fog_radius_cells())
                _pre_build_fog = None
        dm_server.broadcast_state(_get_dm_state())

    elif btn_id == 'default_track':
        global zone_dialog, zone_dialog_is_default
        prefill = {'name': default_zone.name, 'track': default_zone.track,
                   'color': default_zone.color_hex} if default_zone else {}
        zone_dialog = SoundZoneDialog(0, 0, 0, 0, font, WIDTH, HEIGHT, prefill=prefill)
        zone_dialog_is_default = True

    elif btn_id == 'campaign_mgr':
        global campaign_dialog
        campaign_dialog = CampaignDialog(
            campaigns_mod.list_campaigns(), active_campaign, tb_font, WIDTH, HEIGHT,
            hints_map=_build_hints_map()
        )

    elif btn_id == 'open_manual':
        webbrowser.open('http://localhost:5000/manual')

    elif btn_id == 'reset_campaign':
        sids = db.get_snapshot_scene_ids()
        if sids:
            n = len(sids)
            confirm_popup = ConfirmPopup(
                f'Reset campaign to initial state?\n\n'
                f'{n} scene{"s" if n != 1 else ""} will be reverted.\n'
                f'This cannot be undone.',
                font, WIDTH, HEIGHT)
            confirm_popup._pending = 'campaign_reset'

    elif btn_id == 'lock':
        if pin_manager.has_pin():
            pin_manager.lock()   # LockOverlay appears via the per-frame sync below
        else:
            init_msg_popup = HintPopup(font, small_font, WIDTH, HEIGHT,
                "This campaign has no PIN set.\n\n"
                "Save (export) it from the web GM panel to set one — "
                "the default campaign can never have a PIN.",
                title='No PIN Set')

    elif btn_id == 'check_update':
        if not _update_check_in_progress:
            _update_check_in_progress = True
            threading.Thread(target=_bg_check_for_update, daemon=True,
                             name='update-check-manual').start()

    elif btn_id == 'set_start':
        global start_scene_id
        sid = scene_id()
        if sid:
            db.set_start_scene_id(sid)
            start_scene_id = sid

    elif btn_id == '_zoom_slider':
        _apply_zoom(toolbar.zoom_level, save=False)

    elif btn_id == 'undo':
        if undo_stack:
            ent, ox, oy = undo_stack.pop()
            ent.x, ent.y = ox, oy
            if ent.is_enemy:
                db.update_enemy_position(ent.id, int(ox), int(oy))
            else:
                db.update_character_position(ent.id, int(ox), int(oy))

    elif btn_id == 'party_home':
        party = [c for c in characters if not getattr(c, 'is_npc', False)]
        pad   = GRID_SIZE
        for i, ch in enumerate(party):
            ch.x = float(pad + i * GRID_SIZE)
            ch.y = float(pad)
            db.update_character_position(ch.id, int(ch.x), int(ch.y))
        camera_x = 0.0
        camera_y = 0.0
        if layers:
            for layer in layers:
                layer.x = 0.0
                layer.y = 0.0
                layer.clamp(WIDTH, HEIGHT - TOOLBAR_HEIGHT)
            camera_x, camera_y = -layers[0].x, -layers[0].y

    elif btn_id == 'scene_snapshot':
        db.save_scene_snapshot(scene_id(), _build_scene_snapshot(scene_id()))
        _update_snapshot_btn()

    elif btn_id == 'scene_revert':
        if db.has_scene_snapshot(scene_id()):
            confirm_popup = ConfirmPopup(
                'Revert scene to its initial state?\n'
                'All current enemies, NPCs, items and traps\n'
                'in this scene will be replaced.',
                font, WIDTH, HEIGHT)
            confirm_popup._pending = 'scene_revert'

    elif btn_id == 'scene_prev':
        if scenes:
            switch_scene((current_scene_idx - 1) % len(scenes))

    elif btn_id == 'scene_next':
        if scenes:
            switch_scene((current_scene_idx + 1) % len(scenes))

    elif btn_id == 'scene_add':
        global new_scene_popup
        new_scene_popup = NewSceneChoicePopup(font, WIDTH, HEIGHT)

    elif btn_id == 'scene_del':
        if scenes:
            sn = scene_name() or 'this scene'
            confirm_popup = ConfirmPopup(
                f'Are you sure you wish to remove "{sn}"?',
                font, WIDTH, HEIGHT)
            confirm_popup._pending = 'scene_del'

    elif btn_id == 'scene_rename':
        if scenes:
            renaming_scene = True
            scene_new_name = scene_name()

    elif btn_id in ('aoe_circle', 'aoe_cone', 'aoe_line'):
        aoe_tool.mode = toolbar.get_aoe_mode()
        aoe_tool.cancel()
        if not aoe_tool.mode:
            aoe_tool.clear_all()

    elif btn_id == 'measure':
        measure_tool.active = toolbar.active.get('measure', False)
        if not measure_tool.active:
            measure_tool.clear()

# ── Handle context menu action ────────────────────────────────────────────────

def handle_context(action):
    global context_menu, hp_popup, conditions_popup, renaming_char, new_name, char_dialog, enemy_dialog, size_popup, stat_block_panel, num_input_popup, group_hp_popup
    global _place_item_dialog, _place_trap_dialog, _place_pending_pos
    global _edit_item_dialog, _edit_trap_dialog, _edit_item_obj, _edit_trap_obj
    global target_entity
    target = getattr(context_menu, '_target', None)

    if action == 'damage':
        if target:
            num_input_popup = NumberInputPopup(target, 'damage', font, WIDTH, HEIGHT)
    elif action == 'heal':
        if target:
            num_input_popup = NumberInputPopup(target, 'heal', font, WIDTH, HEIGHT)
    elif action == 'rename':
        if target:
            renaming_char = target
            new_name      = target.name
    elif action == 'set_hp':
        if target:
            hp_popup = HPPopup(target, font, WIDTH, HEIGHT)
    elif action == 'conditions':
        if target:
            conditions_popup = ConditionsPopup(target, font, WIDTH, HEIGHT)
    elif action == 'set_init':
        if target:
            init_panel.visible = True
            toolbar.active['show_init'] = True
            init_panel.start_edit(target)
    elif action == 'clear_reticle':
        target_entity = None
    elif action == 'remove':
        if target:
            if target.is_enemy:
                db.delete_enemy(target.id)
                enemies.remove(target)
            else:
                db.delete_character(target.id)
                characters.remove(target)
            rebuild_initiative()
            if target_entity is target:
                target_entity = None
    elif action == 'remove_from_scene':
        if target and not target.is_enemy and getattr(target, 'is_npc', False):
            db.delete_character(target.id)
            characters.remove(target)
            rebuild_initiative()
            if target_entity is target:
                target_entity = None

    elif action == 'pin_to_scene':
        if target and target.is_enemy:
            sid = scene_id()
            if sid != 0:
                target.scene_id = sid
                db.update_enemy_scene(target.id, sid)
                reload_enemies()
                rebuild_initiative()

    elif action == 'make_global':
        if target and target.is_enemy:
            target.scene_id = 0
            db.update_enemy_scene(target.id, 0)
            reload_enemies()
            rebuild_initiative()

    elif action == 'add_enemy':
        wx  = int(getattr(context_menu, '_wx', 400))
        wy  = int(getattr(context_menu, '_wy', 300))
        sid = scene_id()
        new_id = db.insert_enemy('New Enemy', wx, wy, sid)
        ent = Character(wx, wy, pygame.Color('#c0392b'), 15, 'New Enemy',
                        id=new_id, is_enemy=True)
        ent.hp = ent.max_hp = 10
        ent.scene_id = sid
        enemies.append(ent)
        rebuild_initiative()

    elif action == 'add_character':
        dlg = CharacterDialog(font, small_font, WIDTH, HEIGHT)
        dlg._wx = int(getattr(context_menu, '_wx', camera_x + WIDTH  // 2))
        dlg._wy = int(getattr(context_menu, '_wy', camera_y + HEIGHT // 2))
        char_dialog = dlg

    elif action == 'char_settings':
        if target and not target.is_enemy:
            char_dialog = CharacterDialog(font, small_font, WIDTH, HEIGHT, entity=target)

    elif action == 'enemy_settings':
        if target and target.is_enemy:
            enemy_dialog = EnemyDialog(font, small_font, WIDTH, HEIGHT, entity=target)

    elif action == 'set_size':
        if target:
            size_popup = SizePopup(target, font, small_font, WIDTH, HEIGHT)

    elif action == 'stat_block':
        if target:
            etype = 'enemy' if target.is_enemy else 'char'
            data  = db.get_stat_block(etype, target.id)
            stat_block_panel = StatBlockPanel(target, data, font, small_font, WIDTH, HEIGHT)

    elif action == 'clear_aoe':
        aoe_tool.clear_all()

    elif action == 'place_item':
        global _place_item_dialog, _place_pending_pos
        wx2 = int(getattr(context_menu, '_wx', camera_x + WIDTH  // 2))
        wy2 = int(getattr(context_menu, '_wy', camera_y + HEIGHT // 2))
        _place_pending_pos  = (wx2, wy2)
        _place_item_dialog  = HiddenItemDialog(font, WIDTH, HEIGHT)

    elif action == 'place_trap':
        global _place_trap_dialog
        wx2 = int(getattr(context_menu, '_wx', camera_x + WIDTH  // 2))
        wy2 = int(getattr(context_menu, '_wy', camera_y + HEIGHT // 2))
        _place_pending_pos  = (wx2, wy2)
        _place_trap_dialog  = TrapDialog(font, WIDTH, HEIGHT)

    elif action == 'drop_scene_marker':
        global scene_picker
        if scenes and len(scenes) > 1:
            scene_picker = ScenePickerPopup(scenes, scene_id(), tb_font, WIDTH, HEIGHT)

    elif action in ('group_damage', 'group_heal'):
        global group_hp_popup
        if initiative_order:
            vis, _ = _visible_initiative()
            if vis:
                group_hp_popup = GroupHPPopup(vis, font, small_font, WIDTH, HEIGHT)

    elif action == 'edit_item':
        global _edit_item_dialog, _edit_item_obj
        hit = getattr(context_menu, '_hit_item', None)
        if hit:
            _edit_item_obj    = hit
            _edit_item_dialog = HiddenItemDialog(font, WIDTH, HEIGHT,
                                                  existing={'dc': hit.dc,
                                                            'radius': hit.radius,
                                                            'description': hit.description})
            _edit_item_dialog._TITLE = 'Edit Hidden Item'

    elif action == 'remove_item':
        hit = getattr(context_menu, '_hit_item', None)
        if hit:
            db.delete_scene_item(hit.id)
            hidden_items[:] = [i for i in hidden_items if i.id != hit.id]
            _item_cooldowns.pop(hit.id, None)

    elif action == 'edit_trap':
        global _edit_trap_dialog, _edit_trap_obj
        hit = getattr(context_menu, '_hit_trap', None)
        if hit:
            _edit_trap_obj    = hit
            _edit_trap_dialog = TrapDialog(font, WIDTH, HEIGHT,
                                            existing={'radius': hit.radius,
                                                      'description': hit.description})
            _edit_trap_dialog._TITLE = 'Edit Trap'

    elif action == 'reset_trap':
        hit = getattr(context_menu, '_hit_trap', None)
        if hit:
            hit.triggered = False
            db.reset_scene_trap(hit.id)
            dm_server.broadcast_state(_get_dm_state())

    elif action == 'remove_trap':
        hit = getattr(context_menu, '_hit_trap', None)
        if hit:
            db.delete_scene_trap(hit.id)
            scene_traps_list[:] = [t for t in scene_traps_list if t.id != hit.id]

    context_menu = None

def _return_marker_pos():
    """World (x, y) near the party, biased up-left, avoiding character tokens."""
    if not characters:
        return (camera_x + WIDTH // 2, camera_y + (HEIGHT - TOOLBAR_HEIGHT) // 2)

    # Use bounding box of the party to find a true up-left anchor point
    min_x = min(c.x for c in characters)
    min_y = min(c.y for c in characters)
    cx    = sum(c.x for c in characters) / len(characters)
    cy    = sum(c.y for c in characters) / len(characters)

    dist       = GRID_SIZE * 2.5
    clear_min  = GRID_SIZE          # minimum acceptable gap from any token

    # Candidate directions in preference order: up-left first, then up, then
    # left, then the remaining compass points as fallbacks.
    # In screen/world coords: Y increases downward, so sin negative = up.
    # 225° → cos≈-0.707, sin≈-0.707 → up-left
    pref_dirs = [225, 270, 180, 315, 90, 135, 0, 45]

    # First pass: try up-left anchor from bounding box edge (not centroid)
    # so the marker doesn't land inside a tight cluster.
    for deg in pref_dirs:
        rad = math.radians(deg)
        # Anchor from the bounding-box corner for up-left directions,
        # centroid for everything else.
        if deg in (225, 270, 180):
            ax, ay = min_x, min_y
        else:
            ax, ay = cx, cy
        tx = ax + math.cos(rad) * dist
        ty = ay + math.sin(rad) * dist
        gap = min(math.hypot(tx - c.x, ty - c.y) for c in characters)
        if gap >= clear_min:
            return (tx, ty)

    # All directions blocked — fall back to whichever maximises gap
    best, best_gap = (cx - dist, cy - dist), -1.0
    for deg in pref_dirs:
        rad = math.radians(deg)
        tx = cx + math.cos(rad) * dist
        ty = cy + math.sin(rad) * dist
        gap = min(math.hypot(tx - c.x, ty - c.y) for c in characters)
        if gap > best_gap:
            best_gap = gap
            best = (tx, ty)
    return best


def _place_marker(to_scene_id):
    """Drop a scene marker at the centre of the current view."""
    sid = scene_id()
    if not sid:
        return
    wx = camera_x + WIDTH  // 2
    wy = camera_y + (HEIGHT - TOOLBAR_HEIGHT) // 2
    mid  = db.add_scene_marker(sid, to_scene_id, wx, wy)
    name = next((s[1] for s in scenes if s[0] == to_scene_id), '???')
    scene_markers.append(SceneMarker(mid, wx, wy, to_scene_id, name))

def _apply_group_hp(action, amount, entity_ids):
    """Apply group damage, healing, or full heal to entities whose IDs are in entity_ids."""
    for ent in characters + enemies:
        if ent.id in entity_ids:
            if action == 'damage':    ent.hp = max(0, ent.hp - amount)
            elif action == 'full_heal': ent.hp = ent.max_hp
            else:                     ent.hp = min(ent.max_hp, ent.hp + amount)
            if ent.is_enemy: db.update_enemy_hp(ent.id, ent.hp)
            else:            db.update_character_hp(ent.id, ent.hp)
    dm_server.broadcast_state(_get_dm_state())

def apply_num_input(kind, amount):
    """Apply a confirmed damage or heal amount to num_input_popup.entity."""
    global num_input_popup
    ent = num_input_popup.entity if num_input_popup else None
    if not ent or amount <= 0:
        num_input_popup = None
        return
    if kind == 'confirm':
        if num_input_popup.mode == 'damage':
            ent.hp = max(0, ent.hp - amount)
        else:
            ent.hp = min(ent.max_hp, ent.hp + amount)
        if ent.is_enemy:
            db.update_enemy_hp(ent.id, ent.hp)
        else:
            db.update_character_hp(ent.id, ent.hp)
    num_input_popup = None

# ── Button feedback sound maps ─────────────────────────────────────────────────

_TOOLBAR_SOUND = {
    'roll_init':     'roll',
    'add_enemy':     'click',
    'add_char':      'click',
    'clear_all':     'damage',
    'reset_campaign':'damage',
    'scene_add':     'confirm',
    'scene_del':     'damage',
    'prev_turn':     'select',
    'next_turn':     'select',
    'fog_on':        'click',
    'music_enabled': 'click',
}
# All other toolbar buttons default to 'click' (see _toolbar_sound())

def _toolbar_sound(btn_id):
    return _TOOLBAR_SOUND.get(btn_id, 'click')

_CONTEXT_SOUND = {
    'damage':           'damage',
    'group_damage':     'damage',
    'heal':             'heal',
    'group_heal':       'heal',
    'remove':           'damage',
    'remove_item':      'damage',
    'remove_trap':      'damage',
    'char_settings':    'click',
    'enemy_settings':   'click',
    'rename':           'click',
    'set_hp':           'click',
    'conditions':       'click',
    'set_init':         'click',
    'set_size':         'click',
    'stat_block':       'click',
    'clear_reticle':    'click',
    'pin_to_scene':     'click',
    'make_global':      'click',
    'edit_item':        'click',
    'edit_trap':        'click',
    'reset_trap':       'click',
    'remove_from_scene':'damage',
}

_HP_POPUP_SOUND = {
    'close':       'cancel',
    'hp':          None,          # resolved dynamically (damage vs heal)
    'max_hp':      'select',
    'full_heal':   'heal',
    'set_as_max':  'confirm',
    'set_hp_abs':  'select',
    'set_max_abs': 'select',
}

def _apply_hp_popup(kind, val):
    """Apply a result from HPPopup.hit() or HPPopup.key() to the entity."""
    global hp_popup
    # Play sound before mutating state
    if kind == 'hp':
        sound_fx.play('damage' if (val or 0) < 0 else 'heal')
    elif kind in _HP_POPUP_SOUND and _HP_POPUP_SOUND[kind]:
        sound_fx.play(_HP_POPUP_SOUND[kind])
    if kind == 'close':
        hp_popup = None
    elif kind == 'hp':
        ent = hp_popup.entity
        ent.hp = max(0, ent.hp + val)
        if ent.is_enemy: db.update_enemy_hp(ent.id, ent.hp)
        else:            db.update_character_hp(ent.id, ent.hp)
    elif kind == 'max_hp':
        ent = hp_popup.entity
        ent.max_hp = max(1, ent.max_hp + val)
        if ent.is_enemy: db.update_enemy_max_hp(ent.id, ent.max_hp)
        else:            db.update_character_max_hp(ent.id, ent.max_hp)
    elif kind == 'full_heal':
        ent = hp_popup.entity
        ent.hp = ent.max_hp
        if ent.is_enemy: db.update_enemy_hp(ent.id, ent.hp)
        else:            db.update_character_hp(ent.id, ent.hp)
    elif kind == 'set_as_max':
        ent = hp_popup.entity
        ent.max_hp = max(1, ent.hp)
        ent.hp     = ent.max_hp
        if ent.is_enemy:
            db.update_enemy_max_hp(ent.id, ent.max_hp)
            db.update_enemy_hp(ent.id, ent.hp)
        else:
            db.update_character_max_hp(ent.id, ent.max_hp)
            db.update_character_hp(ent.id, ent.hp)
    elif kind == 'set_hp_abs':
        ent = hp_popup.entity
        ent.hp = max(0, min(ent.max_hp, val))
        if ent.is_enemy: db.update_enemy_hp(ent.id, ent.hp)
        else:            db.update_character_hp(ent.id, ent.hp)
    elif kind == 'set_max_abs':
        ent = hp_popup.entity
        ent.max_hp = max(1, val)
        ent.hp     = min(ent.hp, ent.max_hp)
        if ent.is_enemy:
            db.update_enemy_max_hp(ent.id, ent.max_hp)
            db.update_enemy_hp(ent.id, ent.hp)
        else:
            db.update_character_max_hp(ent.id, ent.max_hp)
            db.update_character_hp(ent.id, ent.hp)

def _any_modal_open():
    """True if any dialog/popup is currently covering the map."""
    return any([
        _place_item_dialog, _place_trap_dialog, _edit_item_dialog, _edit_trap_dialog,
        init_msg_popup, build_mode_hint, dc_roll_popup, dc_result_popup, tta_browser,
        zone_dialog, campaign_dialog, char_dialog, enemy_dialog, size_popup,
        stat_block_panel, notes_panel.visible, new_scene_popup, dungeon_gen_dialog,
        scene_picker, confirm_popup, group_hp_popup, num_input_popup, hp_popup,
        conditions_popup, context_menu,
    ])


# ── Main loop ─────────────────────────────────────────────────────────────────
running = True
clock   = pygame.time.Clock()
_last_caption_url = _effective_gm_url()

threading.Thread(target=telemetry.send_launch_event,
                 args=(updater.get_current_version(),),
                 daemon=True, name='telemetry-launch').start()

# Silent startup check — only surfaces a popup if an update is actually
# available; stays quiet if already up to date or the check fails.
_update_check_in_progress = True
threading.Thread(target=_bg_check_for_update, kwargs={'startup': True},
                 daemon=True, name='update-check-startup').start()

while running:
    now = pygame.time.get_ticks()

    # ── Keep window caption in sync with hotspot/network changes ─────────────
    _cur_url = _effective_gm_url()
    if _cur_url != _last_caption_url:
        _last_caption_url = _cur_url
        pygame.display.set_caption(
            f"RealmScape — {active_campaign}  |  GM Panel: {_cur_url}")

    # ── Sync lock overlay with pin_manager state (web panel may have changed it,
    # or loading/switching to a PIN-protected campaign locks automatically)
    if pin_manager.locked and lock_overlay is None:
        lock_overlay = LockOverlay(font, WIDTH, HEIGHT)
    elif not pin_manager.locked and lock_overlay is not None:
        lock_overlay = None

    # ── DM remote commands ────────────────────────────────────────────────────
    while not dm_server.cmd_queue.empty():
        try:
            _handle_dm_command(dm_server.cmd_queue.get_nowait())
        except queue.Empty:
            break
        except Exception as _cmd_err:
            import traceback
            print(f'[DM command error] {_cmd_err}')
            traceback.print_exc()

    # Periodic heartbeat so the browser stays in sync with local changes
    _dm_tick += 1
    if _dm_tick >= 90:      # ~1.5 s at 60 fps
        _dm_tick = 0
        old_zone = active_zone_id
        check_zone_detection()
        if active_zone_id != old_zone:
            dm_server.broadcast_state(_get_dm_state())
        else:
            dm_server.broadcast_state(_get_dm_state())

    # ── Tick cooldowns & detect proximity ─────────────────────────────────────
    if trap_flash_timer > 0:
        trap_flash_timer -= 1

    for k in list(_item_cooldowns):
        _item_cooldowns[k] -= 1
        if _item_cooldowns[k] <= 0:
            del _item_cooldowns[k]

    if dc_roll_popup is None and dc_result_popup is None:
        all_ents = characters + enemies
        for item in hidden_items:
            if item.found or item.id in _item_cooldowns:
                continue
            for ent in all_ents:
                if math.hypot(ent.x - item.x, ent.y - item.y) <= item.radius:
                    dc_roll_popup = DCRollPopup(font, WIDTH, HEIGHT, item)
                    break
            if dc_roll_popup:
                break

        if dc_roll_popup is None:
            for trap in scene_traps_list:
                if trap.triggered:
                    continue
                if fog_on:
                    _vr = _current_vision_radius()
                    if not any(math.hypot(trap.x - c.x, trap.y - c.y) <= _vr
                               for c in characters):
                        continue  # trap is in fogged area — cannot trigger
                for ent in all_ents:
                    if math.hypot(ent.x - trap.x, ent.y - trap.y) <= trap.radius:
                        trap.triggered = True
                        db.trigger_scene_trap(trap.id)
                        trap_flash_timer = 45
                        break

    vis_order, vis_idx = _visible_initiative()

    # ── Long-press detection (single finger, not moved, held long enough) ──
    if len(touch_fingers) == 1:
        fid, fdata = next(iter(touch_fingers.items()))
        if not fdata['moved'] and not fdata['fired_lp']:
            if now - fdata['start_time'] >= LONG_PRESS_MS:
                fdata['fired_lp'] = True
                sx, sy = fdata['last']
                sr = toolbar._sc_r.get('name')
                if scenes and sr and sr.collidepoint(sx, sy):
                    renaming_scene = True
                    scene_new_name = scene_name()
                else:
                    open_context_menu(sx, sy)

    # ── Event loop ────────────────────────────────────────────────────────────
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        # ── PIN lock overlay intercepts everything except QUIT ──────────────
        elif lock_overlay:
            if event.type == pygame.FINGERUP:
                # LockOverlay only understands MOUSEBUTTONDOWN/KEYDOWN — translate
                # the tap so the numpad responds to touch, not just mouse clicks.
                event = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                    {'button': 1, 'pos': (int(event.x * WIDTH), int(event.y * HEIGHT))})
            pin = lock_overlay.handle_event(event)
            if pin is not None:
                if pin_manager.verify_pin(pin):
                    pin_manager.unlock()
                    lock_overlay = None
                else:
                    lock_overlay.wrong_pin()

        # ── Window resize / move (SDL2 events, no polling needed) ──────────
        elif event.type == pygame.VIDEORESIZE:
            # pygame 2.x: window is already resized; do NOT call set_mode()
            # again — that would destroy and recreate the window, causing GL
            # context errors and flickering. WINDOWRESIZED (below) also fires
            # and handles the update; this branch just stays for safety.
            WIDTH, HEIGHT = event.w, event.h
            window_state['width'] = WIDTH
            window_state['height'] = HEIGHT
            db.update_window_state(WIDTH, HEIGHT,
                                   window_state['x'], window_state['y'])

        elif event.type == pygame.WINDOWRESIZED:
            WIDTH, HEIGHT = event.x, event.y
            window_state['width'] = WIDTH
            window_state['height'] = HEIGHT
            db.update_window_state(WIDTH, HEIGHT,
                                   window_state['x'], window_state['y'])

        elif event.type == pygame.WINDOWMOVED:
            window_state['x'] = event.x
            window_state['y'] = event.y
            db.update_window_state(window_state['width'], window_state['height'],
                                   event.x, event.y)

        # ── Drag & drop image ──────────────────────────────────────────────
        elif event.type == pygame.DROPFILE:
            path = event.file
            if path.lower().endswith(('.png','.jpg','.jpeg','.bmp','.gif')):
                mpos = pygame.mouse.get_pos()
                hit  = next((e for e in enemies + characters
                              if e.is_clicked(mpos, camera_x, camera_y)), None)
                if hit:
                    hit.set_image(path)
                    rel = campaigns_mod.import_asset(path, active_campaign)
                    hit.image_path = rel
                    if hit.is_enemy:
                        db.update_enemy_image_path(hit.id, rel)
                    else:
                        db.update_character_image_path(hit.id, rel)
                else:
                    set_bg_image(path)

        # ── Touch events ───────────────────────────────────────────────────
        elif event.type == pygame.FINGERDOWN:
            fx = int(event.x * WIDTH)
            fy = int(event.y * HEIGHT)
            touch_fingers[event.finger_id] = {
                'start': (fx, fy), 'last': (fx, fy),
                'start_time': now, 'moved': False, 'fired_lp': False
            }
            # First finger down on the map — grab a marker/token to drag, mirroring
            # the mouse's press-to-start-drag behavior (markers take priority).
            if len(touch_fingers) == 1 and not _any_modal_open():
                fake_pos = (fx, fy)
                map_pos  = (fx, fy - TOOLBAR_HEIGHT)
                if not toolbar.is_over(fake_pos):
                    renaming_char     = None
                    dragged_ent       = None
                    dragged_marker    = None
                    marker_drag_start = None
                    for mk in scene_markers:
                        if mk.is_clicked(fake_pos, camera_x, camera_y, TOOLBAR_HEIGHT):
                            dragged_marker    = mk
                            marker_drag_start = fake_pos
                            sound_fx.play('select')
                            break
                    if not dragged_marker:
                        for ent in characters + enemies:
                            if ent.is_clicked(map_pos, camera_x, camera_y):
                                dragged_ent = ent
                                dragging    = True
                                sound_fx.play('pickup')
                                _is_party = not ent.is_enemy and not getattr(ent, 'is_npc', False)
                                if toolbar.active.get('group_move') and _is_party:
                                    _gm_party = [c for c in characters if not getattr(c, 'is_npc', False)]
                                    for e in _gm_party:
                                        undo_stack.append((e, e.x, e.y))
                                    target_entity = None
                                else:
                                    undo_stack.append((ent, ent.x, ent.y))
                                    if target_entity is not None and target_entity is not ent:
                                        target_entity = None
                                if len(undo_stack) > MAX_UNDO:
                                    del undo_stack[:len(undo_stack) - MAX_UNDO]
                                for c in characters: c.selected = (c == ent)
                                break
            # Cancel entity/marker drag if a second finger goes down (switch to pan)
            if len(touch_fingers) >= 2:
                if dragged_ent:
                    dragging   = False
                    dragged_ent = None
                if dragged_marker:
                    dragged_marker    = None
                    marker_drag_start = None

        elif event.type == pygame.FINGERMOTION:
            fx = int(event.x * WIDTH)
            fy = int(event.y * HEIGHT)
            if event.finger_id in touch_fingers:
                fd = touch_fingers[event.finger_id]
                lx, ly = fd['last']
                dpx, dpy = fx - lx, fy - ly
                fd['last'] = (fx, fy)
                sx, sy = fd['start']
                if math.hypot(fx - sx, fy - sy) > LONG_PRESS_MOVE_PX:
                    fd['moved'] = True

                if len(touch_fingers) >= 2:
                    # Two-finger camera pan
                    camera_x = max(0, camera_x - dpx)
                    camera_y = max(0, camera_y - dpy)
                    for layer in layers:
                        layer.x = -camera_x
                        layer.y = -camera_y
                        layer.clamp(WIDTH, HEIGHT - TOOLBAR_HEIGHT)
                    if layers:
                        camera_x, camera_y = -layers[0].x, -layers[0].y
                elif dragged_marker:
                    dragged_marker.x = fx + camera_x
                    dragged_marker.y = fy - TOOLBAR_HEIGHT + camera_y
                elif dragging and dragged_ent:
                    dragged_ent.x = fx + camera_x
                    dragged_ent.y = fy - TOOLBAR_HEIGHT + camera_y

        elif event.type == pygame.FINGERUP:
            fd = touch_fingers.pop(event.finger_id, None)
            if fd and (dragged_ent or dragged_marker):
                # Finish the single-finger token/marker drag started on FINGERDOWN —
                # reuse the exact same finalize logic as a real mouse-button release
                # instead of duplicating the DB-save / group-move / portal-tap code.
                fx, fy = fd['last']
                pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP,
                                                     {'button': 1, 'pos': (fx, fy)}))
                continue
            if fd and not fd['moved'] and not fd['fired_lp']:
                # Tap — treat as left-click
                fx, fy = fd['last']
                fake_pos = (fx, fy)
                # Cancel scene rename if tapping outside the name slot
                if renaming_scene:
                    sr = toolbar._sc_r.get('name')
                    if not (sr and sr.collidepoint(fake_pos)):
                        renaming_scene = False
                # Any modal dialog/popup currently open? Re-dispatch the tap as a
                # real MOUSEBUTTONDOWN + MOUSEBUTTONUP pair so it runs through the
                # exact same handling as a desktop mouse click, instead of keeping a
                # second, hand-maintained copy of this logic in sync per-dialog (the
                # previous approach, which is how several dialogs ended up unreachable
                # by touch — they were simply never added to that list).
                if _any_modal_open():
                    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                                         {'button': 1, 'pos': fake_pos}))
                    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP,
                                                         {'button': 1, 'pos': fake_pos}))
                    continue

                toolbar.maybe_close_dropdown(fake_pos)
                if toolbar.is_over(fake_pos):
                    btn = toolbar.click(fake_pos)
                    if btn:
                        handle_toolbar(btn)
                elif not (hp_popup or conditions_popup or context_menu):
                    # Select entity
                    hit = next((e for e in enemies + characters
                                if e.is_clicked(fake_pos, camera_x, camera_y)), None)
                    if hit:
                        sound_fx.play('pickup')
                        for c in characters: c.selected = False
                        hit.selected = True

        # ── Mouse button down ──────────────────────────────────────────────
        elif event.type == pygame.MOUSEBUTTONDOWN:
            # Ignore synthetic mouse events generated by touch — FINGERUP handles those.
            if getattr(event, 'touch', False):
                continue
            pos = event.pos
            # Cancel scene rename if clicking anywhere outside the name slot
            if renaming_scene:
                sr = toolbar._sc_r.get('name')
                if not (sr and sr.collidepoint(pos)):
                    renaming_scene = False
            toolbar.maybe_close_dropdown(pos)

            # Hidden-item / trap placement dialogs
            if _place_item_dialog:
                _place_item_dialog.handle_event(event)
                if _place_item_dialog.done:
                    if _place_item_dialog.result and _place_pending_pos:
                        r = _place_item_dialog.result
                        px, py = _place_pending_pos
                        new_id = db.add_scene_item(scene_id(), px, py,
                                                   r['radius'], r['dc'], r['description'])
                        hidden_items.append(HiddenItem(new_id, scene_id(), px, py,
                                                       r['radius'], r['dc'],
                                                       r['description'], False))
                        if not build_mode:
                            build_mode_hint = HintPopup(font, small_font, WIDTH, HEIGHT,
                                "Hidden Item added — but it won't be visible yet!\n\n"
                                "Hidden items only appear on the screen when"
                                "Build Mode is active.\n\n"
                                "Enable it now via Map > Build Mode.",
                    title='Important Message')
                    _place_item_dialog = None
                    _place_pending_pos = None
                continue

            if _place_trap_dialog:
                _place_trap_dialog.handle_event(event)
                if _place_trap_dialog.done:
                    if _place_trap_dialog.result and _place_pending_pos:
                        r = _place_trap_dialog.result
                        px, py = _place_pending_pos
                        new_id = db.add_scene_trap(scene_id(), px, py,
                                                   r['radius'], r['description'])
                        scene_traps_list.append(SceneTrap(new_id, scene_id(), px, py,
                                                          r['radius'], r['description'], False))
                        if not build_mode:
                            build_mode_hint = HintPopup(font, small_font, WIDTH, HEIGHT,
                                "Trap placed — but it won't be visible yet!\n\n"
                                "Traps only appear on the screen when"
                                "Build Mode is active.\n\n"
                                "Enable it now via Map > Build Mode.",
                    title='Important Message')
                    _place_trap_dialog = None
                    _place_pending_pos = None
                continue

            if _edit_item_dialog:
                _edit_item_dialog.handle_event(event)
                if _edit_item_dialog.done:
                    if _edit_item_dialog.result and _edit_item_obj:
                        r = _edit_item_dialog.result
                        db.update_scene_item(_edit_item_obj.id, r['dc'],
                                             r['description'], r['radius'])
                        _edit_item_obj.dc          = r['dc']
                        _edit_item_obj.description = r['description']
                        _edit_item_obj.radius      = r['radius']
                    _edit_item_dialog = None
                    _edit_item_obj    = None
                continue

            if _edit_trap_dialog:
                _edit_trap_dialog.handle_event(event)
                if _edit_trap_dialog.done:
                    if _edit_trap_dialog.result and _edit_trap_obj:
                        r = _edit_trap_dialog.result
                        db.update_scene_trap(_edit_trap_obj.id,
                                             r['description'], r['radius'])
                        _edit_trap_obj.description = r['description']
                        _edit_trap_obj.radius      = r['radius']
                    _edit_trap_dialog = None
                    _edit_trap_obj    = None
                continue

            if init_msg_popup:
                if init_msg_popup.handle_event(event):
                    init_msg_popup = None
                continue

            if build_mode_hint:
                if build_mode_hint.handle_event(event):
                    build_mode_hint = None
                continue

            # DC roll popup
            if dc_roll_popup:
                dc_roll_popup.handle_event(event)
                if dc_roll_popup.done:
                    item = dc_roll_popup.item
                    found = dc_roll_popup.result
                    dc_roll_popup = None
                    if found is True:
                        db.delete_scene_item(item.id)
                        hidden_items[:] = [i for i in hidden_items if i.id != item.id]
                        dc_result_popup = DCResultPopup(font, WIDTH, HEIGHT,
                                                        True, item.description)
                    elif found is False:
                        _item_cooldowns[item.id] = 300  # 5 s cooldown
                        dc_result_popup = DCResultPopup(font, WIDTH, HEIGHT, False, '')
                continue

            if dc_result_popup:
                dc_result_popup.handle_event(event)
                if dc_result_popup.done:
                    dc_result_popup = None
                continue

            # TTA browser (sits on top of zone_dialog)
            if tta_browser:
                result = tta_browser.handle_event(event)
                if result == 'close':
                    tta_browser = None
                elif result is not None:  # a URL was selected
                    if zone_dialog:
                        zone_dialog.set_track(result)
                    tta_browser = None
                continue

            # Zone dialog
            if zone_dialog:
                res = zone_dialog.handle_event(event)
                _apply_zone_dialog(res)
                continue

            # Zone draw mode – record start point
            if zone_draw_mode:
                wx = pos[0] + camera_x
                wy = (pos[1] - TOOLBAR_HEIGHT) + camera_y
                zone_draw_start = (wx, wy)
                zone_draw_cur   = (wx, wy)
                continue

            # Campaign dialog
            if campaign_dialog:
                action = campaign_dialog.handle_event(event)
                _apply_campaign_dialog(action)
                continue

            # Character dialog
            if char_dialog:
                result = char_dialog.handle_event(event)
                if result == 'cancel':
                    r = getattr(char_dialog, 'last_press_rect', None)
                    (press_fx.trigger(r) if r else press_fx.trigger_pos(event.pos)) \
                        if event.type == pygame.MOUSEBUTTONDOWN else None
                    sound_fx.play('cancel')
                    char_dialog = None
                elif result is not None:
                    r = getattr(char_dialog, 'last_press_rect', None)
                    (press_fx.trigger(r) if r else press_fx.trigger_pos(event.pos)) \
                        if event.type == pygame.MOUSEBUTTONDOWN else None
                    apply_char_dialog(result)
                continue

            if enemy_dialog:
                result = enemy_dialog.handle_event(event)
                if result == 'cancel':
                    r = getattr(enemy_dialog, 'last_press_rect', None)
                    (press_fx.trigger(r) if r else press_fx.trigger_pos(event.pos)) \
                        if event.type == pygame.MOUSEBUTTONDOWN else None
                    sound_fx.play('cancel')
                    enemy_dialog = None
                elif result is not None:
                    r = getattr(enemy_dialog, 'last_press_rect', None)
                    (press_fx.trigger(r) if r else press_fx.trigger_pos(event.pos)) \
                        if event.type == pygame.MOUSEBUTTONDOWN else None
                    apply_enemy_dialog(result)
                continue

            # Size popup
            if size_popup:
                kind, val = size_popup.hit(pos)
                if kind == 'close':
                    size_popup = None
                elif kind == 'size':
                    ent = size_popup.entity
                    ent.size = val
                    if ent.is_enemy: db.update_enemy_size(ent.id, val)
                    else:            db.update_character_size(ent.id, val)
                    size_popup = None
                continue

            # Notes panel (clicks inside the panel are consumed; outside unfocus)
            if notes_panel.visible:
                action = notes_panel.hit(pos)
                if action == 'close':
                    notes_panel.visible = False
                    toolbar.active['notes'] = False
                    db.save_notes(scene_id(), notes_panel.text)
                    continue
                elif action == 'focus':
                    notes_panel.focused = True
                    continue
                else:
                    notes_panel.focused = False   # click outside → unfocus

            # Stat block panel (non-modal: inside clicks consumed, outside fall through)
            if stat_block_panel:
                kind, val = stat_block_panel.hit(pos)
                if kind == 'close':
                    stat_block_panel = None
                    continue
                elif kind in ('inc', 'dec'):
                    stat_block_panel.adjust(val, 1 if kind == 'inc' else -1)
                    etype = 'enemy' if stat_block_panel.entity.is_enemy else 'char'
                    db.save_stat_block(etype, stat_block_panel.entity.id,
                                       stat_block_panel.data)
                    continue
                # else: click outside the panel — fall through to map interactions

            # New-scene choice popup (Blank Map vs Generate Map)
            if new_scene_popup:
                choice = new_scene_popup.hit(pos)
                if choice == 'blank':
                    new_scene_popup = None
                    _create_blank_scene()
                elif choice == 'generate':
                    new_scene_popup = None
                    dungeon_gen_dialog = DungeonGenDialog(
                        font, WIDTH, HEIGHT,
                        default_name=f'Scene {len(scenes)+1}')
                elif choice == 'cancel':
                    new_scene_popup = None
                continue

            # Dungeon gen dialog (unified params + preview)
            if dungeon_gen_dialog:
                ret = dungeon_gen_dialog.mouse_down(pos)
                if isinstance(ret, tuple) and ret[0] == 'generate':
                    import time as _time
                    assets_dir = campaigns_mod.assets_path(active_campaign)
                    os.makedirs(assets_dir, exist_ok=True)
                    out_path = os.path.join(
                        assets_dir, f'dungeon_{int(_time.time())}.png')
                    if _pending_gen_path and os.path.exists(_pending_gen_path):
                        try: os.remove(_pending_gen_path)
                        except OSError: pass
                    _pending_gen_path = out_path
                    dungeon_gen_dialog.set_generating()
                    threading.Thread(target=_run_dungeon_gen,
                                     args=(ret[1], out_path), daemon=True).start()
                if dungeon_gen_dialog.done:
                    if dungeon_gen_dialog.result:
                        _accept_generated_scene()
                    else:
                        if _pending_gen_path and os.path.exists(_pending_gen_path):
                            try: os.remove(_pending_gen_path)
                            except OSError: pass
                    dungeon_gen_dialog = None
                continue

            # Scene picker popup
            if scene_picker:
                action, val = scene_picker.hit(pos)
                if action == 'select':
                    _place_marker(val)
                scene_picker = None
                continue

            # Confirm popup
            if confirm_popup:
                result = confirm_popup.hit(pos)
                if result is True:
                    press_fx.trigger_pos(pos)
                    sound_fx.play('confirm')
                    _apply_confirm(confirm_popup._pending)
                    confirm_popup = None
                elif result is False:
                    press_fx.trigger_pos(pos)
                    sound_fx.play('cancel')
                    confirm_popup = None
                continue

            # Group HP popup
            if group_hp_popup:
                action, amt, ids = group_hp_popup.hit(pos)
                if action == 'close':
                    press_fx.trigger_pos(pos)
                    sound_fx.play('cancel')
                    group_hp_popup = None
                elif action == 'damage':
                    press_fx.trigger_pos(pos)
                    sound_fx.play('damage')
                    _apply_group_hp(action, amt, ids)
                    group_hp_popup = None
                elif action in ('heal', 'full_heal'):
                    press_fx.trigger_pos(pos)
                    sound_fx.play('heal')
                    _apply_group_hp(action, amt, ids)
                    group_hp_popup = None
                continue

            # Number-input popup (damage / heal)
            if num_input_popup:
                kind, val = num_input_popup.hit(pos)
                if kind == 'confirm':
                    press_fx.trigger_pos(pos)
                    sound_fx.play('damage' if num_input_popup.mode == 'damage' else 'heal')
                    apply_num_input(kind, val or 0)
                elif kind == 'cancel':
                    press_fx.trigger_pos(pos)
                    sound_fx.play('cancel')
                    apply_num_input(kind, val or 0)
                continue

            # HP popup
            if hp_popup:
                kind, val = hp_popup.hit(pos)   # also sets hp_popup.last_hit_rect
                if kind is not None:
                    r = hp_popup.last_hit_rect
                    press_fx.trigger(r) if r else press_fx.trigger_pos(pos)
                _apply_hp_popup(kind, val)
                continue

            # Conditions popup
            if conditions_popup:
                kind, val = conditions_popup.hit(pos)  # sets conditions_popup.last_hit_rect
                if kind == 'close':
                    r = conditions_popup.last_hit_rect
                    press_fx.trigger(r) if r else press_fx.trigger_pos(pos)
                    sound_fx.play('cancel')
                    conditions_popup = None
                elif kind == 'toggle':
                    r = conditions_popup.last_hit_rect
                    press_fx.trigger(r) if r else press_fx.trigger_pos(pos)
                    sound_fx.play('select')
                    ent = conditions_popup.entity
                    if val in ent.conditions: ent.conditions.discard(val)
                    else:                     ent.conditions.add(val)
                    cs = ent.conditions_str()
                    if ent.is_enemy: db.update_enemy_conditions(ent.id, cs)
                    else:            db.update_character_conditions(ent.id, cs)
                continue

            # Context menu
            if context_menu:
                action = context_menu.hit(pos)  # also sets context_menu.last_hit_rect
                if action:
                    r = context_menu.last_hit_rect
                    press_fx.trigger(r) if r else press_fx.trigger_pos(pos)
                    sound_fx.play(_CONTEXT_SOUND.get(action, 'click'))
                    handle_context(action)
                elif context_menu.is_outside(pos):
                    context_menu = None
                continue

            # Initiative panel
            if init_panel.is_over(pos, WIDTH):
                grp_btn = init_panel.hit_group_btn(pos, WIDTH)
                if grp_btn in ('group_damage', 'group_heal') and initiative_order:
                    vis, _ = _visible_initiative()
                    if vis:
                        group_hp_popup = GroupHPPopup(vis, font, small_font, WIDTH, HEIGHT)
                else:
                    row_idx = init_panel.hit_row(pos, vis_order, WIDTH, HEIGHT)
                    if row_idx is not None:
                        init_panel.start_edit(vis_order[row_idx])
                continue

            # Toolbar
            if toolbar.is_over(pos):
                btn = toolbar.click(pos)    # also sets toolbar.last_hit_rect
                r = toolbar.last_hit_rect
                if r:
                    press_fx.trigger(r)
                if btn:
                    sound_fx.play(_toolbar_sound(btn))
                    handle_toolbar(btn)
                else:
                    sound_fx.play('click')  # tab open/close
                continue

            # Map area  (pos adjusted for toolbar offset for world coords)
            map_pos = (pos[0], pos[1] - TOOLBAR_HEIGHT)

            if event.button == 1:
                # AoE tool
                if aoe_tool.mode:
                    wx = pos[0] + camera_x
                    wy = pos[1] - TOOLBAR_HEIGHT + camera_y
                    aoe_tool.start(wx, wy)
                    continue

                # Measure tool
                if measure_tool.active:
                    wx = pos[0] + camera_x
                    wy = pos[1] - TOOLBAR_HEIGHT + camera_y
                    if measure_tool.start is None:
                        measure_tool.set_start(wx, wy)
                    else:
                        measure_tool.set_end(wx, wy)
                    continue

                # Legend click
                if char_legend_rect().collidepoint(pos):
                    clicked = char_in_legend(pos)
                    if clicked:
                        for c in characters: c.selected = (c == clicked)
                        renaming_char = clicked
                        new_name      = clicked.name
                    continue

                # Start drag — markers take priority (they sit on the map)
                renaming_char      = None
                dragged_ent        = None
                dragged_marker     = None
                marker_drag_start  = None
                for mk in scene_markers:
                    if mk.is_clicked(pos, camera_x, camera_y, TOOLBAR_HEIGHT):
                        dragged_marker    = mk
                        marker_drag_start = pos   # screen coords at press-down
                        sound_fx.play('select')
                        break
                if not dragged_marker:
                    for ent in characters + enemies:
                        if ent.is_clicked(map_pos, camera_x, camera_y):
                            dragged_ent = ent
                            dragging    = True
                            sound_fx.play('pickup')
                            _is_party = not ent.is_enemy and not getattr(ent, 'is_npc', False)
                            if toolbar.active.get('group_move') and _is_party:
                                _gm_party = [c for c in characters if not getattr(c, 'is_npc', False)]
                                for e in _gm_party:
                                    undo_stack.append((e, e.x, e.y))
                                target_entity = None
                            else:
                                undo_stack.append((ent, ent.x, ent.y))
                                if target_entity is not None and target_entity is not ent:
                                    target_entity = None
                            if len(undo_stack) > MAX_UNDO:
                                del undo_stack[:len(undo_stack) - MAX_UNDO]
                            for c in characters: c.selected = (c == ent)
                            break
                    else:
                        # Clicked empty map space — clear targeting and begin pan
                        target_entity  = None
                        _map_panning   = True
                        _pan_last_pos  = pos

            elif event.button == 3:  # Right-click → context menu
                open_context_menu(*pos)

        # ── Mouse button up ────────────────────────────────────────────────
        elif event.type == pygame.MOUSEBUTTONUP:
            if getattr(event, 'touch', False):
                continue
            if dungeon_gen_dialog:
                dungeon_gen_dialog.mouse_up(event.pos)
            if toolbar._zoom_dragging:
                s = current_scene()
                if s:
                    db.save_scene_zoom(s[0], current_zoom)
            toolbar.handle_up()
            if event.button == 1 and zone_draw_mode and zone_draw_start:
                wx = event.pos[0] + camera_x
                wy = event.pos[1] - TOOLBAR_HEIGHT + camera_y
                x0, y0 = zone_draw_start
                zx, zy = min(x0, wx), min(y0, wy)
                zw, zh = abs(wx - x0), abs(wy - y0)
                if zw > 20 and zh > 20:
                    zone_dialog = SoundZoneDialog(zx, zy, zw, zh, font, WIDTH, HEIGHT)
                zone_draw_mode  = False
                zone_draw_start = None
                zone_draw_cur   = None
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)

            if event.button == 1:
                if aoe_tool.mode and aoe_tool.placing:
                    aoe_tool.place()
                if dragged_marker:
                    # Compare release to original press to distinguish tap from drag
                    if marker_drag_start:
                        moved_px = math.hypot(event.pos[0] - marker_drag_start[0],
                                              event.pos[1] - marker_drag_start[1])
                    else:
                        moved_px = 0
                    if moved_px < 6:
                        # Tap — switch to linked scene, auto-place return marker
                        # Transient (return) markers descend; permanent markers ascend
                        sound_fx.play('portal_return' if dragged_marker.id is None else 'portal')
                        _return_from_id   = scene_id()
                        _return_to_sid    = dragged_marker.to_scene_id
                        switch_scene(next((i for i, s in enumerate(scenes)
                                           if s[0] == _return_to_sid), 0))
                        # Place a return marker in the destination if none exists yet
                        _dest_sid = scene_id()
                        if (_dest_sid and _return_from_id
                                and _dest_sid != _return_from_id
                                and _dest_sid != start_scene_id):
                            _has_return = any(m.to_scene_id == _return_from_id
                                              for m in scene_markers)
                            if not _has_return:
                                _rx, _ry = _return_marker_pos()
                                _rname = next((s[1] for s in scenes
                                               if s[0] == _return_from_id), '???')
                                _tm = SceneMarker(None, _rx, _ry, _return_from_id, _rname)
                                scene_markers.append(_tm)
                                _add_transient_marker(_tm)
                    else:
                        # Drag — save new world position (skip temporary markers)
                        if dragged_marker.id is not None:
                            db.update_scene_marker_pos(dragged_marker.id,
                                                       dragged_marker.x, dragged_marker.y)
                    dragged_marker    = None
                    marker_drag_start = None
                if dragged_ent:
                    _is_party = not dragged_ent.is_enemy and not getattr(dragged_ent, 'is_npc', False)
                    if toolbar.active.get('group_move') and _is_party:
                        _gm_party = [c for c in characters if not getattr(c, 'is_npc', False)]
                        for ent in _gm_party:
                            if toolbar.active.get('grid_snap'):
                                ent.snap_to_grid(GRID_SIZE)
                            db.update_character_position(ent.id, int(ent.x), int(ent.y))
                    else:
                        if toolbar.active.get('grid_snap'):
                            dragged_ent.snap_to_grid(GRID_SIZE)
                        if dragged_ent.is_enemy:
                            db.update_enemy_position(dragged_ent.id,
                                int(dragged_ent.x), int(dragged_ent.y))
                        else:
                            db.update_character_position(dragged_ent.id,
                                int(dragged_ent.x), int(dragged_ent.y))
                    dragging    = False
                    dragged_ent = None
                if _map_panning:
                    _map_panning  = False
                    _pan_last_pos = None
                    s = current_scene()
                    if s:
                        db.update_scene_camera(s[0], int(camera_x), int(camera_y))
                    db.update_current_location(int(camera_x), int(camera_y))
            elif event.button == 3:
                for mk in scene_markers:
                    if mk.is_clicked(event.pos, camera_x, camera_y, TOOLBAR_HEIGHT):
                        if mk.id is not None:
                            db.delete_scene_marker(mk.id)
                        scene_markers.remove(mk)
                        break

        # ── Mouse motion ───────────────────────────────────────────────────
        elif event.type == pygame.MOUSEMOTION:
            if dungeon_gen_dialog:
                dungeon_gen_dialog.mouse_motion(event.pos)
            new_z = toolbar.handle_motion(event.pos)
            if new_z is not None:
                _apply_zoom(new_z, save=False)
            if zone_draw_mode and zone_draw_start:
                wx = event.pos[0] + camera_x
                wy = event.pos[1] - TOOLBAR_HEIGHT + camera_y
                zone_draw_cur = (wx, wy)
            if dragged_marker:
                dragged_marker.x = event.pos[0] + camera_x
                dragged_marker.y = event.pos[1] - TOOLBAR_HEIGHT + camera_y
            if dragging and dragged_ent:
                target_entity = None
                new_x = event.pos[0] + camera_x
                new_y = event.pos[1] - TOOLBAR_HEIGHT + camera_y
                _is_party = not dragged_ent.is_enemy and not getattr(dragged_ent, 'is_npc', False)
                if toolbar.active.get('group_move') and _is_party:
                    dx = new_x - dragged_ent.x
                    dy = new_y - dragged_ent.y
                    _gm_party = [c for c in characters if not getattr(c, 'is_npc', False)]
                    for ent in _gm_party:
                        ent.x += dx
                        ent.y += dy
                else:
                    dragged_ent.x = new_x
                    dragged_ent.y = new_y
            elif _map_panning and _pan_last_pos:
                dx = event.pos[0] - _pan_last_pos[0]
                dy = event.pos[1] - _pan_last_pos[1]
                _pan_last_pos = event.pos
                if layers:
                    for layer in layers:
                        layer.x += dx
                        layer.y += dy
                        layer.clamp(WIDTH, HEIGHT - TOOLBAR_HEIGHT)
                    camera_x, camera_y = -layers[0].x, -layers[0].y
                else:
                    camera_x = max(0.0, camera_x - dx)
                    camera_y = max(0.0, camera_y - dy)
            if aoe_tool.mode and aoe_tool.placing:
                wx = event.pos[0] + camera_x
                wy = event.pos[1] - TOOLBAR_HEIGHT + camera_y
                aoe_tool.update(wx, wy)
        # ── Mouse wheel ────────────────────────────────────────────────────
        elif event.type == pygame.MOUSEWHEEL:
            if group_hp_popup:
                group_hp_popup.scroll_list(-event.y)
            elif tta_browser:
                tta_browser.handle_event(event)

        # ── Keyboard ───────────────────────────────────────────────────────
        elif event.type == pygame.KEYDOWN:
            # New-scene choice popup
            if new_scene_popup:
                choice = new_scene_popup.key(event)
                if choice == 'cancel':
                    new_scene_popup = None
                continue
            # Dungeon gen dialog
            if dungeon_gen_dialog:
                ret = dungeon_gen_dialog.key(event)
                if isinstance(ret, tuple) and ret[0] == 'generate':
                    import time as _time
                    assets_dir = campaigns_mod.assets_path(active_campaign)
                    os.makedirs(assets_dir, exist_ok=True)
                    out_path = os.path.join(
                        assets_dir, f'dungeon_{int(_time.time())}.png')
                    if _pending_gen_path and os.path.exists(_pending_gen_path):
                        try: os.remove(_pending_gen_path)
                        except OSError: pass
                    _pending_gen_path = out_path
                    dungeon_gen_dialog.set_generating()
                    threading.Thread(target=_run_dungeon_gen,
                                     args=(ret[1], out_path), daemon=True).start()
                if dungeon_gen_dialog.done:
                    if dungeon_gen_dialog.result:
                        _accept_generated_scene()
                    else:
                        if _pending_gen_path and os.path.exists(_pending_gen_path):
                            try: os.remove(_pending_gen_path)
                            except OSError: pass
                    dungeon_gen_dialog = None
                continue
            # Confirm popup captures keys while open
            if confirm_popup:
                result = confirm_popup.key(event)
                if result is True:
                    _apply_confirm(confirm_popup._pending)
                    confirm_popup = None
                elif result is False:
                    confirm_popup = None
                continue
            # Group HP popup captures all keys while open
            if group_hp_popup:
                action, amt, ids = group_hp_popup.key(event)
                if action == 'close':
                    group_hp_popup = None
                elif action in ('damage', 'heal', 'full_heal'):
                    _apply_group_hp(action, amt, ids)
                    group_hp_popup = None
                continue
            # Number-input popup captures all keys while open
            if num_input_popup:
                kind, val = num_input_popup.key(event)
                if kind in ('confirm', 'cancel'):
                    apply_num_input(kind, val or 0)
                continue

            # HP popup typed-input captures keys when a field is focused
            if hp_popup and hp_popup.focus is not None:
                kind, val = hp_popup.key(event)
                if kind is not None:
                    _apply_hp_popup(kind, val)
                continue

            if _place_item_dialog:
                _place_item_dialog.handle_event(event)
                if _place_item_dialog.done:
                    if _place_item_dialog.result and _place_pending_pos:
                        r = _place_item_dialog.result
                        px, py = _place_pending_pos
                        new_id = db.add_scene_item(scene_id(), px, py,
                                                   r['radius'], r['dc'], r['description'])
                        hidden_items.append(HiddenItem(new_id, scene_id(), px, py,
                                                       r['radius'], r['dc'],
                                                       r['description'], False))
                    _place_item_dialog = None; _place_pending_pos = None
                continue

            if _place_trap_dialog:
                _place_trap_dialog.handle_event(event)
                if _place_trap_dialog.done:
                    if _place_trap_dialog.result and _place_pending_pos:
                        r = _place_trap_dialog.result
                        px, py = _place_pending_pos
                        new_id = db.add_scene_trap(scene_id(), px, py,
                                                   r['radius'], r['description'])
                        scene_traps_list.append(SceneTrap(new_id, scene_id(), px, py,
                                                          r['radius'], r['description'], False))
                    _place_trap_dialog = None; _place_pending_pos = None
                continue

            if _edit_item_dialog:
                _edit_item_dialog.handle_event(event)
                if _edit_item_dialog.done:
                    if _edit_item_dialog.result and _edit_item_obj:
                        r = _edit_item_dialog.result
                        db.update_scene_item(_edit_item_obj.id, r['dc'],
                                             r['description'], r['radius'])
                        _edit_item_obj.dc = r['dc']; _edit_item_obj.description = r['description']
                        _edit_item_obj.radius = r['radius']
                    _edit_item_dialog = None; _edit_item_obj = None
                continue

            if _edit_trap_dialog:
                _edit_trap_dialog.handle_event(event)
                if _edit_trap_dialog.done:
                    if _edit_trap_dialog.result and _edit_trap_obj:
                        r = _edit_trap_dialog.result
                        db.update_scene_trap(_edit_trap_obj.id,
                                             r['description'], r['radius'])
                        _edit_trap_obj.description = r['description']
                        _edit_trap_obj.radius = r['radius']
                    _edit_trap_dialog = None; _edit_trap_obj = None
                continue

            if dc_roll_popup:
                dc_roll_popup.handle_event(event)
                if dc_roll_popup.done:
                    item = dc_roll_popup.item; found = dc_roll_popup.result
                    dc_roll_popup = None
                    if found is True:
                        db.delete_scene_item(item.id)
                        hidden_items[:] = [i for i in hidden_items if i.id != item.id]
                        dc_result_popup = DCResultPopup(font, WIDTH, HEIGHT,
                                                        True, item.description)
                    elif found is False:
                        _item_cooldowns[item.id] = 300
                        dc_result_popup = DCResultPopup(font, WIDTH, HEIGHT, False, '')
                continue

            if dc_result_popup:
                dc_result_popup.handle_event(event)
                if dc_result_popup.done: dc_result_popup = None
                continue

            # TTA browser captures keys while open
            if tta_browser:
                result = tta_browser.handle_event(event)
                if result == 'close':
                    tta_browser = None
                elif result is not None:
                    if zone_dialog:
                        zone_dialog.set_track(result)
                    tta_browser = None
                continue

            # Zone dialog captures all keys while open
            if zone_dialog:
                res = zone_dialog.handle_event(event)
                _apply_zone_dialog(res)
                continue

            # Escape cancels zone draw mode
            if zone_draw_mode and event.key == pygame.K_ESCAPE:
                zone_draw_mode  = False
                zone_draw_start = None
                zone_draw_cur   = None
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
                continue

            # Campaign dialog captures all keys while open
            if campaign_dialog:
                action = campaign_dialog.handle_event(event)
                _apply_campaign_dialog(action)
                continue

            # Character dialog captures all keys while open
            if char_dialog:
                result = char_dialog.handle_event(event)
                if result == 'cancel':
                    sound_fx.play('cancel')
                    char_dialog = None
                elif result is not None:
                    apply_char_dialog(result)
                continue

            if enemy_dialog:
                result = enemy_dialog.handle_event(event)
                if result == 'cancel':
                    sound_fx.play('cancel')
                    enemy_dialog = None
                elif result is not None:
                    apply_enemy_dialog(result)
                continue

            # Size popup dismisses on Esc
            if size_popup:
                if event.key == pygame.K_ESCAPE:
                    size_popup = None
                continue

            # Notes panel captures keyboard when focused
            if notes_panel.visible and notes_panel.focused:
                if event.key == pygame.K_ESCAPE:
                    notes_panel.focused = False
                elif notes_panel.key(event):
                    db.save_notes(scene_id(), notes_panel.text)
                continue

            # Initiative panel inline edit
            if init_panel.editing_entity is not None:
                val = init_panel.key(event)
                if val is not None:
                    ent = init_panel.editing_entity
                    ent.initiative = val
                    if ent.is_enemy:
                        db.update_enemy_initiative(ent.id, val)
                    else:
                        db.update_character_initiative(ent.id, val)
                    rebuild_initiative()
                continue

            # Scene rename
            if renaming_scene:
                if event.key == pygame.K_RETURN:
                    if scenes and scene_new_name.strip():
                        s = current_scene()
                        db.rename_scene(s[0], scene_new_name)
                        scenes[current_scene_idx] = (s[0], scene_new_name,
                                                     s[2], s[3], s[4])
                    renaming_scene = False
                elif event.key == pygame.K_ESCAPE:
                    renaming_scene = False
                elif event.key == pygame.K_BACKSPACE:
                    scene_new_name = scene_new_name[:-1]
                elif event.unicode:
                    scene_new_name += event.unicode
                continue

            # Character rename
            if renaming_char:
                if event.key == pygame.K_RETURN:
                    renaming_char.name = new_name
                    if renaming_char.is_enemy:
                        db.update_enemy_name(renaming_char.id, new_name)
                    else:
                        db.update_character_name(renaming_char.id, new_name)
                    renaming_char = None
                elif event.key == pygame.K_BACKSPACE:
                    new_name = new_name[:-1]
                else:
                    new_name += event.unicode
                continue

            if event.key == pygame.K_INSERT:
                mx, my = pygame.mouse.get_pos()
                wx  = int(mx + camera_x)
                wy  = int(my - TOOLBAR_HEIGHT + camera_y)
                sid = scene_id()
                new_id = db.insert_enemy('New Enemy', wx, wy, sid)
                ent = Character(wx, wy, pygame.Color('#c0392b'), 15, 'New Enemy',
                                id=new_id, is_enemy=True)
                ent.hp = ent.max_hp = 10
                ent.scene_id = sid
                enemies.append(ent)
                rebuild_initiative()

            elif event.key == pygame.K_ESCAPE:
                if stat_block_panel:
                    stat_block_panel = None

            elif event.key == pygame.K_DELETE:
                # Remove selected entity
                sel = next((e for e in enemies if e.selected), None) or \
                      next((e for e in characters if e.selected), None)
                if sel:
                    if sel.is_enemy:
                        db.delete_enemy(sel.id); enemies.remove(sel)
                    else:
                        db.delete_character(sel.id); characters.remove(sel)
                    rebuild_initiative()
                    if target_entity is sel:
                        target_entity = None
                    if stat_block_panel and stat_block_panel.entity is sel:
                        stat_block_panel = None

            elif event.key == pygame.K_F2:
                sel = next((e for e in characters + enemies if e.selected), None)
                if sel:
                    renaming_char = sel; new_name = sel.name

            elif event.key == pygame.K_z and (event.mod & pygame.KMOD_CTRL):
                handle_toolbar('undo')

            elif event.key == pygame.K_PAGEUP:
                handle_toolbar('prev_turn')
            elif event.key == pygame.K_PAGEDOWN:
                handle_toolbar('next_turn')

    # ── Camera movement (keyboard) ────────────────────────────────────────────
    keys = pygame.key.get_pressed()
    dx   = (keys[pygame.K_RIGHT] - keys[pygame.K_LEFT]) * speed
    dy   = (keys[pygame.K_DOWN]  - keys[pygame.K_UP])   * speed

    if pygame.key.get_mods() & pygame.KMOD_SHIFT:
        if dx or dy:
            target_entity = None
        for char in characters:
            if getattr(char, 'is_npc', False):
                continue
            char.x += dx; char.y += dy
            db.update_character_position(char.id, int(char.x), int(char.y))
    else:
        if dx or dy:
            target_entity = None
            camera_x = max(0.0, camera_x + dx)
            camera_y = max(0.0, camera_y + dy)
            for layer in layers:
                layer.x = -camera_x
                layer.y = -camera_y
                layer.clamp(WIDTH, HEIGHT - TOOLBAR_HEIGHT)
            if layers:
                camera_x, camera_y = -layers[0].x, -layers[0].y
            db.update_current_location(int(camera_x), int(camera_y))
            _s = current_scene()
            if _s:
                db.update_scene_camera(_s[0], int(camera_x), int(camera_y))

    # Update fog edit mode from toolbar
    fog.edit        = toolbar.active.get('fog_on', False)
    aoe_tool.mode   = toolbar.get_aoe_mode()
    measure_tool.active = toolbar.active.get('measure', False)

    # ── Draw ──────────────────────────────────────────────────────────────────
    screen.fill(BLACK)

    # Map layers (offset by TOOLBAR_HEIGHT)
    map_surf = pygame.Surface((WIDTH, HEIGHT - TOOLBAR_HEIGHT))
    map_surf.fill(BLACK)
    for layer in layers:
        # Re-blit layer onto map sub-surface
        map_surf.blit(layer.img, (int(layer.x), int(layer.y)))
    screen.blit(map_surf, (0, TOOLBAR_HEIGHT))

    # World-aligned scrolling grid
    if toolbar.active.get('show_grid', True):
        draw_grid(screen, camera_x, camera_y, WIDTH, HEIGHT, TOOLBAR_HEIGHT)

    # Fog of war — only active while Fog On toggle is on
    _party_chars = [c for c in characters if not getattr(c, 'is_npc', False)]
    if fog.edit:
        fog.draw(screen, camera_x, camera_y, WIDTH, HEIGHT, TOOLBAR_HEIGHT,
                 vision_sources=[(c.x, c.y) for c in _party_chars],
                 vision_radius=_current_vision_radius())

    # AoE templates
    aoe_tool.draw(screen, camera_x, camera_y, TOOLBAR_HEIGHT)

    # Measure tool
    measure_tool.draw(screen, camera_x, camera_y, TOOLBAR_HEIGHT, font)

    # Sound zones (drawn beneath tokens) — hidden when fog of war is active
    if show_zones and not fog.edit:
        for z in sound_zones:
            z.draw(screen, camera_x, camera_y, TOOLBAR_HEIGHT, small_font,
                   active=(z.id == active_zone_id))
        # Zone draw preview
        if zone_draw_mode and zone_draw_start and zone_draw_cur:
            x0, y0 = zone_draw_start; x1, y1 = zone_draw_cur
            px = int(min(x0, x1) - camera_x)
            py = int(min(y0, y1) - camera_y) + TOOLBAR_HEIGHT
            pw = int(abs(x1 - x0)); ph = int(abs(y1 - y0))
            if pw > 2 and ph > 2:
                ov = pygame.Surface((pw, ph), pygame.SRCALPHA)
                ov.fill((68, 136, 255, 40))
                screen.blit(ov, (px, py))
                pygame.draw.rect(screen, (140, 200, 255), (px, py, pw, ph), 2)

    # Scene markers
    for mk in scene_markers:
        mk.draw(screen, camera_x, camera_y, TOOLBAR_HEIGHT, small_font)

    # Characters
    _fog_vr = _current_vision_radius() if fog.edit else 0
    for char in characters:
        if fog.edit and not build_mode and getattr(char, 'is_npc', False):
            # NPC: hide unless a party member's vision circle covers them
            if not any(math.hypot(char.x - c.x, char.y - c.y) <= _fog_vr
                       for c in _party_chars):
                continue
        is_turn = (initiative_order and
                   current_turn_idx < len(initiative_order) and
                   initiative_order[current_turn_idx] is char)
        char.draw(screen, camera_x, camera_y - TOOLBAR_HEIGHT,
                  current_turn=is_turn, font=font, small_font=small_font)

    # Enemies (visible on screen, hidden if fog covers their cell)
    for ent in enemies:
        sx = ent.x - camera_x
        sy = ent.y - camera_y
        if -ent.size <= sx <= WIDTH + ent.size and -ent.size <= sy <= HEIGHT + ent.size:
            if fog.edit:
                vr = _current_vision_radius()
                if not any(math.hypot(ent.x - c.x, ent.y - c.y) <= vr
                           for c in _party_chars):
                    continue
            is_turn = (initiative_order and
                       current_turn_idx < len(initiative_order) and
                       initiative_order[current_turn_idx] is ent)
            if ent.initiative == 0:
                ent.initiative = random.randint(1, 20)
                db.update_enemy_initiative(ent.id, ent.initiative)
                rebuild_initiative()
            ent.draw(screen, camera_x, camera_y - TOOLBAR_HEIGHT,
                     current_turn=is_turn, font=font, small_font=small_font)

    # Targeting reticle (drawn on top of all entities)
    if target_entity and not _is_fog_hidden(target_entity):
        draw_targeting_reticle(screen, target_entity, camera_x, camera_y)

    # ── Hidden items & traps visual indicators ─────────────────────────────────
    # Visibility rules:
    #   Build Mode ON  → show everything (DM editing/setup view)
    #   Fog ON         → items hidden; traps shown only in player vision circles
    #   Fog OFF        → items hidden; only triggered traps shown
    fog_on = toolbar.active.get('fog_on', True)
    for item in hidden_items:
        if item.found:
            continue
        if not build_mode:
            continue  # hidden items invisible in all play modes
        sx = int(item.x - camera_x)
        sy = int(item.y - camera_y) + TOOLBAR_HEIGHT
        pygame.draw.circle(screen, (220, 50, 50), (sx, sy), 5)
        pygame.draw.circle(screen, (255, 150, 150), (sx, sy), 3)

    for trap in scene_traps_list:
        if not build_mode and not trap.triggered:
            continue  # untriggered traps invisible during play
        if not build_mode and trap.triggered and fog_on:
            _vr = _current_vision_radius()
            if not any(math.hypot(trap.x - c.x, trap.y - c.y) <= _vr
                       for c in characters):
                continue  # triggered trap outside all vision circles — still fogged
        sx = int(trap.x - camera_x)
        sy = int(trap.y - camera_y) + TOOLBAR_HEIGHT
        if trap.triggered:
            # Triggered: bright red filled circle + exclamation so it's hard to miss
            pygame.draw.circle(screen, (180, 0, 0),   (sx, sy), 12)
            pygame.draw.circle(screen, (255, 80, 80), (sx, sy), 10)
            t_lbl = font.render('!', True, (255, 255, 255))
        else:
            # Build-mode indicator: subtle red T
            t_lbl = font.render('T', True, (220, 50, 50))
        screen.blit(t_lbl, (sx - t_lbl.get_width() // 2,
                             sy - t_lbl.get_height() // 2))

    # Trap flash overlay
    if trap_flash_timer > 0:
        alpha = min(160, int(160 * trap_flash_timer / 45))
        flash_surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        flash_surf.fill((220, 30, 30, alpha))
        screen.blit(flash_surf, (0, 0))

    # Legends
    draw_char_legend(renaming_char, new_name)

    # Notes panel (left side, before init panel so both can be open at once)
    if notes_panel.visible:
        notes_panel.draw(screen, WIDTH, HEIGHT, scene_name())

    # Initiative panel
    init_panel.draw(screen, vis_order, vis_idx, WIDTH, HEIGHT)

    # Toolbar (drawn last so it's always on top)
    _sname = scene_name()
    if start_scene_id and scene_id() == start_scene_id:
        _sname = '* ' + _sname
    _turn_name = vis_order[vis_idx].name if vis_order and 0 <= vis_idx < len(vis_order) else ''
    toolbar.draw(screen, WIDTH, _sname, vis_idx, len(vis_order), _turn_name)

    # Scene rename overlay — blue edit box replaces the scene name label
    if renaming_scene:
        r = toolbar._sc_r.get('name')
        if r:
            pygame.draw.rect(screen, (0, 80, 160), r, border_radius=4)
            pygame.draw.rect(screen, (80, 160, 255), r, 2, border_radius=4)
            blink = (pygame.time.get_ticks() // 500) % 2 == 0
            t = tb_font.render(scene_new_name + ('|' if blink else ''), True, WHITE)
            clip = pygame.Rect(r.left + 4, r.top + 2, r.width - 8, r.height - 4)
            old_clip = screen.get_clip()
            screen.set_clip(clip)
            screen.blit(t, (r.left + 6, r.centery - t.get_height() // 2))
            screen.set_clip(old_clip)

    # Popups (topmost)
    if stat_block_panel: stat_block_panel.draw(screen)
    if group_hp_popup:   group_hp_popup.draw(screen)
    if hp_popup:         hp_popup.draw(screen)
    if conditions_popup: conditions_popup.draw(screen)
    if context_menu:     context_menu.draw_labeled(screen)
    if char_dialog:      char_dialog.draw(screen)
    if enemy_dialog:     enemy_dialog.draw(screen)
    if size_popup:       size_popup.draw(screen)
    if num_input_popup:  num_input_popup.draw(screen)
    if confirm_popup:    confirm_popup.draw(screen)
    if scene_picker:     scene_picker.draw(screen)
    if campaign_dialog:    campaign_dialog.draw(screen)
    if zone_dialog:        zone_dialog.draw(screen)
    if tta_browser:
        if _tta_songlist is not None and tta_browser._loading:
            tta_browser.update_songlist(_tta_songlist)
        tta_browser.draw(screen)
    if _place_item_dialog: _place_item_dialog.draw(screen)
    if _place_trap_dialog: _place_trap_dialog.draw(screen)
    if _edit_item_dialog:  _edit_item_dialog.draw(screen)
    if _edit_trap_dialog:  _edit_trap_dialog.draw(screen)
    if lock_overlay:       lock_overlay.draw(screen)
    if dc_roll_popup:      dc_roll_popup.draw(screen)
    if dc_result_popup:    dc_result_popup.draw(screen)
    if new_scene_popup:    new_scene_popup.draw(screen)
    if dungeon_gen_dialog:
        dungeon_gen_dialog.tick()
        dungeon_gen_dialog.draw(screen)
    # Spawn the hint popup on the first rendered frame so the map is visible behind it
    if _init_msg_pending and init_msg_popup is None:
        _init_msg_text = _load_init_msg()
        if _init_msg_text:
            init_msg_popup = HintPopup(font, small_font, WIDTH, HEIGHT, _init_msg_text,
                                       qr_url='https://github.com/coolfuton8/RealmScape')
        _init_msg_pending = False

    if init_msg_popup:         init_msg_popup.draw(screen)
    if build_mode_hint:        build_mode_hint.draw(screen)

    # Check dungeongen background thread for completion
    if dungeon_gen_dialog and not _gen_queue.empty():
        gen_result = _gen_queue.get_nowait()
        if gen_result['status'] == 'ok':
            _pending_gen_path = gen_result['path']
            dungeon_gen_dialog.set_preview(gen_result['path'])
        else:
            dungeon_gen_dialog.set_error(gen_result['error'])

    # Self-update — surface the result of a "Check for Updates" click, or a
    # silent startup check (which only ever speaks up if one is available).
    if not _update_check_queue.empty():
        _upd = _update_check_queue.get_nowait()
        _update_check_in_progress = False
        if _upd['latest'] and _upd['startup']:
            _pending_update_notice = _upd   # shown below once init_msg_popup is free
        elif _upd['latest']:
            confirm_popup = ConfirmPopup(
                f"A new version of RealmScape is available!\n\n"
                f"Installed: v{updater.get_current_version()}\n"
                f"Available: v{_upd['latest']}\n\n"
                f"Download and install it now?\n"
                f"Your campaigns will not be affected.",
                font, WIDTH, HEIGHT)
            confirm_popup._pending = 'app_update'
        elif _upd['startup']:
            pass   # up-to-date / check failed — stay quiet on a silent startup check
        elif _upd['error']:
            init_msg_popup = HintPopup(font, small_font, WIDTH, HEIGHT,
                f"Could not check for updates:\n\n{_upd['error']}",
                title='Update Check Failed')
        else:
            init_msg_popup = HintPopup(font, small_font, WIDTH, HEIGHT,
                f"You're running the latest version "
                f"(v{updater.get_current_version()}).",
                title='Up To Date')

    # Show the startup "update available" notice once the message slot frees
    # up (won't interrupt/clobber the campaign's Initial Message popup).
    if _pending_update_notice is not None and init_msg_popup is None:
        init_msg_popup = HintPopup(font, small_font, WIDTH, HEIGHT,
            f"A new version of RealmScape is available!\n\n"
            f"Installed: v{updater.get_current_version()}\n"
            f"Available: v{_pending_update_notice['latest']}\n\n"
            f"To install it, open Campaign -> Check for Updates.",
            title='Update Available')
        _pending_update_notice = None

    # Self-update — surface the result of an in-progress download/install
    if not _update_apply_queue.empty():
        _updr = _update_apply_queue.get_nowait()
        _update_apply_in_progress = False
        init_msg_popup = HintPopup(font, small_font, WIDTH, HEIGHT, _updr['message'],
            title='Update Complete' if _updr['success'] else 'Update Failed')

    # Load a cached audio file signalled by the download thread
    with _pending_music_lock:
        _pm, _pending_music = _pending_music, None
    if _pm and music_enabled:
        try:
            pygame.mixer.music.load(_pm)
            pygame.mixer.music.play(-1)
        except Exception as _e:
            print(f'[Audio] play cached: {_e}')

    press_fx.draw(screen)
    draw_hotspot_overlay(screen, font, small_font)

    try:
        pygame.display.flip()
    except pygame.error:
        pass  # transient GL context conflict; skip frame, next will succeed
    clock.tick(60)

# ── Cleanup ───────────────────────────────────────────────────────────────────
_stop_all_audio_sync()
if tta_browser:
    tta_browser._stop_preview()
_save_current_scene_state()
if not current_scene():
    db.save_notes(0, notes_panel.text)
db.update_current_location(int(camera_x), int(camera_y))
pygame.quit()
