import os
from datetime import timedelta

class Config:
    """Base configuration"""
    # Secrets come from the environment (.env next to docker-compose.yml);
    # nothing sensitive is hard-coded here.
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'christmas-secret-key-change-in-production'

    # Server name for URL generation in emails
    SERVER_NAME_FOR_EMAILS = os.environ.get('SERVER_NAME_FOR_EMAILS') or 'wishlist.example.com'
    PREFERRED_URL_SCHEME = os.environ.get('PREFERRED_URL_SCHEME') or 'https'

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'postgresql://christmas:christmas@db:5432/christmas_app'
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
    ASSIGNMENTS_FILE_PATH = os.environ.get('ASSIGNMENTS_FILE_PATH') or '/app/data/assignments'

    # File upload configuration
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or '/app/data/uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

    # Gemini AI API Key for photo transformation and gift poems
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    # Model names - override in .env when Google retires a model
    GEMINI_IMAGE_MODEL = os.environ.get('GEMINI_IMAGE_MODEL') or 'gemini-3-pro-image'
    GEMINI_IMAGE_FALLBACK_MODEL = os.environ.get('GEMINI_IMAGE_FALLBACK_MODEL') or 'gemini-3.1-flash-image'
    GEMINI_TEXT_MODEL = os.environ.get('GEMINI_TEXT_MODEL') or 'gemini-3.6-flash'

    # The backup service's folder, mounted read-only so Admin -> Settings can show backup status
    BACKUP_STATUS_DIR = os.environ.get('BACKUP_STATUS_DIR') or '/app/backups'

    # Push notifications. The key pair is generated and stored in the database
    # automatically; set VAPID_PRIVATE_KEY only to supply your own.
    VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')
    # Contact address push services may use (an https:// URL or mailto:)
    VAPID_SUBJECT = os.environ.get('VAPID_SUBJECT') or \
        f"https://{os.environ.get('SERVER_NAME_FOR_EMAILS') or 'wishlist.example.com'}"


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
