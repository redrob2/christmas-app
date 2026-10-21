"""Push notifications to phones and computers (Web Push).

Each device that turns notifications on stores a PushSubscription. Sending
posts an encrypted message to that browser's push service (Apple, Google,
Mozilla or Microsoft), which delivers it - no extra container or account needed.
The key pair that signs these messages ("VAPID") is generated on first start
and kept in the database.
"""
import base64
import json
from datetime import datetime
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from flask import current_app

from app import db

# Endpoints are supplied by the browser, so only ever post to the real push services
PUSH_SERVICE_HOSTS = ('fcm.googleapis.com', 'android.googleapis.com', 'push.services.mozilla.com',
                      'push.apple.com', 'notify.windows.com')
MAX_DEVICES_PER_USER = 10


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _unb64(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _public_from_private(private_key):
    number = int.from_bytes(_unb64(private_key), 'big')
    key = ec.derive_private_key(number, ec.SECP256R1())
    return _b64(key.public_key().public_bytes(serialization.Encoding.X962,
                                              serialization.PublicFormat.UncompressedPoint))


def ensure_vapid_keys():
    """Load (or on the very first start, create) the key pair. Called at startup."""
    from app.models import AppSettings
    private_key = current_app.config.get('VAPID_PRIVATE_KEY')
    if not private_key:
        settings = AppSettings.query.first()
        if not settings.vapid_private_key:
            key = ec.generate_private_key(ec.SECP256R1())
            settings.vapid_private_key = _b64(key.private_numbers().private_value.to_bytes(32, 'big'))
            db.session.commit()
            print('[push] created notification keys', flush=True)
        private_key = settings.vapid_private_key
    try:
        current_app.extensions['vapid'] = (private_key, _public_from_private(private_key))
    except Exception as e:
        print(f'[push] notification key is invalid, notifications are off: {e}', flush=True)
        current_app.extensions['vapid'] = None


def public_key():
    keys = current_app.extensions.get('vapid')
    return keys[1] if keys else ''


def allowed_endpoint(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or '').lower()
    return (parts.scheme == 'https' and not parts.username and parts.port in (None, 443)
            and any(host == h or host.endswith('.' + h) for h in PUSH_SERVICE_HOSTS))


def device_label(user_agent):
    ua = user_agent or ''
    for needle, label in (('iPhone', 'iPhone'), ('iPad', 'iPad'), ('Android', 'Android'),
                          ('Windows', 'Windows'), ('Macintosh', 'Mac'), ('CrOS', 'Chromebook'),
                          ('Linux', 'Linux')):
        if needle in ua:
            return label
    return 'Browser'


def save_subscription(user, data, user_agent=None):
    """Store a browser's subscription JSON for this user. Returns an error message or None."""
    from app.models import PushSubscription
    endpoint = (data or {}).get('endpoint') or ''
    keys = (data or {}).get('keys') or {}
    p256dh, auth = keys.get('p256dh') or '', keys.get('auth') or ''
    if not (isinstance(endpoint, str) and len(endpoint) <= 1000 and allowed_endpoint(endpoint)):
        return 'That browser uses a notification service this app does not support.'
    try:
        if len(_unb64(p256dh)) != 65 or not 8 <= len(_unb64(auth)) <= 64:
            raise ValueError
    except (ValueError, TypeError):
        return 'The browser sent an invalid notification key.'

    # One row per device; a shared device belongs to whoever signed in on it last
    sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if sub is None:
        sub = PushSubscription(endpoint=endpoint)
        db.session.add(sub)
    sub.user_id, sub.p256dh, sub.auth = user.id, p256dh, auth
    sub.device = device_label(user_agent)
    db.session.flush()

    extra = (PushSubscription.query.filter_by(user_id=user.id)
             .order_by(PushSubscription.created_at.desc()).offset(MAX_DEVICES_PER_USER).all())
    for old in extra:
        db.session.delete(old)
    db.session.commit()
    return None


def remove_subscription(user, endpoint):
    from app.models import PushSubscription
    PushSubscription.query.filter_by(user_id=user.id, endpoint=endpoint or '').delete()
    db.session.commit()


def link_path(url):
    """Absolute link (e.g. from get_external_url) -> /path?query#fragment for the notification"""
    parts = urlsplit(url or '/')
    return (parts.path or '/') + (f'?{parts.query}' if parts.query else '') + \
        (f'#{parts.fragment}' if parts.fragment else '')


def send_push(users, title, body='', url='/', tag=None, badge=None, ttl=2 * 24 * 3600):
    """Notify every device of these users. Never raises; returns how many devices accepted it.

    Keep the text safe for a lock screen: never put who is whose Secret Santa in it.
    """
    from pywebpush import WebPushException, webpush
    from app.models import PushSubscription

    keys = current_app.extensions.get('vapid')
    user_ids = {u.id for u in (users if isinstance(users, (list, set, tuple)) else [users]) if u}
    if not keys or not user_ids:
        return 0
    try:
        subs = PushSubscription.query.filter(PushSubscription.user_id.in_(user_ids)).all()
    except Exception as e:  # e.g. table missing in a half-upgraded database
        print(f'[push] lookup failed: {e}', flush=True)
        db.session.rollback()
        return 0

    payload = {'title': title[:120], 'body': (body or '')[:300], 'url': url or '/'}
    if tag:
        payload['tag'] = tag
    if badge is not None:
        payload['badge'] = badge
    data = json.dumps(payload)

    sent = 0
    for sub in subs:
        if not allowed_endpoint(sub.endpoint):
            db.session.delete(sub)
            continue
        try:
            webpush(subscription_info={'endpoint': sub.endpoint, 'keys': {'p256dh': sub.p256dh, 'auth': sub.auth}},
                    data=data, vapid_private_key=keys[0],
                    # a fresh dict each time: pywebpush fills in the push service ("aud") per endpoint
                    vapid_claims={'sub': current_app.config['VAPID_SUBJECT']},
                    ttl=ttl, timeout=8, headers={'Urgency': 'normal'})
            sub.last_used_at = datetime.utcnow()
            sent += 1
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else None
            if status in (404, 410):  # the device turned notifications off or was reset
                db.session.delete(sub)
            else:
                print(f'[push] {sub.device} for user {sub.user_id} failed: {status} {e}', flush=True)
        except Exception as e:
            print(f'[push] {sub.device} for user {sub.user_id} failed: {e}', flush=True)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return sent
