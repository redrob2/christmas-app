"""Builds a database like a real family install and fills it (people, lists, purchases,
Secret Santa, messages, notification sign-ups...). Works with this repo's code or an
older copy of it, to test copying from older versions.
usage: python seed_family.py <repo> <database-url>"""
import os, sys
from datetime import date, datetime, timedelta
from decimal import Decimal

repo, url = sys.argv[1], sys.argv[2]
os.environ.update(DATABASE_URL=url, SECRET_KEY='family-secret', PREFERRED_URL_SCHEME='http',
                  UPLOAD_FOLDER=os.path.join(os.path.dirname(__file__), '_up'),
                  ASSIGNMENTS_FILE_PATH=os.path.join(os.path.dirname(__file__), '_as'))
sys.path.insert(0, repo)
from app import create_app, db
app = create_app('production')
from app.models import *

with app.app_context():
    admin = User.query.filter_by(is_admin=True).first()
    if admin is None:   # (newer versions have no built-in admin)
        admin = User(email='rob@family.test', name='Rob', is_admin=True); db.session.add(admin)
    admin.email, admin.name = 'rob@family.test', 'Rob'
    admin.set_password('robpass123'); admin.must_change_password = False; admin.last_login = datetime.utcnow()
    people = {}
    for n in ['Elizabeth', 'Ann', 'Bob']:
        u = User(email=f'{n.lower()}@family.test', name=n, must_change_password=False, last_login=datetime.utcnow(),
                 birthday=date(1980, 12, 3), address='1 Snow Lane\nNorth Pole', about_me='Loves cocoa')
        u.set_password(f'{n.lower()}pass123'); db.session.add(u); people[n] = u
    db.session.commit()
    kid = User(email='managed-kid@managed.invalid', name='Maya', is_managed=True, managed_by_id=people['Elizabeth'].id,
               must_change_password=False)
    kid.set_password('x' * 30); db.session.add(kid)
    pending = User(email='zoe@family.test', name='Zoe', is_approved=False, signup_note="Ann's cousin")
    pending.set_password('zoepass123'); db.session.add(pending)
    ev = ChristmasEvent(name='Christmas 2026', year=2026, event_date=date(2026, 12, 25), budget=Decimal('50.00'),
                        lists_lock_date=date(2026, 12, 15), secret_santa_enabled=True)
    db.session.add(ev); db.session.commit()
    everyone = [admin] + list(people.values()) + [kid]
    for u in everyone:
        db.session.add(EventParticipant(event_id=ev.id, user_id=u.id, participates_in_secret_santa=not u.is_managed))
        db.session.add(WishList(event_id=ev.id, owner_id=u.id))
    db.session.commit()
    lists = {w.owner.name: w for w in WishList.query.all()}
    items = []
    for owner, name, price in [('Ann', 'Wool socks', '18.50'), ('Ann', 'Stand mixer', '399.99'),
                               ('Maya', 'Plush reindeer', '20'), ('Bob', 'Mystery novel', None)]:
        it = WishListItem(wishlist_id=lists[owner].id, name=name, price=Decimal(price) if price else None,
                          priority=2, url='https://example.com/x', notes='Any color\nexcept white', image='items/a.jpg')
        db.session.add(it); items.append(it)
    db.session.commit()
    db.session.add(ItemPurchase(item_id=items[0].id, purchaser_id=admin.id, status='wrapped', is_secret_santa=True))
    db.session.add(ItemPurchase(item_id=items[2].id, purchaser_id=people['Bob'].id))
    db.session.add(GiftContribution(item_id=items[1].id, user_id=people['Bob'].id, amount=Decimal('75.25')))
    order = [admin, people['Elizabeth'], people['Ann'], people['Bob']]
    for i, g in enumerate(order):
        db.session.add(SecretSantaAssignment(event_id=ev.id, giver_id=g.id, receiver_id=order[(i + 1) % 4].id,
                                             notified_at=datetime.utcnow(), seen_at=datetime.utcnow()))
    db.session.add(ExclusionPair(event_id=ev.id, user1_id=admin.id, user2_id=people['Elizabeth'].id, reason='Married'))
    ev.assignments_generated = ev.assignments_sent = True
    db.session.commit()
    a = SecretSantaAssignment.query.filter_by(giver_id=admin.id).first()
    db.session.add(SantaMessage(assignment_id=a.id, from_santa=True, body='Fiction or non-fiction? 🎄'))
    db.session.add(Announcement(event_id=ev.id, author_id=admin.id, body='Dinner at 5!'))
    db.session.add(PushSubscription(user_id=people['Ann'].id, endpoint='https://web.push.apple.com/abc',
                                    p256dh='B' * 87, auth='A' * 22, device='iPhone'))
    db.session.add(ReminderLog(event_id=ev.id, user_id=people['Bob'].id, kind='countdown'))
    s = AppSettings.query.first()
    s.site_name = 'The James Family'; s.signup_question_enabled = True
    s.signup_question = "Dog's name?"; s.signup_answers = 'Arthur'
    db.session.commit()
    from app.admin_tools import log_activity
    log_activity('names_sent', '4 emailed', event=ev, actor=admin)
    print('VAPID', s.vapid_private_key)
    print('COUNTS', {t.name: db.session.execute(db.select(db.func.count()).select_from(t)).scalar()
                     for t in db.metadata.sorted_tables})
