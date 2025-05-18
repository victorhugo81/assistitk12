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


class DevelopmentConfig(Config):
    DEBUG = True  # Enable debug mode for development

class ProductionConfig(Config):
    DEBUG = False  # Disable debug mode for production
    # In production, ensure SECRET_KEY is set in environment variables
    # No fallback should be used in production for sensitive settings

# Dictionary to manage different configurations for different environments
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig  # Set a default configuration
}

