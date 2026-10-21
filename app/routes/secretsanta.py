from flask import Blueprint, render_template, redirect, url_for, flash, current_app, request
from flask_login import login_required, current_user
from datetime import datetime
import random
import json
import os
from app import db, mail
from app.models import (ChristmasEvent, EventParticipant, SecretSantaAssignment,
                       ExclusionPair, User, WishList, SantaMessage)
from app.utils import admin_required, get_external_url
from app.push import send_push
from flask_mail import Message

secretsanta_bp = Blueprint('secretsanta', __name__)


@secretsanta_bp.before_request
def require_secret_santa_enabled():
    """Every Secret Santa page is off for events that don't use Secret Santa"""
    event_id = (request.view_args or {}).get('event_id')
    if event_id is None:
        return None
    event = db.session.get(ChristmasEvent, event_id)
    if event is None or event.secret_santa_enabled:
        return None
    flash(f'Secret Santa is turned off for {event.name}.', 'info')
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for('admin.manage_event', event_id=event_id, step='santa'))
    return redirect(url_for('events.view_event', event_id=event_id))


def get_exclusion_set(event_id):
    """Get set of user pairs that should not be assigned to each other for this event"""
    exclusions = ExclusionPair.query.filter_by(event_id=event_id).all()
    exclusion_set = set()
    for e in exclusions:
        exclusion_set.add((e.user1_id, e.user2_id))
        exclusion_set.add((e.user2_id, e.user1_id))
    return exclusion_set


def get_previous_year_assignments(event):
    """Get assignments from previous year to avoid repeats"""
    previous_events = ChristmasEvent.query.filter(
        ChristmasEvent.year == event.year - 1,
        ChristmasEvent.assignments_generated == True
    ).all()

    previous_assignments = set()
    for prev_event in previous_events:
        assignments = SecretSantaAssignment.query.filter_by(event_id=prev_event.id).all()
        for a in assignments:
            previous_assignments.add((a.giver_id, a.receiver_id))

    return previous_assignments


def generate_derangement(participants, exclusions, previous_assignments, max_attempts=1000):
    """
    Generate a random derangement (no one gets themselves) that respects exclusions
    and tries to avoid previous year pairings.
    """
    user_ids = [p.user_id for p in participants]
    n = len(user_ids)

    if n < 2:
        return None

    for attempt in range(max_attempts):
        # Start with a random shuffle
        receivers = user_ids.copy()
        random.shuffle(receivers)

        # Check if valid
        valid = True
        has_previous = False

        for i, giver_id in enumerate(user_ids):
            receiver_id = receivers[i]

            # No self-assignment
            if giver_id == receiver_id:
                valid = False
                break

            # Check exclusions
            if (giver_id, receiver_id) in exclusions:
                valid = False
                break

            # Check previous year (soft constraint - track but don't fail)
            if (giver_id, receiver_id) in previous_assignments:
                has_previous = True

        if valid:
            # If no previous year matches, or we've tried many times, accept it
            if not has_previous or attempt > max_attempts // 2:
                return list(zip(user_ids, receivers))

    # If we couldn't avoid previous year assignments, try one more time ignoring that constraint
    for _ in range(100):
        receivers = user_ids.copy()
        random.shuffle(receivers)

        valid = True
        for i, giver_id in enumerate(user_ids):
            receiver_id = receivers[i]
            if giver_id == receiver_id or (giver_id, receiver_id) in exclusions:
                valid = False
                break

        if valid:
            return list(zip(user_ids, receivers))

    return None


@secretsanta_bp.route('/event/<int:event_id>')
@login_required
@admin_required
def manage_secret_santa(event_id):
    """Secret Santa steps of the guided event setup (who's in, pairs, draw & send)"""
    from app.routes.admin import render_event_setup
    event = ChristmasEvent.query.get_or_404(event_id)
    step = request.args.get('step', 'santa')
    return render_event_setup(event, step if step in ('santa', 'draw') else 'santa')


@secretsanta_bp.route('/event/<int:event_id>/toggle-participation/<int:participant_id>', methods=['POST'])
@login_required
@admin_required
def toggle_participation(event_id, participant_id):
    event = ChristmasEvent.query.get_or_404(event_id)
    participant = EventParticipant.query.get_or_404(participant_id)

    if participant.event_id != event_id:
        flash('Invalid participant.', 'danger')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id))

    if event.assignments_sent:
        flash('Cannot change participation after emails have been sent.', 'danger')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id))

    if participant.user.is_managed and not participant.participates_in_secret_santa:
        flash(f"{participant.user.name} doesn't have a login, so they can't draw a name. "
              "Family can still buy from their list.", 'warning')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id))

    # Toggle participation
    participant.participates_in_secret_santa = not participant.participates_in_secret_santa
    db.session.commit()

    status = "included in" if participant.participates_in_secret_santa else "excluded from"
    flash(f'{participant.user.name} is now {status} Secret Santa.', 'success')

    return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id))


@secretsanta_bp.route('/event/<int:event_id>/add-exclusion', methods=['POST'])
@login_required
@admin_required
def add_exclusion(event_id):
    event = ChristmasEvent.query.get_or_404(event_id)

    if event.assignments_sent:
        flash('Cannot add exclusions after emails have been sent.', 'danger')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id))

    user1_id = request.form.get('user1_id', type=int)
    user2_id = request.form.get('user2_id', type=int)
    reason = request.form.get('reason', '').strip()

    if not user1_id or not user2_id:
        flash('Please select two people.', 'danger')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id))

    if user1_id == user2_id:
        flash('Cannot exclude someone from themselves.', 'danger')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id))

    # Check if exclusion already exists (in either direction)
    existing = ExclusionPair.query.filter_by(event_id=event_id).filter(
        db.or_(
            db.and_(ExclusionPair.user1_id == user1_id, ExclusionPair.user2_id == user2_id),
            db.and_(ExclusionPair.user1_id == user2_id, ExclusionPair.user2_id == user1_id)
        )
    ).first()

    if existing:
        flash('This exclusion pair already exists.', 'warning')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id))

    # Add exclusion
    exclusion = ExclusionPair(
        event_id=event_id,
        user1_id=user1_id,
        user2_id=user2_id,
        reason=reason
    )
    db.session.add(exclusion)
    db.session.commit()

    user1 = db.session.get(User, user1_id)
    user2 = db.session.get(User, user2_id)
    flash(f'Exclusion added: {user1.name} ↔ {user2.name}', 'success')

    return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id))


@secretsanta_bp.route('/event/<int:event_id>/remove-exclusion/<int:exclusion_id>', methods=['POST'])
@login_required
@admin_required
def remove_exclusion(event_id, exclusion_id):
    event = ChristmasEvent.query.get_or_404(event_id)
    exclusion = ExclusionPair.query.get_or_404(exclusion_id)

    if exclusion.event_id != event_id:
        flash('Invalid exclusion.', 'danger')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id))

    if event.assignments_sent:
        flash('Cannot remove exclusions after emails have been sent.', 'danger')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id))

    user1_name = exclusion.user1.name
    user2_name = exclusion.user2.name

    db.session.delete(exclusion)
    db.session.commit()

    flash(f'Exclusion removed: {user1_name} ↔ {user2_name}', 'success')
    return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id))


@secretsanta_bp.route('/event/<int:event_id>/generate', methods=['POST'])
@login_required
@admin_required
def generate_secret_santa(event_id):
    event = ChristmasEvent.query.get_or_404(event_id)

    if event.assignments_sent:
        flash('Cannot regenerate assignments after emails have been sent.', 'danger')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id, step='draw'))

    # Only get participants who are opted IN to Secret Santa
    participants = EventParticipant.query.filter_by(
        event_id=event_id,
        participates_in_secret_santa=True
    ).all()

    if len(participants) < 2:
        flash('Need at least 2 participating members to generate assignments.', 'danger')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id, step='draw'))

    # Get constraints (now event-specific)
    exclusions = get_exclusion_set(event_id)
    previous_assignments = get_previous_year_assignments(event)

    # Generate assignments
    assignments = generate_derangement(participants, exclusions, previous_assignments)

    if not assignments:
        flash('Could not generate valid assignments. Check exclusion pairs - you may have too many constraints.', 'danger')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id, step='draw'))

    # Clear existing assignments (and any Santa Q&A attached to them)
    old_ids = SecretSantaAssignment.query.filter_by(event_id=event_id).with_entities(SecretSantaAssignment.id)
    SantaMessage.query.filter(SantaMessage.assignment_id.in_(old_ids)).delete(synchronize_session=False)
    SecretSantaAssignment.query.filter_by(event_id=event_id).delete(synchronize_session=False)

    # Save new assignments
    for giver_id, receiver_id in assignments:
        assignment = SecretSantaAssignment(
            event_id=event_id,
            giver_id=giver_id,
            receiver_id=receiver_id
        )
        db.session.add(assignment)

    event.assignments_generated = True
    db.session.commit()

    # Save to file for backup
    save_assignments_to_file(event, assignments)
    from app.admin_tools import log_activity
    log_activity('names_drawn', f'{len(assignments)} people', event=event)

    flash(f'Secret Santa assignments generated for {len(assignments)} participants!', 'success')
    return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id, step='draw'))


def save_assignments_to_file(event, assignments):
    """Save assignments to JSON file for backup"""
    try:
        file_path = current_app.config.get('ASSIGNMENTS_FILE_PATH', '/app/data/assignments')
        os.makedirs(file_path, exist_ok=True)

        filename = f"{event.year}_{event.name.replace(' ', '_')}_{event.id}.json"
        full_path = os.path.join(file_path, filename)

        # Get user names for the file
        data = {
            'event_id': event.id,
            'event_name': event.name,
            'year': event.year,
            'generated_at': datetime.utcnow().isoformat(),
            'assignments': []
        }

        for giver_id, receiver_id in assignments:
            giver = db.session.get(User, giver_id)
            receiver = db.session.get(User, receiver_id)
            data['assignments'].append({
                'giver_id': giver_id,
                'giver_name': giver.name,
                'giver_email': giver.email,
                'receiver_id': receiver_id,
                'receiver_name': receiver.name,
                'receiver_email': receiver.email
            })

        with open(full_path, 'w') as f:
            json.dump(data, f, indent=2)

    except Exception as e:
        print(f"Error saving assignments to file: {e}")


@secretsanta_bp.route('/event/<int:event_id>/send', methods=['POST'])
@login_required
@admin_required
def send_notifications(event_id):
    event = ChristmasEvent.query.get_or_404(event_id)

    if not event.assignments_generated:
        flash('Generate assignments first.', 'danger')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id, step='draw'))

    assignments = SecretSantaAssignment.query.filter_by(event_id=event_id).all()
    sent_count = 0
    failed_count = 0

    for assignment in assignments:
        try:
            dashboard_url = get_external_url('main.dashboard')
            msg = Message(
                f'🎅 Your Secret Santa Assignment - {event.name}!',
                recipients=[assignment.giver.email]
            )
            msg.html = render_template('emails/secret_santa_assignment.html',
                                      event=event,
                                      giver=assignment.giver,
                                      receiver=assignment.receiver,
                                      dashboard_url=dashboard_url)
            mail.send(msg)
            assignment.notified_at = datetime.utcnow()
            sent_count += 1
        except Exception as e:
            print(f"Email error for {assignment.giver.email}: {e}")
            failed_count += 1

    event.assignments_sent = True
    db.session.commit()
    from app.admin_tools import log_activity
    log_activity('names_sent', f'{sent_count} emailed' + (f', {failed_count} failed' if failed_count else ''), event=event)

    # Lock-screen safe: says names are drawn, never whose
    send_push([a.giver for a in assignments], f'🎅 Names are drawn for {event.name}!',
              "Tap to see who you're buying for.",
              url=url_for('secretsanta.my_assignment', event_id=event.id), tag=f'santa-drawn-{event.id}')

    if failed_count == 0:
        flash(f'All {sent_count} notifications sent successfully!', 'success')
    else:
        flash(f'Sent {sent_count} notifications. {failed_count} failed.', 'warning')

    return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id, step='draw'))


@secretsanta_bp.route('/event/<int:event_id>/resend/<int:assignment_id>', methods=['POST'])
@login_required
@admin_required
def resend_notification(event_id, assignment_id):
    event = ChristmasEvent.query.get_or_404(event_id)
    assignment = SecretSantaAssignment.query.get_or_404(assignment_id)

    if assignment.event_id != event_id:
        flash('Invalid assignment.', 'danger')
        return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id, step='draw'))

    try:
        dashboard_url = get_external_url('main.dashboard')
        msg = Message(
            f'🎅 Your Secret Santa Assignment - {event.name}!',
            recipients=[assignment.giver.email]
        )
        msg.html = render_template('emails/secret_santa_assignment.html',
                                  event=event,
                                  giver=assignment.giver,
                                  receiver=assignment.receiver,
                                  dashboard_url=dashboard_url)
        mail.send(msg)
        assignment.notified_at = datetime.utcnow()
        db.session.commit()
        send_push(assignment.giver, f'🎅 Your Secret Santa pick for {event.name}',
                  "Tap to see who you're buying for.",
                  url=url_for('secretsanta.my_assignment', event_id=event.id), tag=f'santa-drawn-{event.id}')
        flash(f'Notification resent to {assignment.giver.name}.', 'success')
    except Exception as e:
        flash(f'Failed to send email: {e}', 'danger')

    return redirect(url_for('secretsanta.manage_secret_santa', event_id=event_id, step='draw'))




# ==================== MY SECRET SANTA + ANONYMOUS Q&A ====================

def unread_message_count(user, event_id=None):
    """Unread Santa messages for this user, in either role"""
    query = SantaMessage.query.join(SecretSantaAssignment).join(ChristmasEvent).filter(
        ChristmasEvent.secret_santa_enabled.is_(True),
        SantaMessage.read_at.is_(None),
        db.or_(
            db.and_(SecretSantaAssignment.giver_id == user.id, SantaMessage.from_santa.is_(False)),
            db.and_(SecretSantaAssignment.receiver_id == user.id, SantaMessage.from_santa.is_(True)),
        ))
    if event_id:
        query = query.filter(SecretSantaAssignment.event_id == event_id)
    return query.count()


def mark_seen(assignment):
    """The giver has now seen who they drew (shown to admins as a tick, never the name)"""
    if assignment and assignment.seen_at is None:
        assignment.seen_at = datetime.utcnow()
        db.session.commit()


def mark_read(assignment, from_santa):
    changed = False
    for message in assignment.messages:
        if message.from_santa == from_santa and message.read_at is None:
            message.read_at = datetime.utcnow()
            changed = True
    if changed:
        db.session.commit()


@secretsanta_bp.route('/my-assignment/<int:event_id>')
@login_required
def my_assignment(event_id):
    event = ChristmasEvent.query.get_or_404(event_id)

    # Check if user is a participant
    participation = EventParticipant.query.filter_by(
        event_id=event_id,
        user_id=current_user.id
    ).first()

    if not participation:
        flash('You are not a participant in this event.', 'danger')
        return redirect(url_for('main.dashboard'))

    # Me as the giver
    assignment = SecretSantaAssignment.query.filter_by(
        event_id=event_id,
        giver_id=current_user.id
    ).first()
    receiver_wishlist = None
    if assignment:
        receiver_wishlist = WishList.query.filter_by(event_id=event_id, owner_id=assignment.receiver_id).first()
        mark_read(assignment, from_santa=False)
        mark_seen(assignment)

    # Me as the recipient - whoever my Santa is stays anonymous
    my_santa = SecretSantaAssignment.query.filter_by(
        event_id=event_id,
        receiver_id=current_user.id
    ).first()
    if my_santa:
        mark_read(my_santa, from_santa=True)

    from app.event_data import santa_info
    santa = santa_info(event, current_user)
    return render_template('secretsanta/my_assignment.html',
                          event=event,
                          santa_spent=santa['spent'],
                          santa_gift_count=santa['gift_count'],
                          assignment=assignment,
                          receiver_wishlist=receiver_wishlist,
                          my_santa=my_santa,
                          participates=participation.participates_in_secret_santa)


@secretsanta_bp.route('/my-assignment/<int:event_id>/message', methods=['POST'])
@login_required
def send_santa_message(event_id):
    """Post a message in the anonymous thread.
    role=santa: I'm writing to the person I'm buying for (they won't see my name)
    role=recipient: I'm replying to my anonymous Secret Santa"""
    role = request.form.get('role')
    body = request.form.get('body', '').strip()[:2000]
    back = url_for('secretsanta.my_assignment', event_id=event_id)

    if role == 'santa':
        assignment = SecretSantaAssignment.query.filter_by(event_id=event_id, giver_id=current_user.id).first()
    else:
        assignment = SecretSantaAssignment.query.filter_by(event_id=event_id, receiver_id=current_user.id).first()

    if not assignment:
        flash('There is no Secret Santa assignment for that conversation.', 'danger')
        return redirect(back)
    if not body:
        flash('Please type a message first.', 'warning')
        return redirect(back)

    from_santa = role == 'santa'
    db.session.add(SantaMessage(assignment_id=assignment.id, from_santa=from_santa, body=body))
    db.session.commit()

    # Email the other side; a message from Santa never includes the giver's name
    other = assignment.receiver if from_santa else assignment.giver
    try:
        msg = Message('🎅 Your Secret Santa sent you a message' if from_santa
                      else f'🎁 {assignment.receiver.name} replied to your question',
                      recipients=[other.email])
        msg.html = render_template('emails/santa_message.html',
                                  event=assignment.event,
                                  recipient=other,
                                  from_santa=from_santa,
                                  sender_name=None if from_santa else assignment.receiver.name,
                                  body=body,
                                  link=get_external_url('secretsanta.my_assignment', event_id=event_id))
        mail.send(msg)
    except Exception as e:
        print(f"Email error: {e}")

    # Push: never names the Santa, and leaves the recipient's name off the giver's lock screen too
    preview = body if len(body) <= 140 else body[:137] + '...'
    if from_santa:
        title, anchor = '🎅 Your Secret Santa sent you a message', '#my-santa-thread'
    else:
        title, anchor = '🎁 The person you\'re buying for replied', '#santa-thread'
    send_push(other, title, preview, url=back + anchor, tag=f'santa-msg-{assignment.id}-{int(from_santa)}',
              badge=unread_message_count(other))

    flash('Message sent! 🤫' if from_santa else 'Reply sent to your Secret Santa!', 'success')
    return redirect(back + ('#santa-thread' if from_santa else '#my-santa-thread'))
