from datetime import date
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import ChristmasEvent, EventParticipant, WishList
from app.event_data import santa_info, family_summary

events_bp = Blueprint('events', __name__)


@events_bp.route('/')
@login_required
def list_events():
    """Every event the user is part of, past ones included"""
    participations = EventParticipant.query.filter_by(user_id=current_user.id).all()
    event_ids = [p.event_id for p in participations]

    events = ChristmasEvent.query.filter(
        ChristmasEvent.id.in_(event_ids)
    ).order_by(ChristmasEvent.year.desc(), ChristmasEvent.name).all()

    from app.event_data import current_event
    active = [e for e in events if e.is_active]
    main = current_event(active, current_user)
    return render_template('events/list.html',
                           active=sorted(active, key=lambda e: (e.id != (main.id if main else None),
                                                                e.event_date or date.max, -e.year)),
                           past=[e for e in events if not e.is_active],
                           main=main,
                           main_is_chosen=bool(main and current_user.main_event_id == main.id))


@events_bp.route('/<int:event_id>')
@login_required
def view_event(event_id):
    """Wishlists tab for one event: your list plus everyone else's"""
    event = ChristmasEvent.query.get_or_404(event_id)

    participation = EventParticipant.query.filter_by(event_id=event_id, user_id=current_user.id).first()
    if not participation and not current_user.is_admin:
        flash('You are not a participant in this event.', 'danger')
        return redirect(url_for('main.dashboard'))

    santa = santa_info(event, current_user)
    user_wishlist = WishList.query.filter_by(event_id=event_id, owner_id=current_user.id).first()
    pick_id = santa['assignment'].receiver_id if santa['assignment'] else None
    family = family_summary(event, current_user, pick_id)

    return render_template('events/view.html',
                          event=event,
                          santa=santa,
                          user_wishlist=user_wishlist,
                          # only the item count for your own list - what was bought stays a surprise
                          user_item_count=user_wishlist.items.count() if user_wishlist else 0,
                          family=family,
                          need_count=sum(1 for p in family if p['needs_gifts']))
