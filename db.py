# db.py  –  all SQLite access
import sqlite3
import json

DB_PATH = 'characters.db'   # overridden at startup via set_db_path()

def set_db_path(path: str):
    global DB_PATH
    DB_PATH = path

def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def _add_col(cursor, table, col, col_type, default):
    cursor.execute(f"PRAGMA table_info({table})")
    if col not in [r[1] for r in cursor.fetchall()]:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type} DEFAULT {default}")

# ── Schema ────────────────────────────────────────────────────────────────────

def init_db():
    conn = _conn(); c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS window_state (
        id INTEGER PRIMARY KEY CHECK(id=1),
        width INTEGER NOT NULL DEFAULT 800,
        height INTEGER NOT NULL DEFAULT 600,
        x INTEGER NOT NULL DEFAULT 100,
        y INTEGER NOT NULL DEFAULT 100,
        image_path TEXT DEFAULT '',
        start_scene_id INTEGER NOT NULL DEFAULT 0
    )""")
    c.execute("INSERT OR IGNORE INTO window_state(id,width,height,x,y,image_path,start_scene_id) VALUES (1,800,600,100,100,'',0)")

    c.execute("""CREATE TABLE IF NOT EXISTS characters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        x INTEGER NOT NULL DEFAULT 100,
        y INTEGER NOT NULL DEFAULT 100,
        color TEXT NOT NULL DEFAULT '#3498db',
        size INTEGER NOT NULL DEFAULT 20,
        image_path TEXT,
        hp INTEGER DEFAULT 10,
        max_hp INTEGER DEFAULT 10,
        conditions TEXT DEFAULT '',
        initiative INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS enemies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        x INTEGER NOT NULL DEFAULT 400,
        y INTEGER NOT NULL DEFAULT 300,
        color TEXT NOT NULL DEFAULT '#c0392b',
        size INTEGER NOT NULL DEFAULT 15,
        image_path TEXT,
        hp INTEGER DEFAULT 10,
        max_hp INTEGER DEFAULT 10,
        conditions TEXT DEFAULT '',
        initiative INTEGER DEFAULT 0,
        scene_id INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS current_location (
        id INTEGER PRIMARY KEY CHECK(id=1),
        x INTEGER NOT NULL DEFAULT 0,
        y INTEGER NOT NULL DEFAULT 0
    )""")
    c.execute("INSERT OR IGNORE INTO current_location VALUES (1,0,0)")

    c.execute("""CREATE TABLE IF NOT EXISTS scenes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        image_path TEXT DEFAULT '',
        camera_x INTEGER DEFAULT 0,
        camera_y INTEGER DEFAULT 0,
        fog_on INTEGER DEFAULT 1,
        fog_radius INTEGER DEFAULT 6,
        zoom REAL DEFAULT 1.0
    )""")
    # Migrate existing DBs that lack newer columns
    for col, default in [('fog_on', 1), ('fog_radius', 6), ('zoom', 1.0)]:
        try:
            c.execute(f'ALTER TABLE scenes ADD COLUMN {col} DEFAULT {default}')
        except Exception:
            pass
    try:
        c.execute('ALTER TABLE characters ADD COLUMN is_npc INTEGER DEFAULT 0')
    except Exception:
        pass
    try:
        c.execute('ALTER TABLE characters ADD COLUMN scene_id INTEGER DEFAULT 0')
    except Exception:
        pass

    c.execute("""CREATE TABLE IF NOT EXISTS character_positions (
        character_id INTEGER,
        scene_id     INTEGER,
        x            REAL,
        y            REAL,
        PRIMARY KEY (character_id, scene_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS scene_markers (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        from_scene_id INTEGER NOT NULL,
        to_scene_id   INTEGER NOT NULL,
        x             REAL    NOT NULL,
        y             REAL    NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS fog_of_war (
        scene_id INTEGER PRIMARY KEY,
        revealed_cells TEXT DEFAULT '[]'
    )""")
    c.execute("INSERT OR IGNORE INTO fog_of_war VALUES (0,'[]')")

    c.execute("""CREATE TABLE IF NOT EXISTS dm_notes (
        scene_id INTEGER PRIMARY KEY,
        text     TEXT DEFAULT ''
    )""")
    c.execute("INSERT OR IGNORE INTO dm_notes VALUES (0,'')")

    c.execute("""CREATE TABLE IF NOT EXISTS sound_zones (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT    NOT NULL DEFAULT 'Zone',
        x          REAL    NOT NULL DEFAULT 0,
        y          REAL    NOT NULL DEFAULT 0,
        w          REAL    NOT NULL DEFAULT 200,
        h          REAL    NOT NULL DEFAULT 200,
        track      TEXT    NOT NULL DEFAULT '',
        color      TEXT    NOT NULL DEFAULT '#4488ff',
        scene_id   INTEGER NOT NULL DEFAULT 0,
        is_default INTEGER NOT NULL DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS stat_blocks (
        entity_type TEXT    NOT NULL,
        entity_id   INTEGER NOT NULL,
        ac          INTEGER DEFAULT 10,
        speed       INTEGER DEFAULT 30,
        str_score   INTEGER DEFAULT 10,
        dex_score   INTEGER DEFAULT 10,
        con_score   INTEGER DEFAULT 10,
        int_score   INTEGER DEFAULT 10,
        wis_score   INTEGER DEFAULT 10,
        cha_score   INTEGER DEFAULT 10,
        PRIMARY KEY (entity_type, entity_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS scene_items (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        scene_id    INTEGER NOT NULL,
        x           REAL    NOT NULL,
        y           REAL    NOT NULL,
        radius      REAL    NOT NULL DEFAULT 50,
        dc          INTEGER NOT NULL DEFAULT 15,
        description TEXT    NOT NULL DEFAULT '',
        found       INTEGER NOT NULL DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS scene_traps (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        scene_id    INTEGER NOT NULL,
        x           REAL    NOT NULL,
        y           REAL    NOT NULL,
        radius      REAL    NOT NULL DEFAULT 50,
        description TEXT    NOT NULL DEFAULT '',
        triggered   INTEGER NOT NULL DEFAULT 0
    )""")

    conn.commit()

    # Back-compat: add new columns to existing tables
    _add_col(c, 'sound_zones',   'is_default',    'INTEGER', 0)
    _add_col(c, 'window_state',  'music_enabled',  'INTEGER', 1)
    _add_col(c, 'window_state',  'hints_enabled',  'INTEGER', 1)
    for col, typ, dflt in [('image_path','TEXT',"''"), ('start_scene_id','INTEGER','0')]:
        _add_col(c, 'window_state', col, typ, dflt)
    for col, typ, dflt in [
        ('hp','INTEGER','10'), ('max_hp','INTEGER','10'),
        ('conditions','TEXT',"''"), ('initiative','INTEGER','0'),
    ]:
        _add_col(c, 'characters', col, typ, dflt)
        _add_col(c, 'enemies',    col, typ, dflt)
    _add_col(c, 'enemies',    'scene_id',   'INTEGER', '0')
    _add_col(c, 'characters', 'init_bonus', 'INTEGER', '0')
    _add_col(c, 'scenes',     'show_grid',  'INTEGER', '1')

    c.execute("""CREATE TABLE IF NOT EXISTS scene_snapshots (
        scene_id INTEGER PRIMARY KEY,
        snapshot_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT ''
    )""")

    conn.commit(); conn.close()

# ── Window state ──────────────────────────────────────────────────────────────

def get_window_state():
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT width,height,x,y,image_path FROM window_state WHERE id=1')
    r = c.fetchone(); conn.close()
    return {'width':r[0],'height':r[1],'x':r[2],'y':r[3],'image_path':r[4]} if r \
           else {'width':800,'height':600,'x':100,'y':100,'image_path':''}

def get_music_enabled():
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT music_enabled FROM window_state WHERE id=1')
    r = c.fetchone(); conn.close()
    return bool(r[0]) if r else True

def set_music_enabled(val):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE window_state SET music_enabled=? WHERE id=1', (1 if val else 0,))
    conn.commit(); conn.close()

def get_hints_enabled():
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT hints_enabled FROM window_state WHERE id=1')
    r = c.fetchone(); conn.close()
    return bool(r[0]) if r else True

def set_hints_enabled(val):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE window_state SET hints_enabled=? WHERE id=1', (1 if val else 0,))
    conn.commit(); conn.close()

def get_hints_enabled_for(db_path: str) -> bool:
    """Read hints_enabled from any campaign DB by file path."""
    try:
        import sqlite3
        con = sqlite3.connect(db_path)
        r = con.execute('SELECT hints_enabled FROM window_state WHERE id=1').fetchone()
        con.close()
        return bool(r[0]) if r else True
    except Exception:
        return True

def set_hints_enabled_for(db_path: str, val: bool):
    """Write hints_enabled to any campaign DB by file path."""
    try:
        import sqlite3
        con = sqlite3.connect(db_path)
        con.execute('UPDATE window_state SET hints_enabled=? WHERE id=1', (1 if val else 0,))
        con.commit()
        con.close()
    except Exception:
        pass

def get_start_scene_id():
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT start_scene_id FROM window_state WHERE id=1')
    r = c.fetchone(); conn.close()
    return int(r[0]) if r else 0

def set_start_scene_id(scene_id):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE window_state SET start_scene_id=? WHERE id=1', (int(scene_id),))
    conn.commit(); conn.close()

def update_window_state(width, height, x, y, image_path=None):
    conn = _conn(); c = conn.cursor()
    if image_path is not None:
        image_path = image_path.replace('\\', '/')
        c.execute('UPDATE window_state SET width=?,height=?,x=?,y=?,image_path=? WHERE id=1',
                  (width,height,x,y,image_path))
    else:
        c.execute('UPDATE window_state SET width=?,height=?,x=?,y=? WHERE id=1',
                  (width,height,x,y))
    conn.commit(); conn.close()

# ── Camera location ───────────────────────────────────────────────────────────

def get_current_location():
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT x,y FROM current_location WHERE id=1')
    r = c.fetchone(); conn.close()
    return r if r else (0,0)

def update_current_location(x, y):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE current_location SET x=?,y=? WHERE id=1', (x,y))
    conn.commit(); conn.close()

# ── Characters ────────────────────────────────────────────────────────────────

def ensure_default_characters():
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM characters')
    if c.fetchone()[0] == 0:
        c.executemany(
            'INSERT INTO characters(name,x,y,color,size,image_path,hp,max_hp,conditions,initiative)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?)',
            [('Fighter',100,100,'#e74c3c',20,None,30,30,'',0),
             ('Wizard', 200,200,'#3498db',20,None,14,14,'',0),
             ('Rogue',  300,300,'#2ecc71',20,None,22,22,'',0)]
        )
        conn.commit()
    conn.close()

_CHAR_COLS = 'id,name,x,y,color,size,image_path,hp,max_hp,conditions,initiative,is_npc,scene_id,init_bonus'

def load_global_characters():
    """Load party members (scene_id=0, is_npc=0)."""
    conn = _conn(); c = conn.cursor()
    c.execute(f'SELECT {_CHAR_COLS} FROM characters WHERE scene_id=0 AND is_npc=0')
    rows = c.fetchall(); conn.close(); return rows

def load_scene_npcs(scene_id):
    """Load NPCs that belong to a specific scene."""
    conn = _conn(); c = conn.cursor()
    c.execute(f'SELECT {_CHAR_COLS} FROM characters WHERE scene_id=? AND is_npc=1', (scene_id,))
    rows = c.fetchall(); conn.close(); return rows

def insert_character(name, x, y, color, size, hp, max_hp, is_npc=False, scene_id=0):
    conn = _conn(); c = conn.cursor()
    c.execute(
        "INSERT INTO characters(name,x,y,color,size,hp,max_hp,conditions,initiative,is_npc,scene_id)"
        " VALUES(?,?,?,?,?,?,?,'',0,?,?)",
        (name, x, y, color, size, hp, max_hp, int(is_npc), scene_id)
    )
    new_id = c.lastrowid; conn.commit(); conn.close(); return new_id

def update_character_is_npc(id, is_npc):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE characters SET is_npc=? WHERE id=?', (int(is_npc), id))
    conn.commit(); conn.close()

def update_character_scene_id(id, scene_id):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE characters SET scene_id=? WHERE id=?', (scene_id, id))
    conn.commit(); conn.close()

def update_character_color(id, color):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE characters SET color=? WHERE id=?', (color, id))
    conn.commit(); conn.close()

def update_character_size(id, size):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE characters SET size=? WHERE id=?', (size, id))
    conn.commit(); conn.close()

def update_character_position(id, x, y):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE characters SET x=?,y=? WHERE id=?',(x,y,id))
    conn.commit(); conn.close()

def save_character_positions(scene_id, positions):
    """Overwrite [(char_id, x, y), ...] for a scene."""
    conn = _conn(); c = conn.cursor()
    c.executemany(
        'INSERT OR REPLACE INTO character_positions VALUES(?,?,?,?)',
        [(cid, scene_id, x, y) for cid, x, y in positions]
    )
    conn.commit(); conn.close()

def seed_character_positions(scene_id, positions):
    """INSERT OR IGNORE [(char_id, x, y), ...] — only fills in missing entries."""
    conn = _conn(); c = conn.cursor()
    c.executemany(
        'INSERT OR IGNORE INTO character_positions VALUES(?,?,?,?)',
        [(cid, scene_id, x, y) for cid, x, y in positions]
    )
    conn.commit(); conn.close()

def get_all_scene_ids():
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT id FROM scenes')
    ids = [r[0] for r in c.fetchall()]; conn.close()
    return ids

def load_character_positions(scene_id):
    """Return {char_id: (x, y)} for the given scene."""
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT character_id, x, y FROM character_positions WHERE scene_id=?', (scene_id,))
    return {r[0]: (float(r[1]), float(r[2])) for r in c.fetchall()}

def update_character_name(id, name):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE characters SET name=? WHERE id=?',(name,id))
    conn.commit(); conn.close()

def update_character_image_path(id, path):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE characters SET image_path=? WHERE id=?',(path.replace('\\', '/'),id))
    conn.commit(); conn.close()

def update_character_hp(id, hp):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE characters SET hp=? WHERE id=?',(hp,id))
    conn.commit(); conn.close()

def update_character_max_hp(id, max_hp):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE characters SET max_hp=? WHERE id=?',(max_hp,id))
    conn.commit(); conn.close()

def update_character_conditions(id, cond_str):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE characters SET conditions=? WHERE id=?',(cond_str,id))
    conn.commit(); conn.close()

def update_character_init_bonus(id, bonus):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE characters SET init_bonus=? WHERE id=?', (bonus, id))
    conn.commit(); conn.close()

def update_character_initiative(id, initiative):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE characters SET initiative=? WHERE id=?',(initiative,id))
    conn.commit(); conn.close()

def delete_character(id):
    conn = _conn(); c = conn.cursor()
    c.execute('DELETE FROM characters WHERE id=?',(id,))
    conn.commit(); conn.close()

# ── Enemies ───────────────────────────────────────────────────────────────────

def ensure_default_enemies():
    conn = _conn(); c = conn.cursor()
    # Only seed starter enemies on a brand-new campaign (no scenes yet).
    # An established campaign with all enemies cleaned up should stay empty.
    c.execute('SELECT COUNT(*) FROM scenes')
    if c.fetchone()[0] > 0:
        conn.close(); return
    c.execute('SELECT COUNT(*) FROM enemies')
    if c.fetchone()[0] == 0:
        c.executemany(
            'INSERT INTO enemies(name,x,y,color,size,image_path,hp,max_hp,conditions,initiative,scene_id)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            [('Goblin',400,200,'#c0392b',15,None, 7, 7,'',0,0),
             ('Orc',   600,350,'#e67e22',20,None,15,15,'',0,0),
             ('Troll', 800,500,'#27ae60',25,None,84,84,'',0,0)]
        )
        conn.commit()
    conn.close()

def load_enemies_from_db(scene_id=0):
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT id,name,x,y,color,size,image_path,hp,max_hp,conditions,initiative,scene_id'
              ' FROM enemies WHERE scene_id=? OR scene_id=0', (scene_id,))
    rows = c.fetchall(); conn.close(); return rows

def insert_enemy(name, x, y, scene_id=0):
    conn = _conn(); c = conn.cursor()
    c.execute('INSERT INTO enemies(name,x,y,color,size,hp,max_hp,conditions,initiative,scene_id)'
              " VALUES(?,%,?,'#c0392b',15,10,10,'',0,?)".replace('%','?'),
              (name, x, y, scene_id))
    new_id = c.lastrowid
    conn.commit(); conn.close(); return new_id

def update_enemy_position(id, x, y):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE enemies SET x=?,y=? WHERE id=?',(x,y,id))
    conn.commit(); conn.close()

def update_enemy_name(id, name):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE enemies SET name=? WHERE id=?',(name,id))
    conn.commit(); conn.close()

def update_enemy_color(id, color):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE enemies SET color=? WHERE id=?',(color,id))
    conn.commit(); conn.close()

def update_enemy_image_path(id, path):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE enemies SET image_path=? WHERE id=?',(path.replace('\\', '/'),id))
    conn.commit(); conn.close()

def update_enemy_hp(id, hp):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE enemies SET hp=? WHERE id=?',(hp,id))
    conn.commit(); conn.close()

def update_enemy_max_hp(id, max_hp):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE enemies SET max_hp=? WHERE id=?',(max_hp,id))
    conn.commit(); conn.close()

def update_enemy_conditions(id, cond_str):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE enemies SET conditions=? WHERE id=?',(cond_str,id))
    conn.commit(); conn.close()

def update_enemy_initiative(id, initiative):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE enemies SET initiative=? WHERE id=?',(initiative,id))
    conn.commit(); conn.close()

def update_enemy_size(id, size):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE enemies SET size=? WHERE id=?', (size, id))
    conn.commit(); conn.close()

def update_enemy_scene(enemy_id, new_scene_id):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE enemies SET scene_id=? WHERE id=?', (new_scene_id, enemy_id))
    conn.commit(); conn.close()

def delete_enemy(id):
    conn = _conn(); c = conn.cursor()
    c.execute('DELETE FROM enemies WHERE id=?',(id,))
    conn.commit(); conn.close()

# ── Scenes ────────────────────────────────────────────────────────────────────

def get_all_scenes():
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT id,name,image_path,camera_x,camera_y FROM scenes ORDER BY id')
    rows = c.fetchall(); conn.close(); return rows

def add_scene(name, image_path='', camera_x=0, camera_y=0):
    conn = _conn(); c = conn.cursor()
    image_path = image_path.replace('\\', '/')
    c.execute('INSERT INTO scenes(name,image_path,camera_x,camera_y) VALUES(?,?,?,?)',
              (name,image_path,camera_x,camera_y))
    new_id = c.lastrowid; conn.commit(); conn.close(); return new_id

def update_scene_camera(scene_id, camera_x, camera_y):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE scenes SET camera_x=?,camera_y=? WHERE id=?',
              (camera_x,camera_y,scene_id))
    conn.commit(); conn.close()

def update_scene_image(scene_id, image_path):
    conn = _conn(); c = conn.cursor()
    image_path = image_path.replace('\\', '/')
    c.execute('UPDATE scenes SET image_path=? WHERE id=?',(image_path,scene_id))
    conn.commit(); conn.close()

def rename_scene(scene_id, name):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE scenes SET name=? WHERE id=?',(name,scene_id))
    conn.commit(); conn.close()

def delete_scene(scene_id):
    conn = _conn(); c = conn.cursor()
    c.execute('DELETE FROM scenes WHERE id=?', (scene_id,))
    c.execute('DELETE FROM scene_markers       WHERE from_scene_id=? OR to_scene_id=?', (scene_id, scene_id))
    c.execute('DELETE FROM enemies             WHERE scene_id=?', (scene_id,))
    c.execute('DELETE FROM character_positions WHERE scene_id=?', (scene_id,))
    c.execute('DELETE FROM fog_of_war          WHERE scene_id=?', (scene_id,))
    c.execute('DELETE FROM dm_notes            WHERE scene_id=?', (scene_id,))
    c.execute('DELETE FROM sound_zones         WHERE scene_id=?', (scene_id,))
    c.execute('DELETE FROM scene_items         WHERE scene_id=?', (scene_id,))
    c.execute('DELETE FROM scene_traps         WHERE scene_id=?', (scene_id,))
    c.execute('DELETE FROM scene_snapshots     WHERE scene_id=?', (scene_id,))
    # Clear start_scene_id if it pointed to the deleted scene
    c.execute('UPDATE window_state SET start_scene_id=0 WHERE start_scene_id=?', (scene_id,))
    conn.commit(); conn.close()

def add_scene_marker(from_scene_id, to_scene_id, x, y):
    conn = _conn(); c = conn.cursor()
    c.execute('INSERT INTO scene_markers(from_scene_id,to_scene_id,x,y) VALUES(?,?,?,?)',
              (from_scene_id, to_scene_id, float(x), float(y)))
    mid = c.lastrowid; conn.commit(); conn.close()
    return mid

def get_scene_markers(from_scene_id):
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT id,to_scene_id,x,y FROM scene_markers WHERE from_scene_id=?',
              (from_scene_id,))
    rows = c.fetchall(); conn.close()
    return rows

def update_scene_marker_pos(marker_id, x, y):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE scene_markers SET x=?,y=? WHERE id=?', (float(x), float(y), marker_id))
    conn.commit(); conn.close()

def delete_scene_marker(marker_id):
    conn = _conn(); c = conn.cursor()
    c.execute('DELETE FROM scene_markers WHERE id=?', (marker_id,))
    conn.commit(); conn.close()

def delete_scene_markers(from_scene_id: int):
    """Delete all permanent markers originating from a scene."""
    conn = _conn(); c = conn.cursor()
    c.execute('DELETE FROM scene_markers WHERE from_scene_id=?', (from_scene_id,))
    conn.commit(); conn.close()

def get_scene_grid(scene_id):
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT show_grid FROM scenes WHERE id=?', (scene_id,))
    r = c.fetchone(); conn.close()
    return bool(r[0]) if r else True

def save_scene_grid(scene_id, show_grid):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE scenes SET show_grid=? WHERE id=?', (int(show_grid), scene_id))
    conn.commit(); conn.close()

def get_scene_fog(scene_id):
    """Returns (fog_on: bool, fog_radius_cells: int) for the scene."""
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT fog_on, fog_radius FROM scenes WHERE id=?', (scene_id,))
    r = c.fetchone(); conn.close()
    return (bool(r[0]), int(r[1])) if r else (True, 6)

def save_scene_fog(scene_id, fog_on, fog_radius_cells):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE scenes SET fog_on=?, fog_radius=? WHERE id=?',
              (int(fog_on), int(fog_radius_cells), scene_id))
    conn.commit(); conn.close()

def get_scene_zoom(scene_id):
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT zoom FROM scenes WHERE id=?', (scene_id,))
    r = c.fetchone(); conn.close()
    return float(r[0]) if r else 1.0

def save_scene_zoom(scene_id, zoom):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE scenes SET zoom=? WHERE id=?', (float(zoom), scene_id))
    conn.commit(); conn.close()

# ── Sound zones ───────────────────────────────────────────────────────────────

def get_sound_zones(scene_id):
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT id,name,x,y,w,h,track,color,scene_id FROM sound_zones'
              ' WHERE (scene_id=? OR scene_id=0) AND is_default=0 ORDER BY id', (scene_id,))
    rows = c.fetchall(); conn.close(); return rows

def get_default_zone(scene_id):
    """Return the ambient-fallback zone row for this scene, or None."""
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT id,name,x,y,w,h,track,color,scene_id FROM sound_zones'
              ' WHERE is_default=1 AND (scene_id=? OR scene_id=0) ORDER BY scene_id DESC LIMIT 1',
              (scene_id,))
    row = c.fetchone(); conn.close(); return row

def set_default_zone(scene_id, name, track, color):
    """Upsert the ambient-fallback zone for this scene (one per scene)."""
    conn = _conn(); c = conn.cursor()
    track = track.replace('\\', '/')
    c.execute('DELETE FROM sound_zones WHERE is_default=1 AND scene_id=?', (scene_id,))
    c.execute('INSERT INTO sound_zones(name,x,y,w,h,track,color,scene_id,is_default)'
              ' VALUES(?,0,0,0,0,?,?,?,1)',
              (name, track, color, scene_id))
    new_id = c.lastrowid; conn.commit(); conn.close(); return new_id

def clear_default_zone(scene_id):
    conn = _conn(); c = conn.cursor()
    c.execute('DELETE FROM sound_zones WHERE is_default=1 AND scene_id=?', (scene_id,))
    conn.commit(); conn.close()

def add_sound_zone(name, x, y, w, h, track, color, scene_id):
    conn = _conn(); c = conn.cursor()
    track = track.replace('\\', '/')
    c.execute('INSERT INTO sound_zones(name,x,y,w,h,track,color,scene_id) VALUES(?,?,?,?,?,?,?,?)',
              (name, float(x), float(y), float(w), float(h), track, color, scene_id))
    new_id = c.lastrowid; conn.commit(); conn.close(); return new_id

def update_sound_zone(id, name, track, color):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE sound_zones SET name=?,track=?,color=? WHERE id=?', (name, track.replace('\\', '/'), color, id))
    conn.commit(); conn.close()

def delete_sound_zone(id):
    conn = _conn(); c = conn.cursor()
    c.execute('DELETE FROM sound_zones WHERE id=?', (id,))
    conn.commit(); conn.close()

# ── GM Notes ──────────────────────────────────────────────────────────────────

def get_notes(scene_id=0):
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT text FROM dm_notes WHERE scene_id=?', (scene_id,))
    r = c.fetchone(); conn.close()
    return r[0] if r else ''

def save_notes(scene_id, text):
    conn = _conn(); c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO dm_notes(scene_id,text) VALUES(?,?)',
              (scene_id, text))
    conn.commit(); conn.close()

# ── Stat blocks ───────────────────────────────────────────────────────────────

_STAT_DEFAULTS = dict(ac=10, speed=30, str_score=10, dex_score=10,
                      con_score=10, int_score=10, wis_score=10, cha_score=10)

def get_stat_block(entity_type, entity_id):
    """Returns a dict with all 8 stat fields, populated with defaults if absent."""
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT ac,speed,str_score,dex_score,con_score,int_score,wis_score,cha_score'
              ' FROM stat_blocks WHERE entity_type=? AND entity_id=?',
              (entity_type, entity_id))
    row = c.fetchone(); conn.close()
    if row:
        keys = ('ac','speed','str_score','dex_score','con_score',
                'int_score','wis_score','cha_score')
        return dict(zip(keys, row))
    return dict(_STAT_DEFAULTS)

def save_stat_block(entity_type, entity_id, data):
    conn = _conn(); c = conn.cursor()
    c.execute(
        'INSERT OR REPLACE INTO stat_blocks'
        '(entity_type,entity_id,ac,speed,str_score,dex_score,con_score,int_score,wis_score,cha_score)'
        ' VALUES(?,?,?,?,?,?,?,?,?,?)',
        (entity_type, entity_id,
         data.get('ac',10), data.get('speed',30),
         data.get('str_score',10), data.get('dex_score',10), data.get('con_score',10),
         data.get('int_score',10), data.get('wis_score',10), data.get('cha_score',10))
    )
    conn.commit(); conn.close()


# ── Hidden items ───────────────────────────────────────────────────────────────

def get_scene_items(scene_id):
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT id,scene_id,x,y,radius,dc,description,found '
              'FROM scene_items WHERE scene_id=?', (scene_id,))
    rows = c.fetchall(); conn.close(); return rows

def add_scene_item(scene_id, x, y, radius, dc, description):
    conn = _conn(); c = conn.cursor()
    c.execute('INSERT INTO scene_items(scene_id,x,y,radius,dc,description) '
              'VALUES(?,?,?,?,?,?)', (scene_id, x, y, radius, dc, description))
    conn.commit(); rowid = c.lastrowid; conn.close(); return rowid

def update_scene_item(item_id, dc, description, radius):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE scene_items SET dc=?,description=?,radius=? WHERE id=?',
              (dc, description, radius, item_id))
    conn.commit(); conn.close()

def mark_scene_item_found(item_id):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE scene_items SET found=1 WHERE id=?', (item_id,))
    conn.commit(); conn.close()

def delete_scene_item(item_id):
    conn = _conn(); c = conn.cursor()
    c.execute('DELETE FROM scene_items WHERE id=?', (item_id,))
    conn.commit(); conn.close()


# ── Traps ──────────────────────────────────────────────────────────────────────

def get_scene_traps(scene_id):
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT id,scene_id,x,y,radius,description,triggered '
              'FROM scene_traps WHERE scene_id=?', (scene_id,))
    rows = c.fetchall(); conn.close(); return rows

def add_scene_trap(scene_id, x, y, radius, description):
    conn = _conn(); c = conn.cursor()
    c.execute('INSERT INTO scene_traps(scene_id,x,y,radius,description) '
              'VALUES(?,?,?,?,?)', (scene_id, x, y, radius, description))
    conn.commit(); rowid = c.lastrowid; conn.close(); return rowid

def update_scene_trap(trap_id, description, radius):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE scene_traps SET description=?,radius=? WHERE id=?',
              (description, radius, trap_id))
    conn.commit(); conn.close()

def trigger_scene_trap(trap_id):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE scene_traps SET triggered=1 WHERE id=?', (trap_id,))
    conn.commit(); conn.close()

def reset_scene_trap(trap_id):
    conn = _conn(); c = conn.cursor()
    c.execute('UPDATE scene_traps SET triggered=0 WHERE id=?', (trap_id,))
    conn.commit(); conn.close()

def delete_scene_trap(trap_id):
    conn = _conn(); c = conn.cursor()
    c.execute('DELETE FROM scene_traps WHERE id=?', (trap_id,))
    conn.commit(); conn.close()


# ── Scene Snapshots ────────────────────────────────────────────────────────────

def save_scene_snapshot(scene_id: int, snapshot: dict):
    import json, datetime
    snapshot['created_at'] = datetime.datetime.now().isoformat(timespec='seconds')
    conn = _conn(); c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO scene_snapshots(scene_id,snapshot_json,created_at) VALUES(?,?,?)',
              (scene_id, json.dumps(snapshot), snapshot['created_at']))
    conn.commit(); conn.close()

def get_scene_snapshot(scene_id: int):
    import json
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT snapshot_json FROM scene_snapshots WHERE scene_id=?', (scene_id,))
    row = c.fetchone(); conn.close()
    return json.loads(row[0]) if row else None

def has_scene_snapshot(scene_id: int) -> bool:
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT 1 FROM scene_snapshots WHERE scene_id=?', (scene_id,))
    r = c.fetchone(); conn.close()
    return r is not None

def get_snapshot_scene_ids() -> list:
    """Return scene_ids that have a saved initial-state snapshot."""
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT scene_id FROM scene_snapshots')
    rows = c.fetchall(); conn.close()
    return [r[0] for r in rows]

def get_scene_enemies_full(scene_id: int) -> list:
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT id,name,x,y,color,size,image_path,hp,max_hp,conditions,initiative'
              ' FROM enemies WHERE scene_id=?', (scene_id,))
    rows = c.fetchall(); conn.close(); return rows

def get_scene_npcs_full(scene_id: int) -> list:
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT id,name,x,y,color,size,image_path,hp,max_hp,conditions,initiative,init_bonus,is_npc'
              ' FROM characters WHERE scene_id=?', (scene_id,))
    rows = c.fetchall(); conn.close(); return rows

def delete_scene_enemies(scene_id: int):
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT id FROM enemies WHERE scene_id=?', (scene_id,))
    for (eid,) in c.fetchall():
        c.execute('DELETE FROM stat_blocks WHERE entity_type=? AND entity_id=?', ('enemy', eid))
    c.execute('DELETE FROM enemies WHERE scene_id=?', (scene_id,))
    conn.commit(); conn.close()

def delete_scene_npcs(scene_id: int):
    conn = _conn(); c = conn.cursor()
    c.execute('SELECT id FROM characters WHERE scene_id=?', (scene_id,))
    for (cid,) in c.fetchall():
        c.execute('DELETE FROM stat_blocks WHERE entity_type=? AND entity_id=?', ('character', cid))
        c.execute('DELETE FROM character_positions WHERE character_id=?', (cid,))
    c.execute('DELETE FROM characters WHERE scene_id=?', (scene_id,))
    conn.commit(); conn.close()

def delete_all_scene_items(scene_id: int):
    conn = _conn(); c = conn.cursor()
    c.execute('DELETE FROM scene_items WHERE scene_id=?', (scene_id,))
    conn.commit(); conn.close()

def delete_all_scene_traps(scene_id: int):
    conn = _conn(); c = conn.cursor()
    c.execute('DELETE FROM scene_traps WHERE scene_id=?', (scene_id,))
    conn.commit(); conn.close()

def restore_enemy(name, x, y, color, size, hp, max_hp, conditions, initiative, image_path, scene_id) -> int:
    conn = _conn(); c = conn.cursor()
    c.execute('INSERT INTO enemies(name,x,y,color,size,hp,max_hp,conditions,initiative,image_path,scene_id)'
              ' VALUES(?,?,?,?,?,?,?,?,?,?,?)',
              (name, x, y, color, size, hp, max_hp, conditions, initiative, image_path.replace('\\', '/'), scene_id))
    new_id = c.lastrowid; conn.commit(); conn.close(); return new_id

def restore_character(name, x, y, color, size, hp, max_hp, conditions, initiative,
                      init_bonus, is_npc, scene_id, image_path) -> int:
    conn = _conn(); c = conn.cursor()
    c.execute('INSERT INTO characters'
              '(name,x,y,color,size,hp,max_hp,conditions,initiative,init_bonus,is_npc,scene_id,image_path)'
              ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (name, x, y, color, size, hp, max_hp, conditions, initiative,
               init_bonus, int(is_npc), scene_id, image_path.replace('\\', '/')))
    new_id = c.lastrowid; conn.commit(); conn.close(); return new_id

# ── Orphan cleanup ─────────────────────────────────────────────────────────────

def cleanup_orphaned_records() -> dict:
    """
    Delete every record that references a non-existent scene, character, or enemy.

    Run at startup so stale data never accumulates.  Returns a dict mapping
    table name → number of rows removed (only includes tables where rows were deleted).

    Deletion order matters: characters/enemies are removed before the tables
    that reference them, so a single pass cleans up transitively stale rows.
    """
    conn = _conn()
    c    = conn.cursor()
    counts: dict = {}

    def _del(table: str, where: str):
        c.execute(f'DELETE FROM {table} WHERE {where}')
        if c.rowcount:
            counts[table] = counts.get(table, 0) + c.rowcount

    # ── 1. Rows whose scene_id points to a deleted scene ──────────────────
    _del('characters',          'scene_id != 0 AND scene_id NOT IN (SELECT id FROM scenes)')
    _del('enemies',             'scene_id != 0 AND scene_id NOT IN (SELECT id FROM scenes)')
    _del('character_positions', 'scene_id NOT IN (SELECT id FROM scenes)')
    _del('scene_markers',       'from_scene_id NOT IN (SELECT id FROM scenes)')
    _del('scene_markers',       'to_scene_id   NOT IN (SELECT id FROM scenes)')
    _del('fog_of_war',          'scene_id != 0 AND scene_id NOT IN (SELECT id FROM scenes)')
    _del('dm_notes',            'scene_id != 0 AND scene_id NOT IN (SELECT id FROM scenes)')
    _del('sound_zones',         'scene_id != 0 AND scene_id NOT IN (SELECT id FROM scenes)')
    _del('scene_items',         'scene_id NOT IN (SELECT id FROM scenes)')
    _del('scene_traps',         'scene_id NOT IN (SELECT id FROM scenes)')
    _del('scene_snapshots',     'scene_id NOT IN (SELECT id FROM scenes)')

    # ── 2. Rows whose character_id points to a deleted character ──────────
    #    (catches positions for characters deleted in step 1 as well)
    _del('character_positions', 'character_id NOT IN (SELECT id FROM characters)')
    _del('stat_blocks',         "entity_type='character' AND entity_id NOT IN (SELECT id FROM characters)")

    # ── 3. Stat blocks whose enemy no longer exists ───────────────────────
    _del('stat_blocks',         "entity_type='enemy' AND entity_id NOT IN (SELECT id FROM enemies)")

    conn.commit()
    conn.close()
    return counts
