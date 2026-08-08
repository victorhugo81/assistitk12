"""
Authentication tests: login, logout, lockout, must-change-password redirect.
"""
import pytest
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_login_page_loads(self, client):
        r = client.get('/login')
        assert r.status_code == 200
        assert b'login' in r.data.lower()

    def test_login_success_redirects_to_index(self, client):
        r = client.post('/login', data={
            'email': 'admin@test.com',
            'password': 'Admin@Password1',
        }, follow_redirects=False)
        assert r.status_code == 302
        assert '/' in r.headers['Location']

    def test_login_wrong_password_stays_on_login(self, client):
        r = client.post('/login', data={
            'email': 'admin@test.com',
            'password': 'wrongpassword',
        }, follow_redirects=True)
        assert r.status_code == 200
        assert b'Login failed' in r.data or b'credentials' in r.data.lower()

    def test_login_unknown_email(self, client):
        r = client.post('/login', data={
            'email': 'nobody@test.com',
            'password': 'Admin@Password1',
        }, follow_redirects=True)
        assert r.status_code == 200
        assert b'Login failed' in r.data or b'credentials' in r.data.lower()

    def test_login_inactive_user(self, app, client):
        with app.app_context():
            from application.models import User
            from application.utils import hash_email
            from main import db
            key = app.config['SECRET_KEY']
            u = User.query.filter_by(email_hash=hash_email('admin@test.com', key)).first()
            original_status = u.status
            u.status = 'Inactive'
            db.session.commit()

        r = client.post('/login', data={
            'email': 'admin@test.com',
            'password': 'Admin@Password1',
        }, follow_redirects=True)
        # Login responses use one generic message regardless of the reason
        # (wrong password, inactive, locked) so they can't be used to
        # enumerate account state — see security audit finding L1.
        assert b'login failed' in r.data.lower()
        assert b'inactive' not in r.data.lower()
        # ...and no session was actually established
        protected = client.get('/', follow_redirects=False)
        assert protected.status_code == 302

        # Restore status
        with app.app_context():
            from application.models import User
            from application.utils import hash_email
            from main import db
            key = app.config['SECRET_KEY']
            u = User.query.filter_by(email_hash=hash_email('admin@test.com', key)).first()
            u.status = 'Active'
            db.session.commit()

    def test_account_lockout_after_five_failures(self, app, client):
        """Five wrong passwords in a row should lock the account."""
        for _ in range(5):
            client.post('/login', data={
                'email': 'user@test.com',
                'password': 'BadPassword99!',
            })

        r = client.post('/login', data={
            'email': 'user@test.com',
            'password': 'Regular@Password1',
        }, follow_redirects=True)
        # A generic message is shown even though the account is actually
        # locked (see security audit finding L1) — verify the lockout itself
        # via the database instead of a leaky, lockout-specific message.
        assert b'login failed' in r.data.lower()
        protected = client.get('/', follow_redirects=False)
        assert protected.status_code == 302

        with app.app_context():
            from application.models import User
            from application.utils import hash_email
            from main import db
            key = app.config['SECRET_KEY']
            u = User.query.filter_by(email_hash=hash_email('user@test.com', key)).first()
            assert u.locked_until is not None
            assert u.locked_until > datetime.now(timezone.utc).replace(tzinfo=None)

            # Unlock for other tests
            u.failed_login_attempts = 0
            u.locked_until = None
            db.session.commit()


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_logout_redirects_to_login(self, admin_client):
        r = admin_client.get('/logout', follow_redirects=False)
        assert r.status_code in (301, 302)

    def test_logout_unauthenticated_redirects(self, client):
        r = client.get('/logout', follow_redirects=False)
        assert r.status_code in (301, 302)


# ---------------------------------------------------------------------------
# Must-change-password enforcement
# ---------------------------------------------------------------------------

class TestMustChangePassword:
    def test_must_change_password_redirect(self, app, client):
        """A user with must_change_password=True should be redirected to set-password."""
        with app.app_context():
            from application.models import User
            from application.utils import hash_email
            from main import db
            key = app.config['SECRET_KEY']
            u = User.query.filter_by(email_hash=hash_email('user@test.com', key)).first()
            u.must_change_password = True
            db.session.commit()
            user_id = u.id

        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess['_user_id'] = str(user_id)
                sess['_fresh'] = True
            r = c.get('/', follow_redirects=False)
            assert r.status_code == 302
            assert 'set-password' in r.headers['Location']

        # Restore
        with app.app_context():
            from application.models import User
            from main import db
            u = db.session.get(User, user_id)
            u.must_change_password = False
            db.session.commit()

    def test_set_password_page_loads(self, app, client):
        with app.app_context():
            from application.models import User
            from application.utils import hash_email
            from main import db
            key = app.config['SECRET_KEY']
            u = User.query.filter_by(email_hash=hash_email('user@test.com', key)).first()
            u.must_change_password = True
            db.session.commit()
            user_id = u.id

        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess['_user_id'] = str(user_id)
                sess['_fresh'] = True
            r = c.get('/set-password')
            assert r.status_code == 200

        with app.app_context():
            from application.models import User
            from main import db
            u = db.session.get(User, user_id)
            u.must_change_password = False
            db.session.commit()
