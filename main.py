import os
from flask import Flask
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from config import config

# Initialize global extensions
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
mail = Mail()


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
    login_manager.login_view = "routes.login"

    migrate = Migrate(app, db)

    # Register blueprint
    from application.routes import routes_blueprint
    app.register_blueprint(routes_blueprint)
    return app

if __name__ == "__main__":
    # Get environment from environment variable or use default
    env = os.environ.get('FLASK_ENV', 'development')
    app = create_app(env)

    # Print all available endpoints for debugging
    with app.app_context():
        print([rule.endpoint for rule in app.url_map.iter_rules()])

    app.run(debug=False)

