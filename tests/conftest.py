"""
Pytest fixtures for the AssistITK12 test suite.

Uses a SQLite in-memory database so tests never touch the real database.
CSRF and rate-limiting are disabled for test simplicity.
"""
import pytest
from werkzeug.security import generate_password_hash

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def app():
    """Create application configured for testing (session-scoped — one DB per run)."""
    import sys, os
    # Make sure the project root is on sys.path so 'main' can be imported
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    from config import Config

    class TestingConfig(Config):
        TESTING = True
        DEBUG = False
        SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
        WTF_CSRF_ENABLED = False
        RATELIMIT_ENABLED = False
        SECRET_KEY = 'test-secret-key-for-pytest'
        SCHEDULER_API_ENABLED = False
        # Disable APScheduler from actually starting background threads
        SCHEDULER_EXECUTORS = {'default': {'type': 'threadpool', 'max_workers': 1}}
        MAIL_SUPPRESS_SEND = True

    from config import config as config_map
    config_map['testing'] = TestingConfig

    from main import create_app, db as _db
    _app = create_app('testing')

    with _app.app_context():
        _db.create_all()
        _seed_base_data(_db, _app)

    yield _app


def _seed_base_data(db, app):
    """Insert the minimum rows needed for most tests to pass."""
    from application.models import Role, Site, Organization, User
    from application.utils import encrypt_mail_password, hash_email

    key = app.config['SECRET_KEY']

    # Roles — id 1 = Admin, 2 = Specialist, 3 = Technician, 4 = Teacher
    roles = [
        Role(id=1, role_name='Admin'),
        Role(id=2, role_name='Specialist'),
        Role(id=3, role_name='Technician'),
        Role(id=4, role_name='Teacher'),
    ]
    db.session.bulk_save_objects(roles)

    # One site
    site = Site(
        id=1,
        site_name='Main School',
        site_acronyms='MS',
        site_code='001',
        site_cds='00-000-0000000',
        site_address='123 Main St',
        site_type='Elementary',
    )
    db.session.add(site)

    # Organization (required by login page, settings, etc.)
    org = Organization(
        id=1,
        organization_name='Test District',
        site_version='1.0',
    )
    db.session.add(org)

    db.session.flush()  # so FKs resolve

    # Admin user
    admin = User(
        first_name='Admin',
        last_name='User',
        status='Active',
        password=generate_password_hash('Admin@Password1'),
        must_change_password=False,
        failed_login_attempts=0,
        role_id=1,
        site_id=1,
    )
    admin.email = 'admin@test.com'
    db.session.add(admin)

    # Regular (teacher) user
    regular = User(
        first_name='Regular',
        last_name='User',
        status='Active',
        password=generate_password_hash('Regular@Password1'),
        must_change_password=False,
        failed_login_attempts=0,
        role_id=4,
        site_id=1,
    )
    regular.email = 'user@test.com'
    db.session.add(regular)

    db.session.commit()


# ---------------------------------------------------------------------------
# Client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(app):
    """Unauthenticated test client."""
    return app.test_client()


@pytest.fixture()
def admin_client(app):
    """Test client pre-logged-in as the Admin user."""
    with app.test_client() as c:
        with app.app_context():
            from application.models import User
            from application.utils import hash_email
            key = app.config['SECRET_KEY']
            user = User.query.filter_by(email_hash=hash_email('admin@test.com', key)).first()
            with c.session_transaction() as sess:
                sess['_user_id'] = str(user.id)
                sess['_fresh'] = True
        yield c


@pytest.fixture()
def user_client(app):
    """Test client pre-logged-in as the regular (teacher) user."""
    with app.test_client() as c:
        with app.app_context():
            from application.models import User
            from application.utils import hash_email
            key = app.config['SECRET_KEY']
            user = User.query.filter_by(email_hash=hash_email('user@test.com', key)).first()
            with c.session_transaction() as sess:
                sess['_user_id'] = str(user.id)
                sess['_fresh'] = True
        yield c
