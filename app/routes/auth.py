import re
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
import secrets
from app import db, mail
from app.models import User, PasswordResetToken
from app.utils import get_external_url, get_site_name
from flask_mail import Message

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.must_change_password:
            return redirect(url_for('auth.change_password'))
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))

        if too_many_failures(email):
            flash('Too many wrong passwords - please wait 15 minutes and try again, '
                  'or use "Forgot your password?".', 'danger')
            return render_template('auth/login.html'), 429

        user = User.query.filter_by(email=email).first()
        if not (user and user.check_password(password)):
            record_failure(email)

        if user and not user.is_approved and user.check_password(password):
            flash("Thanks for your patience - an organizer still needs to approve your account. "
                  "You'll get an email as soon as they do.", 'info')
            return render_template('auth/login.html')

        # Managed people (e.g. young children) have no login of their own
        if user and user.is_approved and not user.is_managed and user.check_password(password):
            clear_failures(email)
            login_user(user, remember=remember)
            session.pop('event_choice_asked', None)   # ask which event to focus on again
            first_time = user.last_login is None
            user.last_login = user.last_seen_at = datetime.utcnow()
            db.session.commit()
            if first_time:
                from app.admin_tools import notify_admins_joined
                notify_admins_joined(user)

            if user.must_change_password:
                flash('Please change your temporary password.', 'warning')
                return redirect(url_for('auth.change_password'))

            # Only follow relative "next" links so the login page can't be used
            # to bounce people to another site
            next_page = request.args.get('next', '')
            if not next_page.startswith('/') or next_page.startswith('//') or '\\' in next_page:
                next_page = None
            return redirect(next_page or url_for('main.dashboard'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not current_user.check_password(current_password):
            flash('Current password is incorrect.', 'danger')
            return render_template('auth/change_password.html')

        if len(new_password) < 6:
            flash('New password must be at least 6 characters.', 'danger')
            return render_template('auth/change_password.html')

        if new_password != confirm_password:
            flash('New passwords do not match.', 'danger')
            return render_template('auth/change_password.html')

        current_user.set_password(new_password)
        current_user.must_change_password = False
        db.session.commit()

        flash('Password changed successfully!', 'success')
        return redirect(url_for('main.dashboard'))

    return render_template('auth/change_password.html')


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        user = User.query.filter_by(email=email, is_managed=False, is_approved=True).first()

        if user:
            # Generate reset token
            token = secrets.token_urlsafe(32)
            reset_token = PasswordResetToken(
                user_id=user.id,
                token=token,
                expires_at=datetime.utcnow() + timedelta(hours=24)
            )
            db.session.add(reset_token)
            db.session.commit()

            # Send email
            try:
                reset_url = get_external_url('auth.reset_password', token=token)
                msg = Message(
                    f'🎄 Password Reset Request - {get_site_name()}',
                    recipients=[user.email]
                )
                msg.html = render_template('emails/password_reset.html',
                                          user=user, reset_url=reset_url)
                mail.send(msg)
                flash('Password reset instructions have been sent to your email.', 'success')
            except Exception as e:
                flash('Error sending email. Please contact an administrator.', 'danger')
                print(f"Email error: {e}")
        else:
            # Don't reveal if email exists
            flash('If an account exists with that email, reset instructions have been sent.', 'info')

        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    reset_token = PasswordResetToken.query.filter_by(token=token).first()

    if not reset_token or not reset_token.is_valid():
        flash('Invalid or expired reset link.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if len(new_password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('auth/reset_password.html', token=token)

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/reset_password.html', token=token)

        user = reset_token.user
        user.set_password(new_password)
        user.must_change_password = False
        reset_token.used = True
        db.session.commit()

        flash('Password reset successfully! Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


# ==================== REQUEST AN ACCOUNT ====================

# Simple flood protection for the public sign-up form (per process; fine for a family site)
_signup_times = {}
SIGNUPS_PER_HOUR = 5
MAX_PENDING = 25


def _client_ip():
    forwarded = request.headers.get('X-Forwarded-For', '')
    return (forwarded.split(',')[0].strip() or request.remote_addr or '?')[:64]


def _too_many_signups():
    now = datetime.utcnow()
    ip = _client_ip()
    recent = [t for t in _signup_times.get(ip, []) if now - t < timedelta(hours=1)]
    _signup_times[ip] = recent
    return len(recent) >= SIGNUPS_PER_HOUR


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    from app.models import AppSettings
    settings = AppSettings.query.first()
    if not settings or not settings.allow_signups:
        flash('New accounts are added by the organizer - ask them to add you.', 'info')
        return redirect(url_for('auth.login'))

    form = {'name': '', 'email': '', 'note': ''}
    if request.method == 'POST':
        form = {'name': request.form.get('name', '').strip()[:100],
                'email': request.form.get('email', '').lower().strip()[:120],
                'note': request.form.get('note', '').strip()[:300]}
        password = request.form.get('password', '')

        # Bots fill in every field, including this one people never see
        if request.form.get('website'):
            return render_template('auth/signup_sent.html', approved=False)
        error = None
        if not form['name'] or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', form['email']):
            error = 'Please enter your name and a valid email address.'
        elif len(password) < 8:
            error = 'Please choose a password of at least 8 characters.'
        elif password != request.form.get('confirm_password', ''):
            error = "The two passwords don't match."
        elif _too_many_signups() or User.query.filter_by(is_approved=False).count() >= MAX_PENDING:
            error = 'Too many requests right now - please try again later.'
        if error:
            flash(error, 'danger')
            return render_template('auth/signup.html', form=form, family_question=family_question())

        _signup_times.setdefault(_client_ip(), []).append(datetime.utcnow())
        # Knowing the family answer (Admin -> Settings) skips the wait for an admin
        family = settings.answer_matches(request.form.get('family_answer', ''))
        # Same answer whether or not the email is taken, so the form can't be used
        # to find out who has an account
        if not User.query.filter_by(email=form['email']).first():
            user = User(email=form['email'], name=form['name'], is_approved=family,
                        must_change_password=False, signup_note=form['note'] or None)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            from app.admin_tools import notify_admins_signup
            notify_admins_signup(user)
        return render_template('auth/signup_sent.html', approved=family)

    return render_template('auth/signup.html', form=form, family_question=family_question())


def family_question():
    """The admin's question, if that feature is switched on in Settings"""
    from app.models import AppSettings
    settings = AppSettings.query.first()
    return settings.signup_question if settings and settings.signup_question_active() else None


# ==================== SIGN-IN PROTECTION ====================

FAILURE_WINDOW = timedelta(minutes=15)
MAX_FAILURES_PER_EMAIL = 5      # wrong passwords for one account
MAX_FAILURES_PER_IP = 20        # wrong passwords from one address (any accounts)


def too_many_failures(email):
    from app.models import LoginFailure
    since = datetime.utcnow() - FAILURE_WINDOW
    recent = LoginFailure.query.filter(LoginFailure.created_at >= since)
    return (recent.filter_by(email=email).count() >= MAX_FAILURES_PER_EMAIL
            or recent.filter_by(ip=_client_ip()).count() >= MAX_FAILURES_PER_IP)


def record_failure(email):
    from app.models import LoginFailure
    db.session.add(LoginFailure(ip=_client_ip(), email=email[:120]))
    LoginFailure.query.filter(LoginFailure.created_at < datetime.utcnow() - timedelta(days=1)).delete()
    db.session.commit()


def clear_failures(email):
    from app.models import LoginFailure
    LoginFailure.query.filter_by(email=email).delete()
    db.session.commit()


# ==================== FIRST RUN: CREATE THE ADMIN ====================

@auth_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    """Create the first admin account. Protected by the setup code in the container log."""
    from app.models import AppSettings
    if User.query.filter_by(is_admin=True).first() is not None:
        return redirect(url_for('auth.login'))
    settings = AppSettings.query.first()
    form = {'name': '', 'email': '', 'site_name': settings.site_name or 'Family Christmas'}

    if request.method == 'POST':
        form = {'name': request.form.get('name', '').strip()[:100],
                'email': request.form.get('email', '').lower().strip()[:120],
                'site_name': request.form.get('site_name', '').strip()[:100] or 'Family Christmas'}
        password = request.form.get('password', '')
        code = request.form.get('setup_code', '').strip().upper().replace(' ', '')
        error = None
        if too_many_failures('setup'):
            error = 'Too many wrong setup codes - please wait 15 minutes.'
        elif not settings.setup_code or not secrets.compare_digest(code, settings.setup_code):
            record_failure('setup')
            error = "That setup code isn't right. It's printed in the container log (Unraid: Docker tab → app icon → Logs)."
        elif not form['name'] or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', form['email']):
            error = 'Please enter your name and a valid email address.'
        elif len(password) < 8:
            error = 'Please choose a password of at least 8 characters.'
        elif password != request.form.get('confirm_password', ''):
            error = "The two passwords don't match."
        if error:
            flash(error, 'danger')
            return render_template('auth/setup.html', form=form)

        admin = User.query.filter_by(email=form['email']).first() or User(email=form['email'])
        admin.name, admin.is_admin, admin.is_approved = form['name'], True, True
        admin.must_change_password = False
        admin.set_password(password)
        db.session.add(admin)
        settings.site_name = form['site_name']
        settings.setup_code = None
        db.session.commit()
        current_app.config['HAS_ADMIN'] = True
        login_user(admin)
        admin.last_login = admin.last_seen_at = datetime.utcnow()
        db.session.commit()
        from app.admin_tools import log_activity
        log_activity('user_added', f'{admin.name} created the admin account (first run)', actor=admin)
        flash("You're all set! Next: create your first event, then add your family.", 'success')
        return redirect(url_for('admin.admin_dashboard'))

    return render_template('auth/setup.html', form=form)
