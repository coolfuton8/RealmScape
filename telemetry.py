# telemetry.py – anonymous "app launched" ping (via PostHog) so the
# developer can see aggregate usage/version-adoption across everyone
# running RealmScape. No campaign data, names, or other personal content
# is ever sent — only a random per-install id, the app version, and the
# OS platform. Set REALMSCAPE_TELEMETRY=0 to disable entirely.
import os
import sys
import uuid

import posthog

POSTHOG_API_KEY = 'phc_xxLnrHNDY8HDLnmdwDQAYswCp4MH3rc9y2VEGKm8xjjZ'
POSTHOG_HOST    = 'https://us.i.posthog.com'

APP_DIR  = os.path.dirname(os.path.abspath(__file__))
_ID_FILE = os.path.join(APP_DIR, '.install_id')

ENABLED = os.environ.get('REALMSCAPE_TELEMETRY', '1') != '0'

posthog.api_key = POSTHOG_API_KEY
posthog.host    = POSTHOG_HOST


def _get_install_id() -> str:
    """A random id that identifies this install, not the person using it."""
    try:
        with open(_ID_FILE, 'r', encoding='utf-8') as f:
            existing = f.read().strip()
            if existing:
                return existing
    except OSError:
        pass
    new_id = str(uuid.uuid4())
    try:
        with open(_ID_FILE, 'w', encoding='utf-8') as f:
            f.write(new_id)
    except OSError:
        pass
    return new_id


def send_launch_event(version: str):
    """Fire-and-forget 'app_launched' ping. Never raises — a telemetry
    failure must never interrupt startup."""
    if not ENABLED:
        return
    try:
        posthog.capture(
            'app_launched',
            distinct_id=_get_install_id(),
            properties={
                'app_version': version,
                'platform':    sys.platform,
            },
        )
    except Exception as exc:
        print(f'[Telemetry] {exc}')
