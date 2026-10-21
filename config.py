import os
from datetime import timedelta

# Everything the app keeps (database file, photos, generated keys) lives here.
# In the container this is the appdata folder mapped to /app/data.
DATA_PATH = os.environ.get('DATA_PATH') or '/app/data'


def _public_address():
    """(scheme, host) used for links in emails and notifications.
    PUBLIC_URL (e.g. https://wishlist.example.com) is the simple way to set it."""
    url = (os.environ.get('PUBLIC_URL') or '').strip().rstrip('/')
    if '://' in url:
        scheme, host = url.split('://', 1)
        if host:
            return scheme.lower(), host.split('/')[0]
    host = os.environ.get('SERVER_NAME_FOR_EMAILS') or 'localhost:8123'
    return (os.environ.get('PREFERRED_URL_SCHEME') or ('http' if host.startswith('localhost') else 'https')), host


_SCHEME, _HOST = _public_address()


class Config:
    """Base configuration"""
    # No built-in secret: SECRET_KEY from the environment, otherwise one is
    # generated on first start and kept in DATA_PATH/secret_key (see create_app)
    SECRET_KEY = os.environ.get('SECRET_KEY') or None
    DATA_PATH = DATA_PATH

    # Public address, for links in emails and notifications
    SERVER_NAME_FOR_EMAILS = _HOST
    PREFERRED_URL_SCHEME = _SCHEME

    # Database: a SQLite file in the appdata folder unless DATABASE_URL points
    # at PostgreSQL (postgresql://user:password@host:5432/dbname)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f'sqlite:///{DATA_PATH}/wishlist.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # pool_pre_ping discards connections that died while the database was
    # restarted (e.g. maintenance), instead of failing the next request
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 1800,
    }

    # Email configuration
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or 'smtp.gmail.com'
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', '1', 'yes']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or MAIL_USERNAME

    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    # Browsers won't send the login cookie on cross-site form posts (CSRF mitigation)
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True

    # Secret Santa assignments file path
    ASSIGNMENTS_FILE_PATH = os.environ.get('ASSIGNMENTS_FILE_PATH') or f'{DATA_PATH}/assignments'

    # File upload configuration
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or f'{DATA_PATH}/uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

    # Gemini AI API Key for photo transformation and gift poems
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    # Model names - override in .env when Google retires a model
    GEMINI_IMAGE_MODEL = os.environ.get('GEMINI_IMAGE_MODEL') or 'gemini-3-pro-image'
    GEMINI_IMAGE_FALLBACK_MODEL = os.environ.get('GEMINI_IMAGE_FALLBACK_MODEL') or 'gemini-3.1-flash-image'
    GEMINI_TEXT_MODEL = os.environ.get('GEMINI_TEXT_MODEL') or 'gemini-3.6-flash'

    # Optional: a folder of pg_dump backups to report on in Admin -> Settings
    # (the Unraid install relies on the Appdata Backup plugin instead)
    BACKUP_STATUS_DIR = os.environ.get('BACKUP_STATUS_DIR') or None

    # Push notifications. The key pair is generated and stored in the database
    # automatically; set VAPID_PRIVATE_KEY only to supply your own.
    VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')
    # Contact address push services may use (an https:// URL or mailto:)
    # (push services accept only "mailto:address" or a bare "https://domain" - no path or port)
    _SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_USERNAME') or ''
    VAPID_SUBJECT = os.environ.get('VAPID_SUBJECT') or (
        f"https://{_HOST.split(':')[0]}" if _SCHEME == 'https' and not _HOST.startswith('localhost')
        else f'mailto:{_SENDER}' if '@' in _SENDER
        else 'https://github.com')


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
