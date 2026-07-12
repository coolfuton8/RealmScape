# updater.py – check GitHub for a newer RealmScape release and apply it in
# place. Only ever copies items that exist in the downloaded GitHub snapshot,
# and never deletes anything already on disk — so local-only files (.venv,
# cache/, secrets, etc., all of which are gitignored and thus never part of
# the snapshot) are left alone automatically. The one item that IS tracked
# in GitHub but must still never be touched is `campaigns/`, since every
# install accumulates its own custom campaign data there.
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime

REPO_OWNER = 'coolfuton8'
REPO_NAME  = 'RealmScape'
BRANCH     = 'main'

APP_DIR      = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(APP_DIR, 'VERSION')

_VERSION_URL = f'https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}/VERSION'
_ZIP_URL     = f'https://github.com/{REPO_OWNER}/{REPO_NAME}/archive/refs/heads/{BRANCH}.zip'

# The only top-level name from the downloaded snapshot that must not be
# applied — everything else in the snapshot came from GitHub and is fair
# game; everything NOT in the snapshot (.venv, cache/, secrets, etc.) is
# never touched because the copy loop below only ever acts on what it finds
# inside the snapshot.
PRESERVE = {'campaigns'}


def get_current_version() -> str:
    try:
        with open(VERSION_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return '0.0.0'


def _parse_version(v: str):
    parts = []
    for p in v.strip().split('.'):
        m = re.match(r'\d+', p)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts)


def check_for_update(timeout: float = 6.0):
    """Return (latest_version, error). latest_version is None if already
    up to date; error holds a message string if the check itself failed."""
    try:
        with urllib.request.urlopen(_VERSION_URL, timeout=timeout) as resp:
            latest = resp.read().decode('utf-8').strip()
    except Exception as exc:
        return None, str(exc)
    if _parse_version(latest) > _parse_version(get_current_version()):
        return latest, None
    return None, None


def download_and_apply_update():
    """Download the latest main-branch snapshot and copy every file it
    contains over this install, except `campaigns/`. Local-only files that
    aren't part of the GitHub repo are left alone since they're never in the
    snapshot to begin with. Returns (success, message)."""
    tmp_dir = tempfile.mkdtemp(prefix='realmscape_update_')
    try:
        zip_path = os.path.join(tmp_dir, 'update.zip')
        try:
            with urllib.request.urlopen(_ZIP_URL, timeout=30) as resp, \
                 open(zip_path, 'wb') as out:
                shutil.copyfileobj(resp, out)
        except Exception as exc:
            return False, f'Download failed: {exc}'

        extract_dir = os.path.join(tmp_dir, 'extracted')
        try:
            import zipfile
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(extract_dir)
        except Exception as exc:
            return False, f'Could not read the downloaded update: {exc}'

        entries = [e for e in os.listdir(extract_dir)
                   if os.path.isdir(os.path.join(extract_dir, e))]
        if not entries:
            return False, 'Downloaded update was empty.'
        src_root = os.path.join(extract_dir, entries[0])

        # Back up whatever is about to be replaced, so a partial failure
        # can be rolled back instead of leaving a half-updated install.
        backup_dir = os.path.join(
            APP_DIR, f'_update_backup_{datetime.now():%Y%m%d_%H%M%S}')

        copied, failed = [], []
        for name in os.listdir(src_root):
            if name in PRESERVE:
                continue
            src = os.path.join(src_root, name)
            dst = os.path.join(APP_DIR, name)
            try:
                if os.path.exists(dst):
                    os.makedirs(backup_dir, exist_ok=True)
                    shutil.move(dst, os.path.join(backup_dir, name))
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                copied.append(name)
            except Exception as exc:
                failed.append(f'{name}: {exc}')
                backed_up = os.path.join(backup_dir, name)
                if os.path.exists(backed_up) and not os.path.exists(dst):
                    try:
                        shutil.move(backed_up, dst)
                    except Exception:
                        pass

        if failed:
            return False, (
                'Update partially applied. These items could not be updated '
                '(old versions were restored where possible):\n' + '\n'.join(failed))

        # Best-effort dependency refresh — new releases may add packages.
        req = os.path.join(APP_DIR, 'requirements.txt')
        if os.path.isfile(req):
            try:
                subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', '-q', '-r', req],
                    cwd=APP_DIR, timeout=300, check=False)
            except Exception:
                pass  # not fatal — user can run install.bat/.sh manually

        new_version = get_current_version()
        return True, (
            f'Updated to v{new_version}. Your campaigns were not touched.\n\n'
            f'Restart RealmScape to use the new version.')
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
