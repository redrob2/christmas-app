"""Reminder emails (and push notifications), run by the "scheduler" service in docker-compose.yml.

    flask --app run:app send-reminders      # one pass (safe to run any time)
    flask --app run:app reminder-scheduler  # run daily at REMINDER_HOUR (default 9am)

Each reminder is recorded in ReminderLog, so nobody gets the same one twice.
"""
import time
from datetime import datetime, timedelta

import click
from flask import render_template
from flask_mail import Message

from app import db, mail
from app.push import link_path, send_push
from app.models import (AppSettings, ChristmasEvent, EventParticipant, ItemPurchase, ReminderLog,
                        SecretSantaAssignment, WishList, WishListItem)
from app.utils import get_external_url


def _already_sent(event, user, kind):
    return ReminderLog.query.filter_by(event_id=event.id, user_id=user.id, kind=kind).first() is not None


def _send(event, user, kind, subject, template, push_body='', **context):
    emailed = True
    try:
        msg = Message(subject, recipients=[user.email])
        msg.html = render_template(template, event=event, user=user, **context)
        mail.send(msg)
    except Exception as e:
        print(f"[reminders] email to {user.email} failed: {e}", flush=True)
        emailed = False
    pushed = send_push(user, subject, push_body, url=link_path(context.get('link')), tag=f'reminder-{kind}-{event.id}')
    if not emailed and not pushed:
        return False  # nothing reached them: try again next run
    db.session.add(ReminderLog(event_id=event.id, user_id=user.id, kind=kind))
    db.session.commit()
    print(f"[reminders] sent {kind} for '{event.name}' to {user.email}", flush=True)
    return True


def send_reminders(today=None):
    """Send any reminders that are due. Returns the number of emails sent."""
    settings = AppSettings.query.first()
    if not settings or not settings.reminders_enabled:
        return 0
    # (a backup restore may have replaced the notification keys since this process started)
    from app.push import ensure_vapid_keys
    ensure_vapid_keys()

    today = today or datetime.now().date()
    sent = 0
    events = ChristmasEvent.query.filter(ChristmasEvent.is_active.is_(True),
                                         ChristmasEvent.event_date.isnot(None)).all()
    for event in events:
        if event.id == settings.demo_event_id:   # practice event: nothing real to remind about
            continue
        days = (event.event_date - today).days
        if days < 0:
            continue
        lock_days = (event.lists_lock_date - today).days if event.lists_lock_date else None
        for participant in EventParticipant.query.filter_by(event_id=event.id).all():
            user = participant.user
            if user.is_managed:  # no login or email of their own
                continue
            wishlist = WishList.query.filter_by(event_id=event.id, owner_id=user.id).first()
            empty_list = wishlist is not None and wishlist.items.count() == 0

            # 1. Empty wishlist, N days out
            if (empty_list and days <= settings.empty_list_reminder_days
                    and not _already_sent(event, user, 'empty_list')):
                sent += _send(event, user, 'empty_list', f'📝 Your wishlist for {event.name} is empty!',
                              'emails/reminder_empty_list.html', days=days,
                              push_body='Add a few ideas so your family knows what you\'d love.',
                              link=get_external_url('wishlist.view_wishlist', wishlist_id=wishlist.id))

            # 2. Lists lock in a few days
            if (lock_days is not None and 0 < lock_days <= 3
                    and not _already_sent(event, user, 'lock_soon')):
                when = event.lists_lock_date.strftime('%B ') + str(event.lists_lock_date.day)
                sent += _send(event, user, 'lock_soon', f'🔒 Wishlists for {event.name} lock on {when}',
                              'emails/reminder_lock_soon.html', when=when, lock_days=lock_days,
                              push_body='Last chance to add or change anything on your list.',
                              link=get_external_url('wishlist.view_wishlist', wishlist_id=wishlist.id) if wishlist
                              else get_external_url('main.dashboard'))

            # 3. Countdown, N days out
            if (0 < days <= settings.countdown_reminder_days
                    and not _already_sent(event, user, 'countdown')):
                assignment = None
                if event.secret_santa_enabled:
                    assignment = SecretSantaAssignment.query.filter_by(event_id=event.id, giver_id=user.id).first()
                receiver = assignment.receiver if assignment else None
                my_purchases = (ItemPurchase.query.filter_by(purchaser_id=user.id)
                                .join(WishListItem).join(WishList)
                                .filter(WishList.event_id == event.id).all())
                # only gifts the buyer marked as their Secret Santa gift
                bought_for_receiver = sum(1 for p in my_purchases
                                          if receiver and p.is_secret_santa
                                          and p.item.wishlist.owner_id == receiver.id)
                unwrapped = sum(1 for p in my_purchases if p.status == 'purchased')
                sent += _send(event, user, 'countdown', f'⏰ {days} day{"s" if days != 1 else ""} until {event.name}!',
                              'emails/reminder_countdown.html', days=days, receiver=receiver,
                              push_body=('Your Secret Santa gift isn\'t marked yet. ' if receiver and not bought_for_receiver else '')
                              + (f'{unwrapped} gift{"s" if unwrapped != 1 else ""} still to wrap.' if unwrapped
                                 else 'Tap to check your shopping.'),
                              bought_for_receiver=bought_for_receiver, unwrapped=unwrapped,
                              empty_list=empty_list,
                              link=get_external_url('events.view_event', event_id=event.id))
    return sent


def register_cli(app):
    @app.cli.command('send-reminders')
    def send_reminders_command():
        """Send any reminder emails that are due now."""
        click.echo(f"Sent {send_reminders()} reminder email(s).")

    @app.cli.command('reminder-scheduler')
    @click.option('--hour', default=9, show_default=True, help='Local hour of day to send reminders.')
    def reminder_scheduler_command(hour):
        """Run forever: every minute, send admins' scheduled reminders that are due;
        once a day from HOUR on, the automatic reminders (each person gets each once)."""
        from app.admin_tools import send_due_reminders
        print(f"[reminders] scheduler started; automatic reminders daily from {hour:02d}:00, "
              "scheduled reminders checked every minute", flush=True)
        last_daily = None
        while True:
            now = datetime.now()
            try:
                sent = send_due_reminders()
                if sent:
                    print(f"[reminders] sent {sent} scheduled reminder(s)", flush=True)
                if now.hour >= hour and last_daily != now.date():
                    send_reminders()
                    last_daily = now.date()
            except Exception as e:
                db.session.rollback()
                print(f"[reminders] run failed: {e}", flush=True)
            finally:
                db.session.remove()
            time.sleep(60 - datetime.now().second)   # wake at the top of each minute
