from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'routes.login'

def create_app(config_class='config.Config'):
    app = Flask(__name__, template_folder='templates')
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        from . import routes, models  # Import routes and models here
        db.create_all()

    # Register Blueprints
    app.register_blueprint(routes.routes_blueprint)

    return app

