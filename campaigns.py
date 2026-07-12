# campaigns.py  –  campaign folder management
import os
import json
import shutil
import re
import io
import sqlite3
import zipfile

_BASE         = os.path.dirname(os.path.abspath(__file__))
CAMPAIGNS_DIR = os.path.join(_BASE, 'campaigns')
_META_FILE    = os.path.join(CAMPAIGNS_DIR, 'active.json')
# Block only characters Windows forbids in folder names: \ / : * ? " < > |
_FORBIDDEN = re.compile(r'[\\/:*?"<>|]')


def _ensure():
    os.makedirs(CAMPAIGNS_DIR, exist_ok=True)


def is_valid_name(name: str) -> bool:
    if not name or len(name) > 50:
        return False
    name = name.strip()
    if not name:
        return False
    return not _FORBIDDEN.search(name)


def list_campaigns() -> list:
    _ensure()
    return sorted(
        d for d in os.listdir(CAMPAIGNS_DIR)
        if os.path.isdir(os.path.join(CAMPAIGNS_DIR, d)) and not d.startswith('.')
    )


def get_active() -> str:
    if os.path.isfile(_META_FILE):
        try:
            with open(_META_FILE) as f:
                return json.load(f).get('active', 'default')
        except Exception:
            pass
    return 'default'


def set_active(name: str):
    _ensure()
    with open(_META_FILE, 'w') as f:
        json.dump({'active': name}, f)


def campaign_path(name: str) -> str:
    return os.path.join(CAMPAIGNS_DIR, name)


def db_path(name: str) -> str:
    return os.path.join(campaign_path(name), 'campaign.db')


def assets_path(name: str) -> str:
    return os.path.join(campaign_path(name), 'assets')


def create(name: str) -> str:
    """Create campaign folder + assets subfolder. Returns db path."""
    path = campaign_path(name)
    os.makedirs(path, exist_ok=True)
    os.makedirs(assets_path(name), exist_ok=True)
    return db_path(name)


def delete(name: str) -> bool:
    """Delete a campaign folder. Refuses to delete 'default'. Returns success."""
    if name == 'default':
        return False
    path = campaign_path(name)
    if os.path.isdir(path):
        shutil.rmtree(path)
        return True
    return False


def rename(old_name: str, new_name: str) -> bool:
    """Copy old campaign folder to new name and update active.json.

    Does NOT delete the old folder — caller must call remove_dir(old_name)
    after releasing any open DB handles, otherwise Windows denies the delete.
    """
    if not is_valid_name(new_name):
        return False
    old_path = campaign_path(old_name)
    new_path = campaign_path(new_name)
    if not os.path.isdir(old_path) or os.path.isdir(new_path):
        return False
    shutil.copytree(old_path, new_path)
    if get_active() == old_name:
        set_active(new_name)
    return True


def remove_dir(name: str):
    """Delete a campaign folder in a background thread with retries.

    Windows (Defender, Search indexer) can briefly lock newly-copied files.
    Running in a daemon thread avoids blocking the pygame main loop.
    """
    path = campaign_path(name)
    if not os.path.isdir(path):
        return

    def _delete():
        import time
        for _ in range(20):          # up to ~10 seconds of retries
            try:
                shutil.rmtree(path)
                return
            except OSError:
                time.sleep(0.5)
        shutil.rmtree(path, ignore_errors=True)   # give up gracefully

    import threading
    threading.Thread(target=_delete, daemon=True, name='campaign-cleanup').start()


def resolve_image_path(path: str) -> str:
    """Resolve a stored image path to a usable absolute path on the current OS.

    Handles: already-valid absolute paths, relative paths (resolved against
    project root), and old Windows absolute paths stored on another machine.
    """
    if not path:
        return path
    # Normalise Windows backslashes before any resolution attempt
    path = path.replace('\\', '/')
    # Already valid on this OS
    if os.path.isabs(path) and os.path.exists(path):
        return path
    # Relative path — resolve against project root
    candidate = os.path.join(_BASE, path)
    if os.path.exists(candidate):
        return candidate
    # Windows absolute path on a different machine — try the filename alone
    filename = os.path.basename(path)
    candidate = os.path.join(_BASE, filename)
    if os.path.exists(candidate):
        return candidate
    return path  # unresolvable; caller handles the missing file


def make_relative_path(path: str) -> str:
    """Convert an absolute path to a path relative to the project root if possible."""
    if not path:
        return path
    try:
        rel = os.path.relpath(path, _BASE)
        # relpath on different Windows drives raises ValueError; also avoid
        # paths that escape the project root with many "../" components.
        if not rel.startswith('..'):
            return rel
    except ValueError:
        pass
    return path


def import_asset(src_path: str, campaign_name: str) -> str:
    """Copy an asset file into the campaign's assets folder and return its relative path.

    If the file is already inside the campaign's assets folder it is not
    copied again.  Filename collisions with *different* files are resolved by
    appending a numeric suffix.  Returns a path relative to the project root
    (e.g. campaigns/default/assets/map.jpg) suitable for storing in the DB.
    """
    if not src_path:
        return src_path
    abs_src = os.path.abspath(src_path)
    if not os.path.isfile(abs_src):
        return make_relative_path(src_path)

    dest_dir = assets_path(campaign_name)
    os.makedirs(dest_dir, exist_ok=True)
    abs_dest_dir = os.path.abspath(dest_dir)

    # Already inside this campaign's assets folder — nothing to copy
    if abs_src.startswith(abs_dest_dir + os.sep):
        return make_relative_path(abs_src)

    filename = os.path.basename(abs_src)
    dest = os.path.join(dest_dir, filename)

    # Resolve filename collision: if a *different* file already exists there,
    # append an incrementing counter before the extension.
    if os.path.exists(dest):
        try:
            same = os.path.samefile(abs_src, dest)
        except OSError:
            same = False
        if not same:
            base, ext = os.path.splitext(filename)
            i = 1
            while os.path.exists(os.path.join(dest_dir, f'{base}_{i}{ext}')):
                i += 1
            dest = os.path.join(dest_dir, f'{base}_{i}{ext}')

    shutil.copy2(abs_src, dest)
    return make_relative_path(dest)


def export_zip(name: str) -> bytes:
    """Zip up a campaign folder (checkpointing its DB first for a consistent
    snapshot) and return the archive's raw bytes. Raises FileNotFoundError
    if the campaign doesn't exist."""
    path = campaign_path(name)
    if not os.path.isdir(path):
        raise FileNotFoundError(f'Campaign "{name}" not found')
    db_file = db_path(name)
    if os.path.isfile(db_file):
        conn = None
        try:
            conn = sqlite3.connect(db_file)
            conn.execute('PRAGMA wal_checkpoint(FULL)')
        except Exception:
            pass   # best-effort — export proceeds even if checkpoint fails
        finally:
            # Must always close, even on failure — an unclosed connection
            # holds an OS-level lock on db_file on Windows, which would later
            # block deleting/replacing this campaign's folder on import.
            if conn is not None:
                conn.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(path):
            for fn in files:
                full = os.path.join(root, fn)
                zf.write(full, os.path.relpath(full, path))
    return buf.getvalue()


def validate_campaign_zip(zip_path: str):
    """Raise ValueError if zip_path doesn't look like a campaign export
    produced by export_zip()."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad is not None:
                raise ValueError(f'Corrupt file in archive: {bad}')
            if 'campaign.db' not in zf.namelist():
                raise ValueError('This file does not look like a RealmScape campaign export')
    except zipfile.BadZipFile:
        raise ValueError('Not a valid zip file')


def _rmtree_retry(path: str, attempts: int = 6, delay: float = 0.3):
    """Synchronous delete with retries — Windows (Defender, Search indexer)
    can briefly lock files that were just written/extracted."""
    import time
    for _ in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except OSError:
            time.sleep(delay)
    shutil.rmtree(path, ignore_errors=True)   # give up gracefully


def import_zip(name: str, zip_path: str):
    """Extract a campaign zip into campaigns/<name>/, replacing any existing
    folder of that name. Raises ValueError on an invalid name or a zip that
    doesn't look like a RealmScape campaign export. Refuses 'default'."""
    if name == 'default' or not is_valid_name(name):
        raise ValueError('Invalid or reserved campaign name')
    validate_campaign_zip(zip_path)

    _ensure()
    staging = campaign_path(f'.importing_{name}')
    if os.path.isdir(staging):
        _rmtree_retry(staging)
    os.makedirs(staging)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(staging)

    target = campaign_path(name)
    if os.path.isdir(target):
        _rmtree_retry(target)
    shutil.move(staging, target)
    os.makedirs(assets_path(name), exist_ok=True)   # in case the export had none


def migrate_legacy_db():
    """On first run, move characters.db → campaigns/default/campaign.db."""
    legacy = os.path.join(_BASE, 'characters.db')
    _ensure()
    create('default')
    dest = db_path('default')
    if os.path.isfile(legacy) and not os.path.isfile(dest):
        shutil.copy2(legacy, dest)
    # Ensure an active.json exists
    if not os.path.isfile(_META_FILE):
        set_active('default')
