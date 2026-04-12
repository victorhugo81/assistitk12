import os
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

class Config:
    # Flask secret key for session management and CSRF protection
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')  # Fallback for development
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Database connection string, with a fallback for development
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///app.db')

    # Flask-Limiter storage: set RATELIMIT_STORAGE_URI=redis://... in production
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')

    # Session cookie security
    SESSION_COOKIE_HTTPONLY = True   # Prevent JavaScript access to session cookie
    SESSION_COOKIE_SAMESITE = 'Lax' # Block cross-site request sending of cookie

    # APScheduler — disable the built-in REST API endpoint
    SCHEDULER_API_ENABLED = False

    # Flask-Mail configuration
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 465))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')


class DevelopmentConfig(Config):
    DEBUG = True  # Enable debug mode for development

class ProductionConfig(Config):
    DEBUG = False  # Disable debug mode for production

    # Secure session cookies in production
    SESSION_COOKIE_SECURE = True      # Only sent over HTTPS
    SESSION_COOKIE_HTTPONLY = True    # Inaccessible to JavaScript
    SESSION_COOKIE_SAMESITE = 'Lax'  # CSRF mitigation

    def __init__(self):
        if self.SECRET_KEY == 'dev-secret-key':
            raise RuntimeError(
                "SECRET_KEY must be set to a strong random value in production. "
                "Set the SECRET_KEY environment variable."
            )
        if self.RATELIMIT_STORAGE_URI == 'memory://':
            raise RuntimeError(
                "RATELIMIT_STORAGE_URI must be set to a persistent backend (e.g. "
                "redis://localhost:6379/0) in production. In-memory storage resets "
                "on every restart, making rate limits ineffective."
            )

# Dictionary to manage different configurations for different environments
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig  # Set a default configuration
}

