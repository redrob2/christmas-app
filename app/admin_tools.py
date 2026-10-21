"""Behind the admin pages: activity log, invites, the "who's ready" board,
nudges, announcements, Secret Santa repairs, copying events, exports and
backup status. Kept out of the route module so the scheduler and tests can use it."""
import csv
import io
import os
import random
import secrets
import string
from datetime import date, datetime

from flask import current_app, render_template, url_for
from flask_mail import Message

from app import db, mail
from app.models import (ActivityLog, Announcement, ChristmasEvent, EventParticipant, ExclusionPair,
                        PushSubscription, SantaMessage, SecretSantaAssignment, User, WishList, WishListItem)
from app.push import link_path, send_push
from app.utils import get_external_url, get_site_name


# ---------- Activity log ----------

def log_activity(action, detail='', event=None, actor=None):
    """Record something that happened. Never pass purchases or who drew whom."""
    try:
        from flask_login import current_user
        if actor is None and current_user and current_user.is_authenticated:
            actor = current_user
    except Exception:
        pass
    db.session.add(ActivityLog(action=action, detail=(detail or '')[:300],
                               event_id=event.id if event else None,
                               actor_id=actor.id if actor else None,
                               actor_name=actor.name if actor else None))
    db.session.commit()


ACTIVITY_LABELS = {
    'user_added': ('user-plus', 'Person added'), 'user_deleted': ('user-x', 'Person removed'),
    'user_updated': ('user-pen', 'Person updated'), 'user_joined': ('party-popper', 'Joined'),
    'password_reset': ('key-round', 'Password reset'), 'invite_resent': ('mail', 'Invite resent'),
    'event_created': ('calendar-plus', 'Event created'), 'event_copied': ('copy', 'Event copied'),
    'event_updated': ('calendar-cog', 'Event updated'), 'event_deleted': ('calendar-x', 'Event deleted'),
    'event_toggled': ('eye', 'Event shown / hidden'), 'participant_added': ('user-round-plus', 'Added to event'),
    'participant_removed': ('user-round-minus', 'Removed from event'), 'names_drawn': ('shuffle', 'Names drawn'),
    'names_sent': ('send', 'Names sent'), 'draw_changed': ('git-compare-arrows', 'Draw adjusted'),
    'announcement': ('megaphone', 'Announcement'), 'nudge': ('bell-ring', 'Nudge sent'),
    'settings': ('sliders-horizontal', 'Settings changed'),
    'signup_requested': ('user-round-search', 'Account requested'),
    'signup_auto': ('badge-check', 'Joined (family question)'),
    'signup_approved': ('user-check', 'Account approved'), 'signup_declined': ('user-x', 'Account declined'),
}


# ---------- People ----------

def generate_temp_password(length=10):
    characters = string.ascii_letters + string.digits
    return ''.join(secrets.choice(characters) for _ in range(length))


def send_welcome(user):
    """Give the person a fresh temporary password and email it. Returns (sent, temp_password)."""
    temp_password = generate_temp_password()
    user.set_password(temp_password)
    user.must_change_password = True
    db.session.commit()
    try:
        msg = Message(f'🎄 Welcome to {get_site_name()}!', recipients=[user.email])
        msg.html = render_template('emails/welcome.html', user=user, temp_password=temp_password,
                                   login_url=get_external_url('auth.login'))
        mail.send(msg)
        return True, temp_password
    except Exception as e:
        print(f"Email error: {e}", flush=True)
        return False, temp_password


def managed_placeholder_email():
    return f'managed-{secrets.token_hex(8)}@managed.invalid'


def approved_users():
    """Everyone except account requests still waiting for approval"""
    return User.query.filter(User.is_approved.is_(True)).order_by(User.name)


def admins(exclude=None):
    query = User.query.filter(User.is_admin.is_(True), User.is_managed.is_(False), User.is_approved.is_(True))
    if exclude is not None:
        query = query.filter(User.id != exclude.id)
    return query.all()


def notify_admins_joined(user):
    """First sign-in of someone an admin added: tell the admins"""
    log_activity('user_joined', f'{user.name} signed in for the first time', actor=user)
    people = admins(exclude=user)
    link = get_external_url('admin.users_list')
    for admin in people:
        try:
            msg = Message(f'🎉 {user.name} just joined {get_site_name()}', recipients=[admin.email])
            msg.html = render_template('emails/admin_joined.html', admin=admin, person=user, link=link)
            mail.send(msg)
        except Exception as e:
            print(f"Email error: {e}", flush=True)
    send_push(people, f'🎉 {user.name} just joined', 'They signed in for the first time.',
              url=link_path(link), tag=f'joined-{user.id}')


def notify_admins_signup(user):
    """Someone created an account: ask the admins to approve it - or, if they answered the
    family question, tell the admins they're in (and still need adding to an event)"""
    auto = user.is_approved
    log_activity('signup_auto' if auto else 'signup_requested', f'{user.name} ({user.email})', actor=user)
    people = admins()
    link = get_external_url('admin.users_list') + ('' if auto else '#pending')
    subject = (f'🎉 {user.name} joined {get_site_name()} (answered the family question)' if auto
               else f'🙋 {user.name} would like to join {get_site_name()}')
    for admin in people:
        try:
            msg = Message(subject, recipients=[admin.email])
            msg.html = render_template('emails/admin_signup.html', admin=admin, person=user, link=link, auto=auto)
            mail.send(msg)
        except Exception as e:
            print(f"Email error: {e}", flush=True)
    if auto:
        send_push(people, f'🎉 {user.name} joined', 'They answered the family question. Add them to an event.',
                  url=link_path(link), tag=f'signup-{user.id}')
    else:
        send_push(people, f'🙋 {user.name} asked to join', 'Tap to approve or decline.',
                  url=link_path(link), tag=f'signup-{user.id}')


def approve_signup(user):
    """Let them in and tell them. They join no events - an admin adds them to those."""
    user.is_approved = True
    db.session.commit()
    log_activity('signup_approved', user.name)
    try:
        msg = Message(f"🎄 You're in! Welcome to {get_site_name()}", recipients=[user.email])
        msg.html = render_template('emails/signup_approved.html', user=user,
                                   link=get_external_url('auth.login'))
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Email error: {e}", flush=True)
        return False


# ---------- Who's ready ----------

def readiness(event, viewer):
    """One row per person in the event. Gift counts are left out for the viewer's own
    list, so the organizer never learns what's been bought for them."""
    assignments = {a.giver_id: a for a in SecretSantaAssignment.query.filter_by(event_id=event.id)}
    devices = dict(db.session.query(PushSubscription.user_id, db.func.count(PushSubscription.id))
                   .group_by(PushSubscription.user_id).all())
    rows = []
    for p in EventParticipant.query.filter_by(event_id=event.id).all():
        user = p.user
        wishlist = WishList.query.filter_by(event_id=event.id, owner_id=user.id).first()
        items = wishlist.items.all() if wishlist else []
        own = user.id == viewer.id
        bought = None if own else sum(1 for i in items if i.purchase)
        chipped = None if own else sum(1 for i in items if i.contributions and not i.purchase)
        assignment = assignments.get(user.id)
        rows.append({
            'user': user,
            'wishlist': wishlist,
            'own': own,
            'joined': user.is_managed or user.last_login is not None,
            'item_count': len(items),
            'bought': bought,
            'needs_gifts': (not own) and bought == 0 and chipped == 0,
            'in_draw': event.secret_santa_enabled and p.participates_in_secret_santa and not user.is_managed,
            'drawn': assignment is not None,
            'seen': bool(assignment and assignment.seen_at),
            'devices': devices.get(user.id, 0),
        })
    rows.sort(key=lambda r: r['user'].name.lower())
    return rows


def readiness_summary(rows, event):
    people = [r for r in rows if not r['user'].is_managed]
    drawn = [r for r in rows if r['drawn']]
    return {
        'people': len(rows),
        'joined': sum(1 for r in people if r['joined']),
        'online': sum(1 for r in people if r['user'].is_online),
        'logins': len(people),
        'with_items': sum(1 for r in rows if r['item_count']),
        'seen': sum(1 for r in drawn if r['seen']),
        'drawn': len(drawn),
        'notifications': sum(1 for r in people if r['devices']),
        'needs_gifts': sum(1 for r in rows if r['needs_gifts']),
        # (never yourself: resending an invite resets that person's password)
        'not_joined': [r['user'] for r in people if not r['joined'] and not r['own']],
        'empty': [r['user'] for r in people if r['joined'] and not r['item_count']],
    }


def nudge_empty_lists(event, people):
    """Email + push everyone listed (signed-in people whose list is empty)"""
    sent = 0
    for user in people:
        wishlist = WishList.query.filter_by(event_id=event.id, owner_id=user.id).first()
        link = get_external_url('wishlist.view_wishlist', wishlist_id=wishlist.id)
        emailed = False
        try:
            msg = Message(f'📝 A nudge: your wishlist for {event.name} is empty', recipients=[user.email])
            msg.html = render_template('emails/nudge_empty_list.html', event=event, user=user, link=link,
                                       days=event.days_until())
            mail.send(msg)
            emailed = True
        except Exception as e:
            print(f"Email error: {e}", flush=True)
        pushed = send_push(user, f'📝 Your list for {event.name} is empty',
                           "Your family is ready to shop - add a few ideas.", url=link_path(link),
                           tag=f'nudge-{event.id}')
        sent += bool(emailed or pushed)
    return sent


def post_announcement(event, author, body, email=True):
    note = Announcement(event_id=event.id, author_id=author.id, body=body)
    db.session.add(note)
    db.session.commit()
    recipients = [p.user for p in EventParticipant.query.filter_by(event_id=event.id)
                  if not p.user.is_managed and p.user_id != author.id]
    link = get_external_url('main.dashboard')
    if email:
        for user in recipients:
            try:
                msg = Message(f'📣 {event.name}: a note from {author.name.split()[0]}', recipients=[user.email])
                msg.html = render_template('emails/announcement.html', event=event, user=user,
                                           author=author, body=body, link=link)
                mail.send(msg)
            except Exception as e:
                print(f"Email error: {e}", flush=True)
    preview = body if len(body) <= 140 else body[:137] + '...'
    send_push(recipients, f'📣 {event.name}', preview, url=link_path(link), tag=f'announce-{note.id}')
    log_activity('announcement', preview, event=event, actor=author)
    return note, len(recipients)


# ---------- Secret Santa repairs after the names went out ----------

class DrawError(Exception):
    pass


def _exclusions(event):
    pairs = set()
    for e in ExclusionPair.query.filter_by(event_id=event.id):
        pairs.add((e.user1_id, e.user2_id))
        pairs.add((e.user2_id, e.user1_id))
    return pairs


def _drop(assignment):
    SantaMessage.query.filter_by(assignment_id=assignment.id).delete(synchronize_session=False)
    db.session.delete(assignment)


def _relink(event, giver_id, receiver_id, excluded):
    """Give `giver_id` a receiver and `receiver_id` a giver, touching as few people as possible.
    Returns the givers whose name changed."""
    if giver_id != receiver_id and (giver_id, receiver_id) not in excluded:
        db.session.add(SecretSantaAssignment(event_id=event.id, giver_id=giver_id, receiver_id=receiver_id))
        return [giver_id]
    # Splice into someone else's pairing: A->B becomes A->receiver, giver->B
    candidates = SecretSantaAssignment.query.filter_by(event_id=event.id).all()
    random.shuffle(candidates)
    for other in candidates:
        a, b = other.giver_id, other.receiver_id
        if (b != giver_id and a != receiver_id and (giver_id, b) not in excluded
                and (a, receiver_id) not in excluded):
            _drop(other)
            db.session.flush()
            db.session.add(SecretSantaAssignment(event_id=event.id, giver_id=giver_id, receiver_id=b))
            db.session.add(SecretSantaAssignment(event_id=event.id, giver_id=a, receiver_id=receiver_id))
            return [giver_id, a]
    raise DrawError("There's no way to rearrange the names that respects the never-pair rules.")


def remove_from_draw(event, user):
    """Take someone out of a draw that's already been sent; only the people
    affected get a new name. Returns how many people got a new name."""
    participant = EventParticipant.query.filter_by(event_id=event.id, user_id=user.id).first_or_404()
    out = SecretSantaAssignment.query.filter_by(event_id=event.id, giver_id=user.id).first()
    into = SecretSantaAssignment.query.filter_by(event_id=event.id, receiver_id=user.id).first()
    participant.participates_in_secret_santa = False
    changed = []
    try:
        if out and into:
            giver_id, receiver_id = into.giver_id, out.receiver_id
            _drop(out)
            _drop(into)
            db.session.flush()
            if giver_id == receiver_id and not SecretSantaAssignment.query.filter_by(event_id=event.id).count():
                raise DrawError('That would leave only one person in the draw.')
            changed = _relink(event, giver_id, receiver_id, _exclusions(event))
        db.session.commit()
    except DrawError:
        db.session.rollback()
        raise
    _announce_new_names(event, changed)
    log_activity('draw_changed', f'{user.name} left the Secret Santa draw; '
                 f'{len(changed)} {"person" if len(changed) == 1 else "people"} got a new name', event=event)
    return len(changed)


def add_to_draw(event, user):
    """Add someone to a draw that's already been sent. Returns how many people got a new name."""
    if user.is_managed:
        raise DrawError(f"{user.name} doesn't have a login, so they can't draw a name.")
    participant = EventParticipant.query.filter_by(event_id=event.id, user_id=user.id).first_or_404()
    if SecretSantaAssignment.query.filter_by(event_id=event.id, giver_id=user.id).first():
        raise DrawError(f'{user.name} is already in the draw.')
    excluded = _exclusions(event)
    candidates = SecretSantaAssignment.query.filter_by(event_id=event.id).all()
    random.shuffle(candidates)
    for other in candidates:
        a, b = other.giver_id, other.receiver_id
        if (a, user.id) not in excluded and (user.id, b) not in excluded:
            _drop(other)
            db.session.flush()
            db.session.add(SecretSantaAssignment(event_id=event.id, giver_id=a, receiver_id=user.id))
            db.session.add(SecretSantaAssignment(event_id=event.id, giver_id=user.id, receiver_id=b))
            participant.participates_in_secret_santa = True
            db.session.commit()
            changed = [a, user.id]
            _announce_new_names(event, changed)
            log_activity('draw_changed', f'{user.name} joined the Secret Santa draw; '
                         '1 other person got a new name', event=event)
            return len(changed)
    raise DrawError(f"There's no way to fit {user.name} in that respects the never-pair rules.")


def _announce_new_names(event, giver_ids):
    """Email/push the givers whose name changed (only if names had already gone out)"""
    if not event.assignments_sent:
        return
    link = get_external_url('secretsanta.my_assignment', event_id=event.id)
    for giver_id in giver_ids:
        assignment = SecretSantaAssignment.query.filter_by(event_id=event.id, giver_id=giver_id).first()
        try:
            msg = Message(f'🎅 Your Secret Santa name for {event.name} has changed',
                          recipients=[assignment.giver.email])
            msg.html = render_template('emails/santa_changed.html', event=event, giver=assignment.giver,
                                       receiver=assignment.receiver, link=link)
            mail.send(msg)
            assignment.notified_at = datetime.utcnow()
        except Exception as e:
            print(f"Email error: {e}", flush=True)
        send_push(assignment.giver, f'🎅 Your Secret Santa name for {event.name} changed',
                  'Tap to see who you are buying for now.', url=link_path(link), tag=f'santa-drawn-{event.id}')
    db.session.commit()


# ---------- Copy an event to next year ----------

def _next_year(day):
    if day is None:
        return None
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # Feb 29
        return day.replace(year=day.year + 1, day=28)


def copy_event(event, hide_old=False):
    """Same people, settings and never-pair rules, one year later. Wishlists start empty
    (everyone can pull last year's unbought items in with "Copy from a past list")."""
    year = event.year + 1
    name = event.name.replace(str(event.year), str(year))
    new = ChristmasEvent(name=name, year=year, description=event.description,
                         event_date=_next_year(event.event_date), lists_lock_date=_next_year(event.lists_lock_date),
                         budget=event.budget, secret_santa_enabled=event.secret_santa_enabled, is_active=True)
    db.session.add(new)
    db.session.flush()
    for p in EventParticipant.query.filter_by(event_id=event.id):
        db.session.add(EventParticipant(event_id=new.id, user_id=p.user_id,
                                        participates_in_secret_santa=p.participates_in_secret_santa))
        db.session.add(WishList(event_id=new.id, owner_id=p.user_id))
    for pair in ExclusionPair.query.filter_by(event_id=event.id):
        db.session.add(ExclusionPair(event_id=new.id, user1_id=pair.user1_id, user2_id=pair.user2_id,
                                     reason=pair.reason))
    if hide_old:
        event.is_active = False
    db.session.commit()
    log_activity('event_copied', f'{new.name} {new.year} created from {event.name} {event.year}', event=new)
    return new


# ---------- Spreadsheet of everyone's lists ----------

PRIORITY_WORDS = {0: 'Nice to have', 1: 'Would like', 2: 'Really want', 3: 'Top pick'}


def _cell(value):
    """Plain text for spreadsheets: stop =, +, -, @ being run as formulas"""
    text = '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


def export_lists_csv(event, viewer):
    out = io.StringIO()
    out.write('﻿')  # so Excel reads the accents and emoji correctly
    writer = csv.writer(out)
    writer.writerow(['Person', 'Gift', 'Price', 'How much they want it', 'Color', 'Size', 'Link', 'Notes', 'Status'])
    wishlists = sorted(WishList.query.filter_by(event_id=event.id).all(), key=lambda w: w.owner.name.lower())
    for wishlist in wishlists:
        own = wishlist.owner_id == viewer.id
        for item in wishlist.items.order_by(WishListItem.priority.desc(), WishListItem.created_at):
            if own:
                status = ''          # never spoil the viewer's own surprises
            elif item.purchase:
                status = 'Bought'
            elif item.contributions:
                status = 'Group gift'
            else:
                status = 'Available'
            writer.writerow([_cell(v) for v in (
                wishlist.owner.name, item.name, f'{item.price:.2f}' if item.price is not None else '',
                PRIORITY_WORDS.get(item.priority or 0, ''), item.color, item.size, item.url, item.notes, status)])
    return out.getvalue()


# ---------- Backups (read from the backup service's folder) ----------

def backup_status():
    folder = current_app.config.get('BACKUP_STATUS_DIR')
    if not folder or not os.path.isdir(folder):
        return {'visible': False, 'folder': folder}

    def newest(prefix, suffix):
        files = [f for f in os.listdir(folder) if f.startswith(prefix) and f.endswith(suffix)]
        if not files:
            return None, 0
        files.sort(key=lambda f: os.path.getmtime(os.path.join(folder, f)))
        path = os.path.join(folder, files[-1])
        return {'name': files[-1], 'when': datetime.fromtimestamp(os.path.getmtime(path)),
                'size': os.path.getsize(path)}, len(files)

    db_backup, db_count = newest('db-', '.dump')
    files_backup, files_count = newest('files-', '.tar.gz')
    age_hours = (datetime.now() - db_backup['when']).total_seconds() / 3600 if db_backup else None
    return {'visible': True, 'folder': folder, 'db': db_backup, 'files': files_backup,
            'count': db_count, 'fresh': age_hours is not None and age_hours < 36, 'age_hours': age_hours}


def human_size(num):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if num < 1024 or unit == 'GB':
            return f'{num:.0f} {unit}' if unit == 'B' else f'{num:.1f} {unit}'
        num /= 1024
