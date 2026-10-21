"""Read-only helpers shared by Home, the Wishlists tab and the Secret Santa page"""
from datetime import date

from app.models import (ChristmasEvent, EventParticipant, GiftContribution, ItemPurchase,
                        SecretSantaAssignment, WishList, WishListItem)


def user_events(user, active_only=True):
    """Events this person is in (active ones by default)"""
    ids = [p.event_id for p in EventParticipant.query.filter_by(user_id=user.id)]
    query = ChristmasEvent.query.filter(ChristmasEvent.id.in_(ids))
    if active_only:
        query = query.filter(ChristmasEvent.is_active.is_(True))
    return query.order_by(ChristmasEvent.year.desc(), ChristmasEvent.id.desc()).all()


def soonest_event(events):
    """The next upcoming event, else one with no date set (newest year first),
    else the most recent past one."""
    if not events:
        return None
    today = date.today()
    upcoming = sorted((e for e in events if e.event_date and e.event_date >= today), key=lambda e: e.event_date)
    if upcoming:
        return upcoming[0]
    undated = [e for e in events if not e.event_date]
    if undated:
        return undated[0]
    return max(events, key=lambda e: e.event_date)


def current_event(events, user=None):
    """The event Home and the tabs open on: the person's chosen main event when it's
    still one of theirs and active, otherwise the soonest."""
    if user is not None and user.main_event_id:
        for event in events:
            if event.id == user.main_event_id:
                return event
    return soonest_event(events)


def santa_info(event, user):
    """The person's Secret Santa assignment and how much they've marked as their Santa gift"""
    info = {'assignment': None, 'receiver_wishlist': None, 'spent': 0, 'gift_count': 0}
    if not event.secret_santa_enabled:
        return info
    assignment = SecretSantaAssignment.query.filter_by(event_id=event.id, giver_id=user.id).first()
    if not assignment:
        return info
    info['assignment'] = assignment
    info['receiver_wishlist'] = WishList.query.filter_by(event_id=event.id, owner_id=assignment.receiver_id).first()
    gifts = (ItemPurchase.query.filter_by(purchaser_id=user.id, is_secret_santa=True)
             .join(WishListItem).join(WishList)
             .filter(WishList.event_id == event.id, WishList.owner_id == assignment.receiver_id).all())
    info['gift_count'] = len(gifts)
    info['spent'] = sum((g.item.price or 0) for g in gifts)
    return info


def shopping_stats(event, user):
    """Counts of the person's purchases in this event by status, plus money spent/pledged"""
    purchases = (ItemPurchase.query.filter_by(purchaser_id=user.id)
                 .join(WishListItem).join(WishList).filter(WishList.event_id == event.id).all())
    pledges = (GiftContribution.query.filter_by(user_id=user.id)
               .join(WishListItem).join(WishList).filter(WishList.event_id == event.id).all())
    stats = {'bought': len(purchases), 'wrapped': 0, 'given': 0, 'to_wrap': 0, 'pledges': len(pledges),
             'total': sum((p.item.price or 0) for p in purchases) + sum((c.amount or 0) for c in pledges)}
    for p in purchases:
        if p.status == 'wrapped':
            stats['wrapped'] += 1
        elif p.status == 'given':
            stats['given'] += 1
        else:
            stats['to_wrap'] += 1
    return stats


def family_summary(event, viewer, pick_id=None):
    """Everyone else's list in the event: counts, and whether anyone has bought for them yet.
    (Never used for the viewer's own list - that would spoil their surprise.)"""
    people = []
    for participant in EventParticipant.query.filter_by(event_id=event.id).all():
        if participant.user_id == viewer.id:
            continue
        wishlist = WishList.query.filter_by(event_id=event.id, owner_id=participant.user_id).first()
        if not wishlist:
            continue
        items = wishlist.items.all()
        bought = sum(1 for i in items if i.purchase)
        chipped = sum(1 for i in items if i.contributions and not i.purchase)
        people.append({
            'user': participant.user,
            'wishlist': wishlist,
            'item_count': len(items),
            'available': len(items) - bought,
            'bought': bought,
            'needs_gifts': bought == 0 and chipped == 0,
            'is_pick': participant.user_id == pick_id,
        })
    people.sort(key=lambda p: (not p['is_pick'], p['user'].name.lower()))
    return people
