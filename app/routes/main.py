from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user
from app import db
from app.models import Announcement, EventParticipant, User, WishList, WishListItem
from app.event_data import (user_events, current_event, soonest_event, santa_info, shopping_stats,
                            family_summary)
from app.routes.secretsanta import mark_seen, unread_message_count

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Home: the current event at a glance - your Secret Santa, your list, your shopping, the family"""
    if current_user.must_change_password:
        return redirect(url_for('auth.change_password'))

    events = user_events(current_user)
    # In several events and never picked one? Ask once per login (skipping = soonest)
    if (len(events) > 1 and not any(e.id == current_user.main_event_id for e in events)
            and not session.get('event_choice_asked')):
        return redirect(url_for('main.choose_event'))
    event = current_event(events, current_user)
    if not event:
        return render_template('main/dashboard.html', event=None, other_events=[])

    participation = EventParticipant.query.filter_by(event_id=event.id, user_id=current_user.id).first()
    santa = santa_info(event, current_user)
    my_list = WishList.query.filter_by(event_id=event.id, owner_id=current_user.id).first()
    my_items = my_list.items.order_by(WishListItem.priority.desc(), WishListItem.created_at).all() if my_list else []
    pick_id = santa['assignment'].receiver_id if santa['assignment'] else None
    if santa['assignment'] and event.assignments_sent:
        mark_seen(santa['assignment'])
    # Lists of people with no login (e.g. children) this person looks after
    managed_lists = (WishList.query.join(User, WishList.owner_id == User.id)
                     .filter(WishList.event_id == event.id, User.is_managed.is_(True),
                             User.managed_by_id == current_user.id).all())
    since = datetime.utcnow() - timedelta(days=45)
    announcements = event.announcements.filter(Announcement.created_at >= since).limit(3).all()

    return render_template('main/dashboard.html',
                          event=event,
                          other_events=[e for e in events if e.id != event.id],
                          participates=bool(participation and participation.participates_in_secret_santa
                                            and event.secret_santa_enabled),
                          santa=santa,
                          unread=unread_message_count(current_user, event.id),
                          my_list=my_list,
                          my_items=my_items,
                          shopping=shopping_stats(event, current_user),
                          family=family_summary(event, current_user, pick_id),
                          managed_lists=managed_lists,
                          announcements=announcements,
                          is_main_choice=current_user.main_event_id == event.id)


@main_bp.route('/choose-event')
@login_required
def choose_event():
    """Which event should Home focus on? (shown once after login for people in several)"""
    session['event_choice_asked'] = True
    events = user_events(current_user)
    if len(events) < 2:
        return redirect(url_for('main.dashboard'))
    soonest = soonest_event(events)
    ordered = sorted(events, key=lambda e: (e.id != soonest.id, e.event_date or date.max, -e.year))
    return render_template('main/choose_event.html', events=ordered, soonest=soonest,
                           chosen_id=current_user.main_event_id)


@main_bp.route('/main-event', methods=['POST'])
@login_required
def set_main_event():
    """Save the person's main event ("auto" = always the soonest)"""
    choice = request.form.get('event_id', 'auto')
    events = user_events(current_user)
    if choice == 'auto':
        current_user.main_event_id = None
        flash('Home will show whichever event is coming up soonest.', 'success')
    else:
        event = next((e for e in events if str(e.id) == choice), None)
        if not event:
            flash("That event isn't one of yours.", 'danger')
            return redirect(url_for('events.list_events'))
        current_user.main_event_id = event.id
        flash(f'{event.name} is now your main event.', 'success')
    db.session.commit()
    session['event_choice_asked'] = True
    next_page = request.form.get('next', '')
    if not next_page.startswith('/') or next_page.startswith('//'):
        next_page = url_for('main.dashboard')
    return redirect(next_page)


@main_bp.route('/wishlists')
@login_required
def wishlists():
    """Wishlists tab: everyone's lists for the current event"""
    event = current_event(user_events(current_user), current_user)
    if not event:
        flash("You haven't been added to an event yet.", 'info')
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('events.view_event', event_id=event.id))


@main_bp.route('/secret-santa')
@login_required
def secret_santa():
    """Secret Santa tab: the current event that has a draw"""
    event = current_event([e for e in user_events(current_user) if e.secret_santa_enabled], current_user)
    if not event:
        flash('None of your events has a Secret Santa draw right now.', 'info')
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('secretsanta.my_assignment', event_id=event.id))


@main_bp.route('/profile')
@login_required
def profile():
    return redirect(url_for('profile.view_profile'))
