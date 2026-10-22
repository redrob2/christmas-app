"""Installable app (PWA): manifest, service worker, offline page, share target,
plus the endpoints phones use to turn notifications on and off."""
import hashlib
import os
import re

from flask import Blueprint, current_app, flash, jsonify, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.event_data import current_event, user_events
from app.models import WishList
from app.push import remove_subscription, save_subscription, send_push
from app.utils import get_app_name, get_site_name

pwa_bp = Blueprint('pwa', __name__)

NAVY = '#121a33'
# Shell files kept on the phone so the app opens instantly (pages themselves are never cached)
PRECACHE = ['css/christmas.css', 'js/christmas.js', 'images/favicon.svg', 'images/pawflake.svg',
            'icons/icon-192.png', 'icons/badge-96.png']


def compute_app_version(basedir):
    """Fingerprint of the code, templates and static files"""
    digest = hashlib.sha1()
    for folder in ('app', 'templates', 'static'):
        for root, dirs, files in os.walk(os.path.join(basedir, folder)):
            dirs[:] = sorted(d for d in dirs if d != '__pycache__')
            for name in sorted(files):
                path = os.path.join(root, name)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                digest.update(f'{os.path.relpath(path, basedir)}:{stat.st_size}:{int(stat.st_mtime)};'.encode())
    return digest.hexdigest()[:12]


def short_name(name):
    """Name under the home-screen icon (about 12 characters fit)"""
    if len(name) <= 12:
        return name
    last = name.split()[-1]
    return last if len(last) <= 12 else name[:12]


def no_store(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@pwa_bp.route('/manifest.webmanifest')
def manifest():
    name = get_site_name()
    icon = lambda file, size, purpose='any': {'src': url_for('static', filename=f'icons/{file}'),
                                              'sizes': size, 'type': 'image/png', 'purpose': purpose}
    data = {
        'id': '/',
        # what the phone shows under the icon and in its app list
        'name': get_app_name(),
        'short_name': short_name(get_app_name()),
        'description': 'Family wishlists, gift shopping and Secret Santa.',
        'start_url': url_for('main.dashboard'),
        'scope': '/',
        'display': 'standalone',
        'background_color': NAVY,
        'theme_color': NAVY,
        'icons': [icon('icon-192.png', '192x192'), icon('icon-512.png', '512x512'),
                  icon('icon-maskable-512.png', '512x512', 'maskable')],
        'shortcuts': [
            {'name': 'Add to my wishlist', 'short_name': 'Add item', 'url': url_for('pwa.share'),
             'icons': [icon('icon-192.png', '192x192')]},
            {'name': 'My shopping', 'url': url_for('wishlist.shopping_list'),
             'icons': [icon('icon-192.png', '192x192')]},
            {'name': 'Secret Santa', 'url': url_for('main.secret_santa'),
             'icons': [icon('icon-192.png', '192x192')]},
        ],
        # Android: "Share" a product from a store's app straight into your wishlist
        'share_target': {'action': url_for('pwa.share'), 'method': 'GET',
                         'params': {'title': 'title', 'text': 'text', 'url': 'url'}},
    }
    response = make_response(jsonify(data))
    response.headers['Content-Type'] = 'application/manifest+json'
    return no_store(response)


@pwa_bp.route('/sw.js')
def service_worker():
    precache = [url_for('static', filename=f) for f in PRECACHE]
    body = render_template('pwa/sw.js', version=current_app.config['APP_VERSION'], precache=precache,
                           offline_url=url_for('pwa.offline'), site_name=get_site_name())
    response = make_response(body)
    response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    response.headers['Service-Worker-Allowed'] = '/'
    return no_store(response)


@pwa_bp.route('/offline')
def offline():
    return render_template('pwa/offline.html')


@pwa_bp.route('/app-version')
def app_version():
    return no_store(jsonify(version=current_app.config['APP_VERSION']))


@pwa_bp.route('/share')
@login_required
def share():
    """Share target + "Add item" shortcut: open the add-item form on my main event's list,
    with the shared link filled in."""
    text = request.args.get('text', '')
    link = request.args.get('url', '').strip()
    if not link:  # many store apps put the link inside the shared text
        found = re.search(r'https?://\S+', text)
        link = found.group(0).rstrip('.,);]') if found else ''
    title = (request.args.get('title') or '').strip()

    event = current_event(user_events(current_user), current_user)
    wishlist = WishList.query.filter_by(event_id=event.id, owner_id=current_user.id).first() if event else None
    if not wishlist:
        flash("You're not on any event's list yet - ask the organizer to add you.", 'info')
        return redirect(url_for('main.dashboard'))

    args = {}
    if link.startswith(('http://', 'https://')) and len(link) <= 2000:
        args['link'] = link
    elif title:
        args['name'] = title[:200]
    return redirect(url_for('wishlist.add_item', wishlist_id=wishlist.id, **args))


# ---------- Notifications (called from christmas.js) ----------

@pwa_bp.route('/push/subscribe', methods=['POST'])
@login_required
def push_subscribe():
    error = save_subscription(current_user, request.get_json(silent=True), request.headers.get('User-Agent'))
    if error:
        return jsonify(error=error), 400
    return jsonify(ok=True)


@pwa_bp.route('/push/unsubscribe', methods=['POST'])
@login_required
def push_unsubscribe():
    remove_subscription(current_user, (request.get_json(silent=True) or {}).get('endpoint'))
    return jsonify(ok=True)


@pwa_bp.route('/push/test', methods=['POST'])
@login_required
def push_test():
    sent = send_push(current_user, '🔔 Notifications are on!',
                     "This is how you'll hear about Secret Santa messages, reminders and gift changes.",
                     url=url_for('profile.view_profile'), tag='test')
    if not sent:
        return jsonify(error="Couldn't reach this device. Turn notifications off and on again."), 400
    return jsonify(ok=True, devices=sent)
