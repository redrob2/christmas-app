from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from config import config
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
import os
import secrets
import sqlite3
import time

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
migrate = Migrate()
csrf = CSRFProtect()

login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'


def create_app(config_name='default'):
    basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    app = Flask(__name__,
                template_folder=os.path.join(basedir, 'templates'),
                static_folder=os.path.join(basedir, 'static'))
    app.request_class = AppRequest

    app.config.from_object(config[config_name])
    prepare_storage(app)
    if app.config.get('TRUST_PROXY'):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    # Ensure upload directories exist
    upload_folder = app.config.get('UPLOAD_FOLDER', '/app/data/uploads')
    os.makedirs(os.path.join(upload_folder, 'profiles'), exist_ok=True)
    os.makedirs(os.path.join(upload_folder, 'items'), exist_ok=True)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    from app.routes.events import events_bp
    from app.routes.wishlist import wishlist_bp
    from app.routes.secretsanta import secretsanta_bp
    from app.routes.profile import profile_bp
    from app.routes.pwa import pwa_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(events_bp, url_prefix='/events')
    app.register_blueprint(wishlist_bp, url_prefix='/wishlist')
    app.register_blueprint(secretsanta_bp, url_prefix='/secretsanta')
    app.register_blueprint(profile_bp, url_prefix='/profile')
    app.register_blueprint(pwa_bp)

    from app.reminders import register_cli
    register_cli(app)
    from app.link_preview import register_cli as register_link_cli
    register_link_cli(app)
    from app.copy_db import register_cli as register_copy_cli
    register_copy_cli(app)

    # Cache-busting: static links carry the file's timestamp (?v=...), so browsers
    # load the new CSS/JS straight after an update instead of a stale cached copy
    static_versions = {}

    @app.url_defaults
    def static_version(endpoint, values):
        if endpoint == 'static' and 'filename' in values and 'v' not in values:
            name = values['filename']
            if name not in static_versions:
                try:
                    static_versions[name] = int(os.stat(os.path.join(app.static_folder, name)).st_mtime)
                except OSError:
                    static_versions[name] = 0
            values['v'] = static_versions[name]

    # Changes whenever the code, templates or static files change: the service
    # worker uses it to refresh its cache, and open pages to offer a reload
    from app.routes.pwa import compute_app_version
    app.config['APP_VERSION'] = compute_app_version(basedir)

    def signups_open():
        from app.models import AppSettings
        settings = AppSettings.query.first()
        return bool(settings and settings.allow_signups)

    @app.context_processor
    def utility_processor():
        from flask import has_request_context
        from flask_login import current_user
        from app.utils import get_app_name, get_external_url, get_site_name
        from app.push import public_key
        unread = pending = 0
        running = []
        # (emails rendered by the reminder scheduler have no request/user)
        if has_request_context() and current_user.is_authenticated:
            from app.routes.secretsanta import unread_message_count
            unread = unread_message_count(current_user)
            if current_user.is_admin:
                from app.models import User
                pending = User.query.filter_by(is_approved=False).count()
            else:
                from app.utils import coordinated_events
                running = coordinated_events(current_user)
        return dict(external_url=get_external_url, site_name=get_site_name(), app_name=get_app_name(),
                    unread_santa_messages=unread, pending_signups=pending, push_public_key=public_key,
                    signups_open=signups_open, events_i_run=running,
                    app_version=app.config['APP_VERSION'])

    from flask_wtf.csrf import CSRFError

    @app.errorhandler(413)
    def too_large(e):
        from flask import flash, redirect, request, url_for
        flash('That file is too large to upload.', 'danger')
        referrer = request.referrer or ''
        return redirect(referrer if referrer.startswith(request.host_url) else url_for('main.index'))

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        """Expired/missing form token (e.g. a page left open overnight): retry instead of a bare 400"""
        from flask import flash, redirect, request, url_for
        if request.is_json or request.accept_mimetypes.best == 'application/json':
            return {'error': 'Your session expired. Please reload the page and try again.'}, 400
        flash('Your session expired - please try that again.', 'warning')
        referrer = request.referrer or ''
        host = request.host_url
        return redirect(referrer if referrer.startswith(host) else url_for('main.index'))

    @app.template_filter('localtime')
    def localtime_filter(value, fmt='%b %d, %I:%M %p'):
        """Stored UTC timestamp -> server-local time (TZ in .env)"""
        from datetime import timezone
        if value is None:
            return ''
        return value.replace(tzinfo=timezone.utc).astimezone().strftime(fmt)

    @app.template_filter('money')
    def money_filter(value):
        if value is None:
            return ''
        return f"${value:,.2f}".replace('.00', '')

    @app.before_request
    def first_run_setup():
        """Until an admin account exists, every page leads to the setup page"""
        from flask import redirect, request, url_for
        if app.config.get('HAS_ADMIN') or request.endpoint in (
                None, 'static', 'healthz', 'auth.setup', 'auth.setup_restore', 'pwa.service_worker', 'pwa.manifest',
                'pwa.offline', 'pwa.app_version'):
            return None
        from app.models import User
        if User.query.filter_by(is_admin=True).first() is not None:
            app.config['HAS_ADMIN'] = True
            return None
        return redirect(url_for('auth.setup'))

    @app.before_request
    def record_last_seen():
        """Remember when each person last used the app (for "Online now" on the admin pages)"""
        from flask import request
        from flask_login import current_user
        if request.endpoint in (None, 'static', 'healthz', 'pwa.service_worker', 'pwa.manifest'):
            return
        if not current_user.is_authenticated:
            return
        from datetime import datetime
        from app.models import SEEN_EVERY, User
        now = datetime.utcnow()
        if current_user.last_seen_at is None or now - current_user.last_seen_at > SEEN_EVERY:
            try:
                db.session.execute(db.update(User).where(User.id == current_user.id).values(last_seen_at=now))
                db.session.commit()
                current_user.last_seen_at = now
            except Exception:
                db.session.rollback()

    @app.template_filter('seen_ago')
    def seen_ago_filter(value):
        """UTC timestamp -> 'Online now' / '12 min ago' / '3 hours ago' / 'Yesterday' / 'Oct 4'"""
        from datetime import datetime, timezone
        if value is None:
            return ''
        minutes = (datetime.utcnow() - value).total_seconds() / 60
        if minutes < 5:
            return 'Online now'
        if minutes < 60:
            return f'{int(minutes)} min ago'
        if minutes < 24 * 60:
            hours = int(minutes // 60)
            return f'{hours} hour{"s" if hours != 1 else ""} ago'
        local = value.replace(tzinfo=timezone.utc).astimezone()
        days = (datetime.now().date() - local.date()).days
        if days <= 1:
            return 'Yesterday'
        if days < 7:
            return f'{days} days ago'
        return local.strftime('%b ') + str(local.day) + (local.strftime(', %Y') if local.year != datetime.now().year else '')

    @app.route('/healthz')
    def healthz():
        """Container health check - verifies the database is reachable"""
        try:
            db.session.execute(text('SELECT 1'))
            return {'status': 'ok'}
        except Exception as e:
            db.session.rollback()
            return {'status': 'error', 'detail': str(e)}, 503

    # Create tables
    with app.app_context():
        wait_for_database()
        db.create_all()
        add_missing_columns()
        from app.models import User, AppSettings
        # Create default app settings if not exists
        settings = AppSettings.query.first()
        if not settings:
            settings = AppSettings(site_name='Family Christmas')
            db.session.add(settings)
            db.session.commit()

        # No built-in admin account: until one is created on the first-run page,
        # that page asks for a one-time setup code shown in the container log
        if User.query.filter_by(is_admin=True).first() is None:
            if not settings.setup_code:
                settings.setup_code = '-'.join(secrets.token_hex(2).upper() for _ in range(3))
                db.session.commit()
            print('\n' + '=' * 64 + '\n  First run: open the web page and create the admin account.\n'
                  f'  Setup code: {settings.setup_code}\n' + '=' * 64 + '\n', flush=True)
        elif settings.setup_code:
            settings.setup_code = None
            db.session.commit()

        from app.push import ensure_vapid_keys
        ensure_vapid_keys()

        # ($0 contributions saved by older versions meant "not chipping in")
        from app.models import GiftContribution
        if GiftContribution.query.filter(GiftContribution.amount == 0).delete():
            db.session.commit()

        # Gunicorn runs this once (--preload) and then forks workers; drop the
        # pooled connections so each worker opens its own
        db.session.remove()
        db.engine.dispose()

    return app


from flask import Request


class AppRequest(Request):
    """Uploads are capped at 16 MB (MAX_CONTENT_LENGTH), except backup restores"""
    BIG_UPLOADS = ('/setup/restore', '/admin/backup/restore')

    @property
    def max_content_length(self):
        if self.path in self.BIG_UPLOADS:
            return 8 * 1024 ** 3
        return super().max_content_length

    @max_content_length.setter
    def max_content_length(self, value):
        Request.max_content_length.fset(self, value)


def prepare_storage(app):
    """Database engine settings, data folders and a generated secret key"""
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    data_path = app.config.get('DATA_PATH') or '/app/data'
    if uri.startswith('sqlite'):
        path = uri.split(':///', 1)[-1]
        if path and path != ':memory:':
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        # wait up to 30s for a lock instead of failing ("database is locked")
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'timeout': 30}}
        global _sqlite_journal_mode
        mode = app.config.get('SQLITE_JOURNAL_MODE', 'delete')
        _sqlite_journal_mode = mode if mode in ('wal', 'delete', 'truncate') else 'delete'

    if not app.config.get('SECRET_KEY'):
        os.makedirs(data_path, exist_ok=True)
        key_file = os.path.join(data_path, 'secret_key')
        if not os.path.exists(key_file):
            with open(key_file, 'w') as f:
                f.write(secrets.token_hex(32))
            try:
                os.chmod(key_file, 0o600)
            except OSError:
                pass
            print(f'[setup] generated a secret key in {key_file}', flush=True)
        with open(key_file) as f:
            app.config['SECRET_KEY'] = f.read().strip()


_sqlite_journal_mode = 'delete'


@event.listens_for(Engine, 'connect')
def _sqlite_pragmas(dbapi_connection, connection_record):
    """SQLite: journal mode (see SQLITE_JOURNAL_MODE), enforce foreign keys, wait for locks"""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute(f'PRAGMA journal_mode={_sqlite_journal_mode.upper()}')
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA busy_timeout=30000')
        cursor.close()


def add_missing_columns():
    """Bring existing tables up to date with the models.

    create_all() only creates missing *tables*; when an update adds a column to
    an existing table, every query on it fails ("column ... does not exist").
    This adds such columns (with their default) so updates need no manual
    migration. It only ever adds - it never drops or changes existing columns.
    """
    from sqlalchemy import inspect, literal
    from app import models  # noqa: F401  (make sure every model is registered)

    inspector = inspect(db.engine)
    dialect = db.engine.dialect
    with db.engine.begin() as conn:
        for table in db.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c['name'] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                sql = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(dialect=dialect)}'
                default = column.default.arg if column.default is not None and column.default.is_scalar else None
                if default is not None:
                    default_sql = literal(default, column.type).compile(
                        dialect=dialect, compile_kwargs={'literal_binds': True})
                    sql += f' DEFAULT {default_sql}'
                    if not column.nullable:
                        sql += ' NOT NULL'
                conn.execute(text(sql))
                print(f"[upgrade] added column {table.name}.{column.name}", flush=True)


def wait_for_database(timeout=90):
    """Retry until the database accepts connections (it may still be starting)"""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with db.engine.connect() as conn:
                conn.execute(text('SELECT 1'))
            return
        except Exception as e:
            if time.monotonic() > deadline:
                raise
            print(f"Waiting for database... ({e.__class__.__name__})", flush=True)
            time.sleep(2)
