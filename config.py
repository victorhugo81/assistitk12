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

    def __init__(self):
        if self.SECRET_KEY == 'dev-secret-key':
            raise RuntimeError(
                "SECRET_KEY must be set to a strong random value in production. "
                "Set the SECRET_KEY environment variable."
            )

# Dictionary to manage different configurations for different environments
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig  # Set a default configuration
}

