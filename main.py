import os
from flask import Flask
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import config

# Initialize global extensions
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
mail = Mail()
limiter = Limiter(key_func=get_remote_address)


@login_manager.user_loader
def load_user(user_id):
    from application.models import User
    return User.query.get(int(user_id))

def create_app(config_name='default'):
    app = Flask(
        __name__,
        template_folder='application/templates',
        static_folder='application/static'
    )

    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'application/static/uploads')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.config['UPLOAD_ATTACHMENT'] = os.path.join(app.root_path, 'application/static/uploads/attachments')
    os.makedirs(app.config['UPLOAD_ATTACHMENT'], exist_ok=True)

    # Use environment-specific configuration
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)
    login_manager.login_view = "routes.login"

    migrate = Migrate(app, db)

    # Register blueprint
    from application.routes import routes_blueprint
    app.register_blueprint(routes_blueprint)

    # Override Flask-Mail config with any settings stored in the database.
    # This ensures ticket notifications use the admin-configured SMTP settings
    # on every startup, not just after the settings form is saved.
    with app.app_context():
        try:
            from application.models import Organization
            from application.utils import decrypt_mail_password
            org = Organization.query.get(1)
            if org and org.mail_server:
                app.config['MAIL_SERVER'] = org.mail_server
                if org.mail_port:
                    app.config['MAIL_PORT'] = org.mail_port
                app.config['MAIL_USE_TLS'] = bool(org.mail_use_tls)
                app.config['MAIL_USE_SSL'] = bool(org.mail_use_ssl)
                app.config['MAIL_USERNAME'] = org.mail_username
                app.config['MAIL_PASSWORD'] = decrypt_mail_password(
                    org.mail_password or '', app.config['SECRET_KEY']
                )
                app.config['MAIL_DEFAULT_SENDER'] = org.mail_default_sender
                mail.init_app(app)
        except Exception:
            pass  # DB not ready on first run — env var defaults remain active

    return app

if __name__ == "__main__":
    # Get environment from environment variable or use default
    env = os.environ.get('FLASK_ENV', 'development')
    app = create_app(env)

    # Print all available endpoints for debugging
    with app.app_context():
        print([rule.endpoint for rule in app.url_map.iter_rules()])

    app.run(debug=False)

