# updater.py – check GitHub for a newer RealmScape release and apply it in
# place. Only ever copies items that exist in the downloaded GitHub snapshot,
# and never deletes anything already on disk — so local-only files (.venv,
# cache/, secrets, etc., all of which are gitignored and thus never part of
# the snapshot) are left alone automatically. Inside `campaigns/`, only the
# bundled `default` example campaign is synced; every other campaign folder,
# plus runtime files like active.json/.app_lock/.web_secret, belong to this
# install and must never be touched.
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

REPO_OWNER = 'coolfuton8'
REPO_NAME  = 'RealmScape'
BRANCH     = 'main'

APP_DIR      = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(APP_DIR, 'VERSION')

_VERSION_URL = f'https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}/VERSION'
_ZIP_URL     = f'https://github.com/{REPO_OWNER}/{REPO_NAME}/archive/refs/heads/{BRANCH}.zip'


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


def _sync_item(src, dst, backup_dir, label, copied, failed):
    """Copy src over dst, backing up any existing dst first so a failure
    partway through can be rolled back instead of losing the old version."""
    try:
        if os.path.exists(dst):
            backup_dst = os.path.join(backup_dir, *label.split('/'))
            os.makedirs(os.path.dirname(backup_dst), exist_ok=True)
            shutil.move(dst, backup_dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        copied.append(label)
    except Exception as exc:
        failed.append(f'{label}: {exc}')
        backup_dst = os.path.join(backup_dir, *label.split('/'))
        if os.path.exists(backup_dst) and not os.path.exists(dst):
            try:
                shutil.move(backup_dst, dst)
            except Exception:
                pass


def download_and_apply_update():
    """Download the latest main-branch snapshot and copy it over this
    install. Inside `campaigns/`, only the bundled `default` example is
    synced — every other campaign, plus local-only files that aren't part
    of the GitHub repo (.venv, cache/, secrets, etc.), are left alone.
    Returns (success, message)."""
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

        # Back up whatever is about to be replaced, so a partial failure can
        # be rolled back instead of leaving a half-updated install. Lives
        # inside tmp_dir (not APP_DIR) so it's removed automatically by the
        # cleanup below instead of accumulating in the RealmScape folder.
        backup_dir = os.path.join(tmp_dir, 'backup')

        copied, failed = [], []
        for name in os.listdir(src_root):
            src = os.path.join(src_root, name)

            if name == 'campaigns':
                # Only the bundled "default" example campaign is fair game.
                # Other campaign folders and runtime files (active.json,
                # .app_lock, .web_secret) belong to this install.
                default_src = os.path.join(src, 'default')
                if os.path.isdir(default_src):
                    _sync_item(default_src,
                              os.path.join(APP_DIR, 'campaigns', 'default'),
                              backup_dir, 'campaigns/default', copied, failed)
                continue

            dst = os.path.join(APP_DIR, name)
            _sync_item(src, dst, backup_dir, name, copied, failed)

        if failed:
            return False, (
                'Update partially applied. These items could not be updated '
                '(old versions were restored where possible):\n' + '\n'.join(failed))

        # GitHub's archive download doesn't preserve the executable bit, so
        # every .sh script loses it after being replaced. Restore it here
        # (a no-op on Windows, where the executable bit doesn't apply).
        if os.name == 'posix':
            for fn in os.listdir(APP_DIR):
                if fn.endswith('.sh'):
                    path = os.path.join(APP_DIR, fn)
                    try:
                        os.chmod(path, os.stat(path).st_mode | 0o111)
                    except OSError:
                        pass

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
