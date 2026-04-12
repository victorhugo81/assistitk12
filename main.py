import os
from flask import Flask
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_apscheduler import APScheduler
from werkzeug.middleware.proxy_fix import ProxyFix
from config import config

# Initialize global extensions
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
mail = Mail()
limiter = Limiter(key_func=get_remote_address)
scheduler = APScheduler()


@login_manager.user_loader
def load_user(user_id):
    from application.models import User
    return db.session.get(User, int(user_id))

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

    # Production startup guards — catch misconfiguration before the app serves traffic
    if config_name == 'production':
        if app.config.get('SECRET_KEY') == 'dev-secret-key':
            raise RuntimeError(
                "SECRET_KEY must be set to a strong random value in production. "
                "Set the SECRET_KEY environment variable."
            )
        if app.config.get('RATELIMIT_STORAGE_URI', 'memory://') == 'memory://':
            raise RuntimeError(
                "RATELIMIT_STORAGE_URI must be set to a persistent backend "
                "(e.g. redis://localhost:6379/0) in production. "
                "In-memory storage resets on every restart, making rate limits ineffective."
            )

    # Trust one layer of reverse-proxy headers (Nginx/Apache sets X-Forwarded-For)
    # so rate limiting sees the real client IP instead of the proxy's IP.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)
    scheduler.init_app(app)
    login_manager.login_view = "routes.login"

    # Warn if rate-limit storage is in-memory (ineffective across restarts)
    if app.config.get('RATELIMIT_STORAGE_URI', 'memory://') == 'memory://':
        import warnings
        warnings.warn(
            "Rate limiter is using in-memory storage. Counters reset on every restart. "
            "Set RATELIMIT_STORAGE_URI=redis://... for persistent rate limiting.",
            RuntimeWarning,
            stacklevel=2,
        )

    migrate = Migrate(app, db)

    # Jinja filter: convert UTC datetime to local system time
    from datetime import timezone as _tz
    def localtime(dt, fmt='%m-%d-%Y %H:%M'):
        if dt is None:
            return ''
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_tz.utc)
        return dt.astimezone().strftime(fmt)
    app.jinja_env.filters['localtime'] = localtime

    # Register blueprint
    from application.routes import routes_blueprint
    app.register_blueprint(routes_blueprint)

    # Security headers applied to every response
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'self';"
        )
        # HSTS: only send over HTTPS — skip in debug mode to avoid breaking HTTP dev
        if not app.debug:
            response.headers['Strict-Transport-Security'] = (
                'max-age=31536000; includeSubDomains'
            )
        return response

    # Override Flask-Mail config with any settings stored in the database.
    # This ensures ticket notifications use the admin-configured SMTP settings
    # on every startup, not just after the settings form is saved.
    with app.app_context():
        try:
            from application.models import Organization
            from application.utils import decrypt_mail_password
            org = db.session.get(Organization, 1)
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

    # Register FTP schedule from Organization if enabled
    with app.app_context():
        _register_org_ftp_schedule()

    if not scheduler.running:
        scheduler.start()

    return app


def _register_org_ftp_schedule():
    """Register (or remove) the single org-level FTP cron job based on Organization settings."""
    try:
        from application.models import Organization
        from application.scheduled_jobs import run_org_ftp_schedule
        org = db.session.get(Organization, 1)
        if org and org.ftp_schedule_enabled and org.ftp_schedule_hour is not None:
            scheduler.add_job(
                id='org_ftp_schedule',
                func=run_org_ftp_schedule,
                trigger='cron',
                day_of_week=org.ftp_schedule_days or '*',
                hour=org.ftp_schedule_hour,
                minute=org.ftp_schedule_minute or 0,
                replace_existing=True
            )
        else:
            try:
                scheduler.remove_job('org_ftp_schedule')
            except Exception:
                pass
    except Exception:
        pass  # DB not ready on first run

if __name__ == "__main__":
    # Get environment from environment variable or use default
    env = os.environ.get('FLASK_ENV', 'development')
    app = create_app(env)

    app.run(debug=app.debug)

