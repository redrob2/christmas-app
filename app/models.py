from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login_manager


# Someone counts as "online now" if they used the app this recently
ONLINE_WINDOW = timedelta(minutes=5)
# How often a visit updates last_seen_at (keeps database writes to a trickle)
SEEN_EVERY = timedelta(minutes=2)

# Available holiday icons for user profiles
HOLIDAY_ICONS = [
    {'id': 'tree', 'icon': 'fa-tree', 'name': 'Christmas Tree', 'color': '#228b22'},
    {'id': 'presents', 'icon': 'fa-gifts', 'name': 'Presents', 'color': '#c41e3a'},
    {'id': 'gift', 'icon': 'fa-gift', 'name': 'Gift', 'color': '#c41e3a'},
    {'id': 'snowflake', 'icon': 'fa-snowflake', 'name': 'Snowflake', 'color': '#87ceeb'},
    {'id': 'star', 'icon': 'fa-star', 'name': 'Star', 'color': '#ffd700'},
    {'id': 'bell', 'icon': 'fa-bell', 'name': 'Bell', 'color': '#ffd700'},
    {'id': 'candy-cane', 'icon': 'fa-candy-cane', 'name': 'Candy Cane', 'color': '#c41e3a'},
    {'id': 'sleigh', 'icon': 'fa-sleigh', 'name': 'Sleigh', 'color': '#8b4513'},
    {'id': 'snowman', 'icon': 'fa-snowman', 'name': 'Snowman', 'color': '#ffffff'},
    {'id': 'holly', 'icon': 'fa-holly-berry', 'name': 'Holly Berry', 'color': '#228b22'},
    {'id': 'mitten', 'icon': 'fa-mitten', 'name': 'Mitten', 'color': '#c41e3a'},
    {'id': 'cookie', 'icon': 'fa-cookie-bite', 'name': 'Cookie', 'color': '#d2691e'},
    {'id': 'mug', 'icon': 'fa-mug-hot', 'name': 'Hot Cocoa', 'color': '#8b4513'},
    {'id': 'heart', 'icon': 'fa-heart', 'name': 'Heart', 'color': '#c41e3a'},
    {'id': 'dove', 'icon': 'fa-dove', 'name': 'Dove', 'color': '#87ceeb'},
    {'id': 'ribbon', 'icon': 'fa-ribbon', 'name': 'Ribbon', 'color': '#c41e3a'},
    {'id': 'music', 'icon': 'fa-music', 'name': 'Caroling', 'color': '#228b22'},
    {'id': 'church', 'icon': 'fa-church', 'name': 'Church', 'color': '#8b4513'},
    {'id': 'candle', 'icon': 'fa-menorah', 'name': 'Candles', 'color': '#ffd700'},
    {'id': 'socks', 'icon': 'fa-socks', 'name': 'Stockings', 'color': '#c41e3a'},
]


def get_icon_by_id(icon_id):
    """Get icon details by ID"""
    for icon in HOLIDAY_ICONS:
        if icon['id'] == icon_id:
            return icon
    return HOLIDAY_ICONS[0]  # Default to tree


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class User(UserMixin, db.Model):
    """User model for authentication and profile"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    must_change_password = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    # Last time they used the app at all (updated every couple of minutes while active;
    # "Remember me" keeps people signed in for days, so last_login alone says little)
    last_seen_at = db.Column(db.DateTime)

    # Profile fields
    profile_icon = db.Column(db.String(50), default='tree')  # Fallback icon ID from HOLIDAY_ICONS
    profile_photo = db.Column(db.String(255))  # Original uploaded photo
    profile_photo_ai = db.Column(db.String(255))  # AI-transformed full-size image
    profile_photo_icon = db.Column(db.String(255))  # AI-transformed icon (resized)
    birthday = db.Column(db.Date)
    address = db.Column(db.Text)
    about_me = db.Column(db.Text)

    # The event Home and the tabs open on when they're in several. None = the soonest.
    # (No foreign key: a deleted event just falls back to the soonest.)
    main_event_id = db.Column(db.Integer)

    # Managed list (e.g. a young child): no login of their own; the person in
    # managed_by looks after their wishlist. They get a placeholder email.
    is_managed = db.Column(db.Boolean, default=False, nullable=False)

    # People who requested an account themselves wait here until an admin approves them
    is_approved = db.Column(db.Boolean, default=True, nullable=False)
    signup_note = db.Column(db.String(300))  # "who are you?" from the sign-up form
    managed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    managed_by = db.relationship('User', remote_side=[id], foreign_keys=[managed_by_id])

    # Relationships
    event_participations = db.relationship('EventParticipant', back_populates='user', lazy='dynamic')
    wishlists = db.relationship('WishList', back_populates='owner', lazy='dynamic')
    purchases = db.relationship('ItemPurchase', back_populates='purchaser', lazy='dynamic')
    secret_santa_giving = db.relationship('SecretSantaAssignment',
                                          foreign_keys='SecretSantaAssignment.giver_id',
                                          back_populates='giver', lazy='dynamic')
    secret_santa_receiving = db.relationship('SecretSantaAssignment',
                                             foreign_keys='SecretSantaAssignment.receiver_id',
                                             back_populates='receiver', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_icon(self):
        """Get the user's holiday icon details - fallback if no AI photo"""
        return get_icon_by_id(self.profile_icon or 'tree')

    def has_ai_photo(self):
        """Check if user has an AI-generated profile photo"""
        return bool(self.profile_photo_icon)

    @property
    def is_online(self):
        return self.last_seen_at is not None and datetime.utcnow() - self.last_seen_at < ONLINE_WINDOW

    @property
    def can_receive_mail(self):
        return not self.is_managed

    def __repr__(self):
        return f'<User {self.email}>'


class ChristmasEvent(db.Model):
    """Christmas event/year model"""
    __tablename__ = 'christmas_events'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text)
    event_date = db.Column(db.Date)  # The actual date of the event
    budget = db.Column(db.Numeric(10, 2))  # Secret Santa spending limit
    secret_santa_enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    assignments_generated = db.Column(db.Boolean, default=False)
    assignments_sent = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    # From this date on, wishlists can't be changed (so buyers aren't surprised late)
    lists_lock_date = db.Column(db.Date)

    # Relationships
    participants = db.relationship('EventParticipant', back_populates='event',
                                   lazy='dynamic', cascade='all, delete-orphan')
    wishlists = db.relationship('WishList', back_populates='event',
                                lazy='dynamic', cascade='all, delete-orphan')
    secret_santa_assignments = db.relationship('SecretSantaAssignment',
                                               back_populates='event',
                                               lazy='dynamic', cascade='all, delete-orphan')
    reminder_logs = db.relationship('ReminderLog', lazy='dynamic', cascade='all, delete-orphan')
    announcements = db.relationship('Announcement', back_populates='event', lazy='dynamic',
                                    order_by='Announcement.created_at.desc()', cascade='all, delete-orphan')
    custom_reminders = db.relationship('CustomReminder', back_populates='event', lazy='dynamic',
                                       cascade='all, delete-orphan')

    def lists_locked(self, today=None):
        today = today or datetime.now().date()
        return self.lists_lock_date is not None and today >= self.lists_lock_date

    def secret_santa_locked(self):
        """Assignments emailed out - participants and pairs can't change any more"""
        return self.secret_santa_enabled and self.assignments_sent

    def days_until(self):
        """Calculate days until the event date"""
        if not self.event_date:
            return None
        today = datetime.now().date()
        delta = self.event_date - today
        return delta.days

    def __repr__(self):
        return f'<ChristmasEvent {self.name} ({self.year})>'


class EventParticipant(db.Model):
    """Links users to Christmas events"""
    __tablename__ = 'event_participants'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('christmas_events.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    participates_in_secret_santa = db.Column(db.Boolean, default=True)  # Can opt out of Secret Santa
    # Put in the practice event automatically at sign-up; taken out again once
    # an admin adds them to a real event
    demo_auto = db.Column(db.Boolean, default=False, nullable=False)
    # Runs this event: its setup, people, Secret Santa, reminders and announcements
    # (site admins can do all of that for every event)
    is_coordinator = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    event = db.relationship('ChristmasEvent', back_populates='participants')
    user = db.relationship('User', back_populates='event_participations')

    __table_args__ = (db.UniqueConstraint('event_id', 'user_id', name='unique_event_participant'),)

    def __repr__(self):
        return f'<EventParticipant event={self.event_id} user={self.user_id}>'


class WishList(db.Model):
    """Wish list for a user in a specific event"""
    __tablename__ = 'wishlists'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('christmas_events.id'), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    event = db.relationship('ChristmasEvent', back_populates='wishlists')
    owner = db.relationship('User', back_populates='wishlists')
    items = db.relationship('WishListItem', back_populates='wishlist',
                            lazy='dynamic', cascade='all, delete-orphan')

    __table_args__ = (db.UniqueConstraint('event_id', 'owner_id', name='unique_wishlist_per_event'),)

    def __repr__(self):
        return f'<WishList event={self.event_id} owner={self.owner_id}>'


class WishListItem(db.Model):
    """Individual item on a wish list"""
    __tablename__ = 'wishlist_items'

    id = db.Column(db.Integer, primary_key=True)
    wishlist_id = db.Column(db.Integer, db.ForeignKey('wishlists.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500))
    color = db.Column(db.String(50))
    size = db.Column(db.String(50))
    notes = db.Column(db.Text)
    image = db.Column(db.String(255))  # Path to uploaded image
    price = db.Column(db.Numeric(10, 2))  # Approximate price
    priority = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    wishlist = db.relationship('WishList', back_populates='items')
    purchase = db.relationship('ItemPurchase', back_populates='item', uselist=False,
                               cascade='all, delete-orphan')
    contributions = db.relationship('GiftContribution', back_populates='item',
                                    order_by='GiftContribution.created_at',
                                    cascade='all, delete-orphan')

    def contribution_total(self):
        return sum((c.amount or 0) for c in self.contributions)

    def __repr__(self):
        return f'<WishListItem {self.name}>'


class ItemPurchase(db.Model):
    """Tracks who purchased which item"""
    __tablename__ = 'item_purchases'

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('wishlist_items.id'), nullable=False, unique=True)
    purchaser_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    purchased_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

    # Poem fields for gift game
    poem = db.Column(db.Text)  # Generated poem for the gift
    poem_generation_count = db.Column(db.Integer, default=0)  # Track regenerations (max 10)

    # Shopping progress: purchased -> wrapped -> given
    status = db.Column(db.String(20), default='purchased', nullable=False)

    # The buyer's own note that this is their Secret Santa gift. Only the buyer
    # ever sees it - showing it to others would reveal who they drew.
    is_secret_santa = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    item = db.relationship('WishListItem', back_populates='purchase')
    purchaser = db.relationship('User', back_populates='purchases')

    def can_generate_poem(self):
        """Check if more poem generations are allowed (max 10)"""
        return self.poem_generation_count < 10

    def __repr__(self):
        return f'<ItemPurchase item={self.item_id} by={self.purchaser_id}>'


# (value, label, Lucide icon name) for ItemPurchase.status
PURCHASE_STATUSES = [
    ('purchased', 'Bought', 'shopping-bag'),
    ('wrapped', 'Wrapped', 'gift'),
    ('given', 'Given', 'hand-heart'),
]


class GiftContribution(db.Model):
    """Someone chipping in toward a group gift"""
    __tablename__ = 'gift_contributions'

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('wishlist_items.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    item = db.relationship('WishListItem', back_populates='contributions')
    user = db.relationship('User')

    __table_args__ = (db.UniqueConstraint('item_id', 'user_id', name='unique_contribution_per_user'),)


class SecretSantaAssignment(db.Model):
    """Secret Santa assignments for an event"""
    __tablename__ = 'secret_santa_assignments'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('christmas_events.id'), nullable=False)
    giver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notified_at = db.Column(db.DateTime)
    # When the giver first saw who they drew (on Home or the Secret Santa page)
    seen_at = db.Column(db.DateTime)

    # Relationships
    event = db.relationship('ChristmasEvent', back_populates='secret_santa_assignments')
    giver = db.relationship('User', foreign_keys=[giver_id], back_populates='secret_santa_giving')
    receiver = db.relationship('User', foreign_keys=[receiver_id], back_populates='secret_santa_receiving')
    messages = db.relationship('SantaMessage', back_populates='assignment',
                               order_by='SantaMessage.created_at',
                               cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('event_id', 'giver_id', name='unique_giver_per_event'),
    )

    def __repr__(self):
        return f'<SecretSantaAssignment event={self.event_id} giver={self.giver_id} receiver={self.receiver_id}>'


class SantaMessage(db.Model):
    """Anonymous Q&A between a Secret Santa and their recipient.
    The recipient only ever sees "Your Secret Santa", never the giver's name."""
    __tablename__ = 'santa_messages'

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('secret_santa_assignments.id'), nullable=False)
    from_santa = db.Column(db.Boolean, nullable=False)  # True = giver wrote it, False = recipient
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime)

    assignment = db.relationship('SecretSantaAssignment', back_populates='messages')


class ReminderLog(db.Model):
    """Records reminder emails already sent so each is only sent once"""
    __tablename__ = 'reminder_logs'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('christmas_events.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('event_id', 'user_id', 'kind', name='unique_reminder'),)


class ExclusionPair(db.Model):
    """Pairs of users who should not be assigned to each other in Secret Santa for a specific event"""
    __tablename__ = 'exclusion_pairs'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('christmas_events.id'), nullable=False)
    user1_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user2_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships (deleting an event also deletes its exclusion pairs)
    event = db.relationship('ChristmasEvent',
                            backref=db.backref('exclusion_pairs', lazy='dynamic',
                                               cascade='all, delete-orphan'))
    user1 = db.relationship('User', foreign_keys=[user1_id])
    user2 = db.relationship('User', foreign_keys=[user2_id])

    __table_args__ = (
        db.UniqueConstraint('event_id', 'user1_id', 'user2_id', name='unique_exclusion_pair_per_event'),
    )

    def __repr__(self):
        return f'<ExclusionPair event={self.event_id} {self.user1_id} - {self.user2_id}>'


class AppSettings(db.Model):
    """Application settings (single row table)"""
    __tablename__ = 'app_settings'

    id = db.Column(db.Integer, primary_key=True)
    site_name = db.Column(db.String(100), default='Family Christmas')
    # Name under the icon when installed on a phone's home screen (keep it short)
    app_name = db.Column(db.String(30), default='Wishlist', nullable=False)
    # Reminder emails (sent daily by the "scheduler" service)
    reminders_enabled = db.Column(db.Boolean, default=True, nullable=False)
    empty_list_reminder_days = db.Column(db.Integer, default=21, nullable=False)
    countdown_reminder_days = db.Column(db.Integer, default=7, nullable=False)
    # "Request an account" link on the sign-in page (requests wait for an admin)
    allow_signups = db.Column(db.Boolean, default=True, nullable=False)
    # Optional "family question": a correct answer lets a new account skip approval
    # One-time code that protects the first-run "create the admin account" page
    setup_code = db.Column(db.String(20))
    signup_question_enabled = db.Column(db.Boolean, default=False, nullable=False)
    signup_question = db.Column(db.String(200))
    signup_answers = db.Column(db.String(300))  # accepted answers, comma-separated
    # Practice event: new sign-ups join it to try things out until they're added to a real event
    demo_event_id = db.Column(db.Integer)

    def signup_question_active(self):
        return bool(self.allow_signups and self.signup_question_enabled and self.signup_question
                    and self.accepted_answers())

    def accepted_answers(self):
        return {a.strip().casefold() for a in (self.signup_answers or '').split(',') if a.strip()}

    def answer_matches(self, answer):
        """Any capitalization; spaces around it don't matter"""
        return self.signup_question_active() and (answer or '').strip().casefold() in self.accepted_answers()
    # Push notification ("VAPID") key pair, created automatically on first start.
    # Keep it: replacing it silently cuts off every device that signed up.
    vapid_private_key = db.Column(db.String(100))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<AppSettings {self.site_name}>'


class PasswordResetToken(db.Model):
    """Password reset tokens"""
    __tablename__ = 'password_reset_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)

    # Relationships
    user = db.relationship('User')

    def is_valid(self):
        return not self.used and datetime.utcnow() < self.expires_at


class PushSubscription(db.Model):
    """A phone/computer that asked for notifications (one row per device and browser)"""
    __tablename__ = 'push_subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    endpoint = db.Column(db.String(1000), unique=True, nullable=False)
    p256dh = db.Column(db.String(200), nullable=False)
    auth = db.Column(db.String(100), nullable=False)
    device = db.Column(db.String(100))  # "iPhone", "Android", "Windows"... for the settings page
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime)

    user = db.relationship('User')


class Announcement(db.Model):
    """A note from the organizer to everyone in an event (shown on Home)"""
    __tablename__ = 'announcements'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('christmas_events.id'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event = db.relationship('ChristmasEvent', back_populates='announcements')
    author = db.relationship('User')


class ActivityLog(db.Model):
    """What admins and the app did (people added, names drawn, ...).
    Never records purchases or who drew whom. No foreign keys, so entries
    survive the people and events they mention being deleted."""
    __tablename__ = 'activity_log'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    actor_id = db.Column(db.Integer)
    actor_name = db.Column(db.String(100))
    event_id = db.Column(db.Integer)
    action = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.String(300))


class LoginFailure(db.Model):
    """Recent wrong-password attempts, for slowing down password guessing"""
    __tablename__ = 'login_failures'

    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(64), index=True)
    email = db.Column(db.String(120), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class CustomReminder(db.Model):
    """A reminder an admin writes for an event: email and/or notification, to everyone
    in the event or chosen people, sent right away or at a set time (by the scheduler)."""
    __tablename__ = 'custom_reminders'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('christmas_events.id'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    send_email = db.Column(db.Boolean, default=True, nullable=False)
    send_push = db.Column(db.Boolean, default=True, nullable=False)
    everyone = db.Column(db.Boolean, default=True, nullable=False)
    recipient_ids = db.Column(db.Text)            # comma-separated user ids when not everyone
    send_at = db.Column(db.DateTime, index=True)   # UTC; when it should go out
    status = db.Column(db.String(20), default='scheduled', nullable=False, index=True)  # scheduled/sending/sent/cancelled/failed
    sent_at = db.Column(db.DateTime)
    emailed = db.Column(db.Integer, default=0, nullable=False)
    pushed = db.Column(db.Integer, default=0, nullable=False)
    people = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event = db.relationship('ChristmasEvent', back_populates='custom_reminders')
    author = db.relationship('User')

    def chosen_ids(self):
        return [int(x) for x in (self.recipient_ids or '').split(',') if x.strip().isdigit()]
