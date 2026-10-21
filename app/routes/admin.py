from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, make_response
import os
from flask_login import login_required, current_user
import re
from datetime import datetime
from app import db, mail
from app.models import (User, ChristmasEvent, EventParticipant, ExclusionPair, AppSettings, WishList,
                        ItemPurchase, SecretSantaAssignment, PasswordResetToken, GiftContribution,
                        SantaMessage, ReminderLog, PushSubscription, Announcement, ActivityLog)
from app.utils import admin_required, get_external_url, get_site_name, parse_money
from app.admin_tools import (ACTIVITY_LABELS, DrawError, add_to_draw, approve_signup, approved_users,
                             backup_status, copy_event,
                             export_lists_csv, generate_temp_password, human_size, log_activity,
                             managed_placeholder_email, nudge_empty_lists, post_announcement, readiness,
                             readiness_summary, remove_from_draw, send_welcome)
from flask_mail import Message

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/')
@login_required
@admin_required
def admin_dashboard():
    users = approved_users().all()
    events = ChristmasEvent.query.order_by(ChristmasEvent.year.desc(), ChristmasEvent.name).all()
    settings = AppSettings.query.first()
    active = [(e, readiness_summary(readiness(e, current_user), e)) for e in events if e.is_active]
    others = [u for u in users if u.id != current_user.id]
    online = [u for u in others if u.is_online]
    recently = sorted((u for u in others if u.last_seen_at and not u.is_online),
                      key=lambda u: u.last_seen_at, reverse=True)[:5]
    return render_template('admin/dashboard.html',
                          online=online,
                          recently=recently,
                          users=users,
                          events=events,
                          settings=settings,
                          active=active,
                          recent=ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(8).all(),
                          activity_labels=ACTIVITY_LABELS,
                          backups=backup_status(),
                          pending=User.query.filter_by(is_approved=False).count())


# ==================== USER MANAGEMENT ====================

@admin_bp.route('/users')
@login_required
@admin_required
def users_list():
    users = approved_users().all()
    pending = User.query.filter_by(is_approved=False).order_by(User.created_at).all()
    return render_template('admin/users.html', users=users, pending=pending)


@admin_bp.route('/users/<int:user_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_approved:
        flash(f'{user.name} is already approved.', 'info')
        return redirect(url_for('admin.users_list'))
    emailed = approve_signup(user)
    flash(f'{user.name} is approved' + ('. They have been emailed.' if emailed
          else ". The email failed - let them know they can sign in.")
          + ' Add them to an event when you are ready (event setup → People).',
          'success' if emailed else 'warning')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/users/<int:user_id>/decline', methods=['POST'])
@login_required
@admin_required
def decline_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_approved:
        flash('Only account requests can be declined.', 'warning')
        return redirect(url_for('admin.users_list'))
    name = user.name
    db.session.delete(user)
    db.session.commit()
    log_activity('signup_declined', name)
    flash(f"{name}'s request was declined and removed.", 'success')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/users/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_user():
    login_users = approved_users().filter(User.is_managed.is_(False)).all()
    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        name = request.form.get('name', '').strip()
        is_admin = request.form.get('is_admin') == 'on'
        managed = request.form.get('managed') == 'on'
        manager = db.session.get(User, request.form.get('managed_by_id', type=int) or 0) if managed else None

        if not name or (not managed and not email):
            flash('Name and email are required.' if not managed else 'Name is required.', 'danger')
            return render_template('admin/add_user.html', login_users=login_users)
        if managed and (manager is None or manager.is_managed):
            flash('Choose who looks after their list.', 'danger')
            return render_template('admin/add_user.html', login_users=login_users)
        if not managed and User.query.filter_by(email=email).first():
            flash('A user with this email already exists.', 'danger')
            return render_template('admin/add_user.html', login_users=login_users)

        if managed:
            # No login: placeholder email and an unusable password; their manager edits the list
            user = User(email=managed_placeholder_email(), name=name, is_managed=True,
                        managed_by_id=manager.id, must_change_password=False)
            user.set_password(generate_temp_password(32))
            db.session.add(user)
            db.session.commit()
            log_activity('user_added', f'{name} (list looked after by {manager.name})')
            flash(f'{name} added - {manager.name} can now look after their wishlist.', 'success')
            return redirect(url_for('admin.users_list'))

        user = User(email=email, name=name, is_admin=is_admin)
        user.set_password(generate_temp_password(32))  # replaced by send_welcome() below
        db.session.add(user)
        db.session.commit()
        log_activity('user_added', name)
        sent, temp_password = send_welcome(user)
        if sent:
            flash(f'User {name} created successfully! Welcome email sent.', 'success')
        else:
            flash(f'User created but email failed to send. Temporary password: {temp_password}', 'warning')
        return redirect(url_for('admin.users_list'))

    return render_template('admin/add_user.html', login_users=login_users)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    login_users = approved_users().filter(User.is_managed.is_(False), User.id != user.id).all()

    if request.method == 'POST':
        user.name = request.form.get('name', '').strip() or user.name
        new_email = request.form.get('email', '').lower().strip()

        if user.is_managed:
            manager = db.session.get(User, request.form.get('managed_by_id', type=int) or 0)
            if manager and not manager.is_managed and manager.id != user.id:
                user.managed_by_id = manager.id
            if request.form.get('give_login') == 'on':
                # They're old enough for their own login now
                if not new_email or User.query.filter(User.email == new_email, User.id != user.id).first():
                    flash('Enter an email address nobody else uses.', 'danger')
                    return render_template('admin/edit_user.html', user=user, login_users=login_users)
                user.email, user.is_managed, user.managed_by_id = new_email, False, None
                db.session.commit()
                log_activity('user_updated', f'{user.name} now has their own login')
                sent, temp_password = send_welcome(user)
                flash(f'{user.name} has their own login now. ' + ('Welcome email sent.' if sent
                      else f'The email failed - temporary password: {temp_password}'), 'success' if sent else 'warning')
                return redirect(url_for('admin.users_list'))
        else:
            user.is_admin = request.form.get('is_admin') == 'on'
            if new_email and new_email != user.email:
                if User.query.filter_by(email=new_email).first():
                    flash('A user with this email already exists.', 'danger')
                    return render_template('admin/edit_user.html', user=user, login_users=login_users)
                user.email = new_email

        db.session.commit()
        log_activity('user_updated', user.name)
        flash('User updated successfully!', 'success')
        return redirect(url_for('admin.users_list'))

    return render_template('admin/edit_user.html', user=user, login_users=login_users)


@admin_bp.route('/users/<int:user_id>/resend-invite', methods=['POST'])
@login_required
@admin_required
def resend_invite(user_id):
    """New temporary password + welcome email for someone who hasn't signed in yet"""
    user = User.query.get_or_404(user_id)
    if user.is_managed or user.last_login is not None or user.id == current_user.id:
        flash(f'{user.name} has already signed in - use Reset Password instead.' if not user.is_managed
              else f"{user.name} doesn't have a login.", 'warning')
        return redirect(request.referrer or url_for('admin.users_list'))
    sent, temp_password = send_welcome(user)
    log_activity('invite_resent', user.name)
    if sent:
        flash(f'Welcome email sent to {user.name} again (with a new temporary password).', 'success')
    else:
        flash(f'The email failed. New temporary password for {user.name}: {temp_password}', 'warning')
    back = request.referrer or ''
    return redirect(back if back.startswith(request.host_url) else url_for('admin.users_list'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin.users_list'))

    # Remove everything that references this user first; the foreign keys are
    # NOT NULL, so deleting the user alone fails with an IntegrityError.
    from app.routes.wishlist import delete_uploaded_file
    ItemPurchase.query.filter_by(purchaser_id=user.id).delete(synchronize_session=False)
    GiftContribution.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    ReminderLog.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    for wishlist in WishList.query.filter_by(owner_id=user.id).all():
        for item in wishlist.items:
            delete_uploaded_file(item.image)
        db.session.delete(wishlist)  # cascades to items and their purchases
    user_assignments = SecretSantaAssignment.query.filter(db.or_(
        SecretSantaAssignment.giver_id == user.id,
        SecretSantaAssignment.receiver_id == user.id
    ))
    SantaMessage.query.filter(
        SantaMessage.assignment_id.in_(user_assignments.with_entities(SecretSantaAssignment.id))
    ).delete(synchronize_session=False)
    user_assignments.delete(synchronize_session=False)
    ExclusionPair.query.filter(db.or_(
        ExclusionPair.user1_id == user.id,
        ExclusionPair.user2_id == user.id
    )).delete(synchronize_session=False)
    EventParticipant.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    PasswordResetToken.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    PushSubscription.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    Announcement.query.filter_by(author_id=user.id).update({'author_id': None}, synchronize_session=False)
    # Lists they looked after go to an admin (the person deleting them)
    User.query.filter_by(managed_by_id=user.id).update({'managed_by_id': current_user.id}, synchronize_session=False)
    for photo in (user.profile_photo, user.profile_photo_ai, user.profile_photo_icon):
        delete_uploaded_file(photo)

    db.session.delete(user)
    db.session.commit()
    log_activity('user_deleted', user.name)
    flash(f'User {user.name} deleted successfully.', 'success')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@admin_required
def reset_user_password(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_managed:
        flash(f"{user.name} doesn't have a login.", 'warning')
        return redirect(url_for('admin.users_list'))

    # Generate new temporary password
    temp_password = generate_temp_password()
    user.set_password(temp_password)
    user.must_change_password = True
    db.session.commit()
    log_activity('password_reset', user.name)

    # Send email with new password
    try:
        login_url = get_external_url('auth.login')
        msg = Message(
            f'🎄 Password Reset - {get_site_name()}',
            recipients=[user.email]
        )
        msg.html = render_template('emails/password_reset_admin.html',
                                  user=user,
                                  temp_password=temp_password,
                                  login_url=login_url)
        mail.send(msg)
        flash(f'Password reset for {user.name}. Email sent.', 'success')
    except Exception as e:
        flash(f'Password reset but email failed. New password: {temp_password}', 'warning')
        print(f"Email error: {e}")

    return redirect(url_for('admin.users_list'))


# ==================== EVENT MANAGEMENT ====================

@admin_bp.route('/events')
@login_required
@admin_required
def events_list():
    events = ChristmasEvent.query.order_by(ChristmasEvent.year.desc(), ChristmasEvent.name).all()
    return render_template('admin/events.html', events=events)


@admin_bp.route('/events/<int:event_id>/copy', methods=['POST'])
@login_required
@admin_required
def copy_event_route(event_id):
    event = ChristmasEvent.query.get_or_404(event_id)
    new = copy_event(event, hide_old=request.form.get('hide_old') == 'on')
    flash(f'Created {new.name} {new.year} with the same people, budget and never-pair rules. '
          'Check the date, then draw names when you are ready.', 'success')
    return redirect(url_for('admin.manage_event', event_id=new.id, step='details'))


@admin_bp.route('/events/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_event():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        year = request.form.get('year', '')
        description = request.form.get('description', '').strip()
        event_date_str = request.form.get('event_date', '')

        if not name or not year:
            flash('Name and year are required.', 'danger')
            return render_template('admin/add_event.html', current_year=datetime.now().year)

        try:
            year = int(year)
        except ValueError:
            flash('Invalid year.', 'danger')
            return render_template('admin/add_event.html', current_year=datetime.now().year)

        # Parse event date
        event_date = None
        if event_date_str:
            try:
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass  # Invalid date, leave as None

        event = ChristmasEvent(
            name=name,
            year=year,
            description=description,
            event_date=event_date,
            budget=parse_money(request.form.get('budget')),
            secret_santa_enabled=request.form.get('secret_santa_enabled') == 'on'
        )
        db.session.add(event)
        db.session.commit()
        log_activity('event_created', f'{name} {year}', event=event)

        flash(f'Event "{name}" created successfully!', 'success')
        return redirect(url_for('admin.manage_event', event_id=event.id, step='people'))

    return render_template('admin/add_event.html', current_year=datetime.now().year)


@admin_bp.route('/events/<int:event_id>')
@login_required
@admin_required
def manage_event(event_id):
    """Guided event setup: Details -> People -> Secret Santa -> Draw & send"""
    event = ChristmasEvent.query.get_or_404(event_id)
    return render_event_setup(event, request.args.get('step', 'details'))


SETUP_STEPS = ('details', 'people', 'santa', 'draw')


def render_event_setup(event, step):
    """One page for every setup step (also used by the Secret Santa admin routes)"""
    if step not in SETUP_STEPS:
        step = 'details'
    if step == 'draw' and not event.secret_santa_enabled:
        step = 'santa'      # the Secret Santa step is where it gets switched on
    participants = EventParticipant.query.filter_by(event_id=event.id).all()
    participant_ids = [p.user_id for p in participants]
    assignments = SecretSantaAssignment.query.filter_by(event_id=event.id).all()
    participating_count = sum(1 for p in participants if p.participates_in_secret_santa)
    return render_template('admin/event_setup.html',
                           event=event,
                           step=step,
                           participants=sorted(participants, key=lambda p: p.user.name.lower()),
                           all_users=approved_users().all(),
                           participant_ids=participant_ids,
                           users=User.query.filter(User.id.in_(participant_ids)).order_by(User.name).all(),
                           exclusions=ExclusionPair.query.filter_by(event_id=event.id).all(),
                           assignments=assignments,
                           has_assignments=bool(assignments),
                           participating_count=participating_count,
                           opted_out_count=len(participants) - participating_count)


@admin_bp.route('/events/<int:event_id>/add-participant', methods=['POST'])
@login_required
@admin_required
def add_participant(event_id):
    event = ChristmasEvent.query.get_or_404(event_id)
    user_id = request.form.get('user_id', type=int)

    if not user_id:
        flash('Please select a user.', 'danger')
        return redirect(url_for('admin.manage_event', event_id=event_id, step='people'))
    user = User.query.get_or_404(user_id)

    # Check if already a participant
    existing = EventParticipant.query.filter_by(
        event_id=event_id,
        user_id=user_id
    ).first()

    if existing:
        flash('User is already a participant.', 'warning')
        return redirect(url_for('admin.manage_event', event_id=event_id, step='people'))

    participant = EventParticipant(event_id=event_id, user_id=user_id,
                                   participates_in_secret_santa=not user.is_managed)
    db.session.add(participant)

    # Create wishlist for user in this event
    wishlist = WishList(event_id=event_id, owner_id=user_id)
    db.session.add(wishlist)

    db.session.commit()
    log_activity('participant_added', user.name, event=event)

    flash(f'{user.name} added to the event!', 'success')
    return redirect(url_for('admin.manage_event', event_id=event_id, step='people'))


@admin_bp.route('/events/<int:event_id>/add-all-participants', methods=['POST'])
@login_required
@admin_required
def add_all_participants(event_id):
    """Add every user who isn't in the event yet (each gets a wishlist)"""
    event = ChristmasEvent.query.get_or_404(event_id)
    existing = {p.user_id for p in EventParticipant.query.filter_by(event_id=event_id)}
    added = 0
    for user in approved_users().all():
        if user.id in existing:
            continue
        db.session.add(EventParticipant(event_id=event_id, user_id=user.id,
                                        participates_in_secret_santa=not user.is_managed))
        if not WishList.query.filter_by(event_id=event_id, owner_id=user.id).first():
            db.session.add(WishList(event_id=event_id, owner_id=user.id))
        added += 1
    db.session.commit()
    if added:
        log_activity('participant_added', f'{added} people (Add everyone)', event=event)
    flash(f'Added {added} {"person" if added == 1 else "people"} to {event.name}.' if added
          else 'Everyone is already in this event.', 'success' if added else 'info')
    return redirect(url_for('admin.manage_event', event_id=event_id, step='people'))


@admin_bp.route('/events/<int:event_id>/remove-participant/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def remove_participant(event_id, user_id):
    event = ChristmasEvent.query.get_or_404(event_id)

    in_draw = SecretSantaAssignment.query.filter_by(event_id=event_id).filter(db.or_(
        SecretSantaAssignment.giver_id == user_id, SecretSantaAssignment.receiver_id == user_id)).first()
    if event.secret_santa_locked() and in_draw:
        flash('Take them out of the Secret Santa draw first (step 4), then remove them.', 'danger')
        return redirect(url_for('admin.manage_event', event_id=event_id, step='people'))

    participant = EventParticipant.query.filter_by(
        event_id=event_id,
        user_id=user_id
    ).first()

    if participant:
        # Also remove their wishlist
        wishlist = WishList.query.filter_by(event_id=event_id, owner_id=user_id).first()
        if wishlist:
            db.session.delete(wishlist)

        name = participant.user.name
        db.session.delete(participant)
        db.session.commit()
        log_activity('participant_removed', name, event=event)
        flash('Participant removed.', 'success')

    return redirect(url_for('admin.manage_event', event_id=event_id, step='people'))


@admin_bp.route('/events/<int:event_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_event(event_id):
    event = ChristmasEvent.query.get_or_404(event_id)
    User.query.filter_by(main_event_id=event.id).update({'main_event_id': None})
    label = f'{event.name} {event.year}'
    db.session.delete(event)
    db.session.commit()
    log_activity('event_deleted', label)
    flash(f'Event "{event.name}" deleted.', 'success')
    return redirect(url_for('admin.events_list'))


@admin_bp.route('/events/<int:event_id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def toggle_event_active(event_id):
    event = ChristmasEvent.query.get_or_404(event_id)
    event.is_active = not event.is_active
    db.session.commit()
    status = 'activated' if event.is_active else 'deactivated'
    log_activity('event_toggled', f'{event.name} {status}', event=event)
    flash(f'Event {status}.', 'success')
    return redirect(url_for('admin.manage_event', event_id=event_id))


@admin_bp.route('/events/<int:event_id>/update', methods=['POST'])
@login_required
@admin_required
def update_event(event_id):
    event = ChristmasEvent.query.get_or_404(event_id)

    # The setup steps post only their own fields ("section"); no section = everything
    section = request.form.get('section', 'all')

    if section in ('details', 'all'):
        event_date_str = request.form.get('event_date', '')
        if event_date_str:
            try:
                event.event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        else:
            event.event_date = None
        event.description = request.form.get('description', '').strip()
        if request.form.get('name', '').strip():
            event.name = request.form['name'].strip()
        lock_str = request.form.get('lists_lock_date', '')
        try:
            event.lists_lock_date = datetime.strptime(lock_str, '%Y-%m-%d').date() if lock_str else None
        except ValueError:
            pass

    if section in ('santa', 'all'):
        event.budget = parse_money(request.form.get('budget'))
        event.secret_santa_enabled = request.form.get('secret_santa_enabled') == 'on'

    db.session.commit()
    log_activity('event_updated', f'{event.name}: {section}', event=event)
    flash('Event updated successfully!', 'success')
    step = {'santa': 'santa'}.get(section, 'details')
    return redirect(url_for('admin.manage_event', event_id=event_id, step=step))


# ==================== SETTINGS ====================

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    app_settings = AppSettings.query.first()

    if not app_settings:
        app_settings = AppSettings()
        db.session.add(app_settings)
        db.session.commit()

    if request.method == 'POST':
        app_settings.site_name = request.form.get('site_name', '').strip() or 'Family Christmas'
        app_settings.allow_signups = request.form.get('allow_signups') == 'on'
        app_settings.signup_question = request.form.get('signup_question', '').strip()[:200] or None
        app_settings.signup_answers = request.form.get('signup_answers', '').strip()[:300] or None
        app_settings.signup_question_enabled = request.form.get('signup_question_enabled') == 'on'
        if app_settings.signup_question_enabled and not (app_settings.signup_question and app_settings.accepted_answers()):
            app_settings.signup_question_enabled = False
            flash('The family question needs both a question and an answer - it has been left off.', 'warning')
        app_settings.reminders_enabled = request.form.get('reminders_enabled') == 'on'
        app_settings.empty_list_reminder_days = max(0, request.form.get('empty_list_reminder_days', 21, type=int) or 0)
        app_settings.countdown_reminder_days = max(0, request.form.get('countdown_reminder_days', 7, type=int) or 0)

        db.session.commit()
        log_activity('settings', 'Site name / sign-ups / reminders' + (
            ' (family question on)' if app_settings.signup_question_enabled else ''))
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('admin.settings'))

    mail_config = {
        'server': current_app.config.get('MAIL_SERVER'),
        'port': current_app.config.get('MAIL_PORT'),
        'username': current_app.config.get('MAIL_USERNAME'),
        'sender': current_app.config.get('MAIL_DEFAULT_SENDER'),
        'password_set': bool(current_app.config.get('MAIL_PASSWORD')),
    }
    push_users = db.session.query(PushSubscription.user_id).distinct().count()
    return render_template('admin/settings.html', settings=app_settings, mail_config=mail_config,
                           restore_enabled=True,
                           backups=backup_status(), human_size=human_size,
                           push_devices=PushSubscription.query.count(), push_users=push_users,
                           login_users=approved_users().filter(User.is_managed.is_(False)).count())


# ==================== WHO'S READY, NUDGES, ANNOUNCEMENTS ====================

@admin_bp.route('/events/<int:event_id>/status')
@login_required
@admin_required
def event_status(event_id):
    event = ChristmasEvent.query.get_or_404(event_id)
    rows = readiness(event, current_user)
    return render_template('admin/event_status.html', event=event, rows=rows,
                           summary=readiness_summary(rows, event),
                           announcements=event.announcements.limit(20).all())


@admin_bp.route('/events/<int:event_id>/nudge', methods=['POST'])
@login_required
@admin_required
def nudge(event_id):
    event = ChristmasEvent.query.get_or_404(event_id)
    summary = readiness_summary(readiness(event, current_user), event)
    if request.form.get('kind') == 'invites':
        sent = 0
        for user in summary['not_joined']:
            ok, _ = send_welcome(user)
            sent += ok
        log_activity('nudge', f'Invites resent to {sent} of {len(summary["not_joined"])} who have not signed in', event=event)
        flash(f'Sent {sent} welcome email{"s" if sent != 1 else ""} (each with a new temporary password).'
              if sent else 'No invites could be sent - check the email settings.', 'success' if sent else 'warning')
    else:
        sent = nudge_empty_lists(event, summary['empty'])
        log_activity('nudge', f'Empty-list nudge to {sent} people', event=event)
        flash(f'Nudged {sent} {"person" if sent == 1 else "people"} about their empty list.', 'success')
    return redirect(url_for('admin.event_status', event_id=event_id))


@admin_bp.route('/events/<int:event_id>/announce', methods=['POST'])
@login_required
@admin_required
def announce(event_id):
    event = ChristmasEvent.query.get_or_404(event_id)
    body = request.form.get('body', '').strip()[:1000]
    if not body:
        flash('Type a message first.', 'warning')
        return redirect(url_for('admin.event_status', event_id=event_id) + '#announce')
    _, count = post_announcement(event, current_user, body, email=request.form.get('email') == 'on')
    flash(f'Posted - {count} {"person was" if count == 1 else "people were"} notified.', 'success')
    return redirect(url_for('admin.event_status', event_id=event_id) + '#announce')


@admin_bp.route('/announcements/<int:announcement_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_announcement(announcement_id):
    note = Announcement.query.get_or_404(announcement_id)
    event_id = note.event_id
    db.session.delete(note)
    db.session.commit()
    flash('Announcement removed.', 'success')
    return redirect(url_for('admin.event_status', event_id=event_id) + '#announce')


@admin_bp.route('/events/<int:event_id>/export.csv')
@login_required
@admin_required
def export_lists(event_id):
    event = ChristmasEvent.query.get_or_404(event_id)
    filename = re.sub(r'[^A-Za-z0-9]+', '-', f'{event.name}-{event.year}-wishlists').strip('-') + '.csv'
    response = make_response(export_lists_csv(event, current_user))
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ==================== SECRET SANTA: CHANGES AFTER THE NAMES WENT OUT ====================

@admin_bp.route('/events/<int:event_id>/draw/remove/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def draw_remove(event_id, user_id):
    event = ChristmasEvent.query.get_or_404(event_id)
    user = User.query.get_or_404(user_id)
    try:
        changed = remove_from_draw(event, user)
        flash(f'{user.name} is out of the draw. ' + (
            f'{changed} {"person was" if changed == 1 else "people were"} sent a new name.' if changed
            else 'Nobody else needed a new name.'), 'success')
    except DrawError as e:
        flash(str(e), 'danger')
    return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id, step='draw'))


@admin_bp.route('/events/<int:event_id>/draw/add/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def draw_add(event_id, user_id):
    event = ChristmasEvent.query.get_or_404(event_id)
    user = User.query.get_or_404(user_id)
    try:
        add_to_draw(event, user)
        flash(f'{user.name} is in the draw and ' + ('was sent their name. One other person was sent a new name.'
              if event.assignments_sent else 'has a name.'), 'success')
    except DrawError as e:
        flash(str(e), 'danger')
    return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id, step='draw'))


# ==================== ACTIVITY ====================

@admin_bp.route('/activity')
@login_required
@admin_required
def activity():
    event_id = request.args.get('event_id', type=int)
    query = ActivityLog.query
    if event_id:
        query = query.filter_by(event_id=event_id)
    entries = query.order_by(ActivityLog.created_at.desc()).limit(300).all()
    events = {e.id: e for e in ChristmasEvent.query.all()}
    return render_template('admin/activity.html', entries=entries, events=events,
                           labels=ACTIVITY_LABELS, event_filter=events.get(event_id))


# ==================== BACKUP & MOVE ====================

@admin_bp.route('/backup/export', methods=['POST'])
@login_required
@admin_required
def backup_export():
    """Download everything (database + photos) as one passphrase-protected file"""
    import shutil
    from datetime import date
    from flask import send_file
    from app.backup import EXTENSION, BackupError, export_backup
    passphrase = request.form.get('passphrase', '')
    if passphrase != request.form.get('confirm_passphrase', ''):
        flash("The two passphrases don't match.", 'danger')
        return redirect(url_for('admin.settings') + '#backup')
    try:
        path, summary = export_backup(passphrase, app_version=current_app.config.get('APP_VERSION', ''))
    except BackupError as e:
        flash(str(e), 'danger')
        return redirect(url_for('admin.settings') + '#backup')
    log_activity('backup_exported', f"{summary['tables'].get('users', 0)} people, {summary['photos']} photos")
    name = re.sub(r'[^A-Za-z0-9]+', '-', get_site_name()).strip('-').lower() or 'wishlist'
    response = send_file(path, as_attachment=True, mimetype='application/octet-stream',
                         download_name=f'{name}-{date.today().isoformat()}{EXTENSION}')
    response.call_on_close(lambda: shutil.rmtree(os.path.dirname(path), ignore_errors=True))
    return response


@admin_bp.route('/backup/restore', methods=['POST'])
@login_required
@admin_required
def backup_restore():
    """Replace everything with a backup (guarded: admin password + typing RESTORE)"""
    from flask_login import logout_user
    from app.backup import BackupError, restart_workers_soon, restore_backup
    back = redirect(url_for('admin.settings') + '#restore')
    if not current_user.check_password(request.form.get('password', '')):
        flash('Your password is not right.', 'danger')
        return back
    if request.form.get('confirm', '').strip().upper() != 'RESTORE':
        flash('Type RESTORE to confirm - this replaces everything.', 'danger')
        return back
    upload = request.files.get('backup_file')
    if not upload or not upload.filename:
        flash('Choose the backup file.', 'danger')
        return back
    path = save_upload_to_temp(upload)
    try:
        summary = restore_backup(path, request.form.get('passphrase', ''))
    except BackupError as e:
        flash(str(e), 'danger')
        return back
    finally:
        os.remove(path)
    logout_user()
    flash(f"Restored {summary['people']} people, {summary['events']} events and {summary['photos']} photos. "
          'Sign in with your account from the backup.', 'success')
    response = redirect(url_for('auth.login'))
    restart = restart_workers_soon(request)
    if restart:
        response.call_on_close(restart)
    return response


def save_upload_to_temp(upload):
    import tempfile
    handle, path = tempfile.mkstemp(suffix='.xmasbackup')
    with os.fdopen(handle, 'wb') as f:
        upload.save(f)
    return path
