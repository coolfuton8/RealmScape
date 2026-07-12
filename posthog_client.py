import atexit
import os
import uuid

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from posthog import Posthog

_CAMPAIGNS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'campaigns')
_INSTALL_ID_FILE = os.path.join(_CAMPAIGNS_DIR, '.install_id')


def _get_install_id():
    try:
        if os.path.exists(_INSTALL_ID_FILE):
            with open(_INSTALL_ID_FILE) as f:
                uid = f.read().strip()
                if uid:
                    return uid
    except Exception:
        pass
    uid = str(uuid.uuid4())
    try:
        os.makedirs(_CAMPAIGNS_DIR, exist_ok=True)
        with open(_INSTALL_ID_FILE, 'w') as f:
            f.write(uid)
    except Exception:
        pass
    return uid


INSTALL_ID = _get_install_id()

_api_key = os.environ.get('POSTHOG_PROJECT_TOKEN', '')
_host = os.environ.get('POSTHOG_HOST', 'https://us.i.posthog.com')

posthog_client = None

if _api_key:
    posthog_client = Posthog(
        project_api_key=_api_key,
        host=_host,
        enable_exception_autocapture=True,
    )
    atexit.register(posthog_client.shutdown)


def capture(event, properties=None):
    if posthog_client:
        posthog_client.capture(INSTALL_ID, event, properties or {})
