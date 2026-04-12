"""
User management tests: list, add, edit, email encryption, profile.
"""
import pytest


class TestUserList:
    def test_users_page_loads(self, admin_client):
        r = admin_client.get('/users')
        assert r.status_code == 200
        assert b'user' in r.data.lower()

    def test_users_search_by_name(self, admin_client):
        r = admin_client.get('/users?search=Admin')
        assert r.status_code == 200


class TestAddUser:
    def test_add_user_form_loads(self, admin_client):
        r = admin_client.get('/add_user')
        assert r.status_code == 200

    def test_add_user_creates_record(self, app, admin_client):
        r = admin_client.post('/add_user', data={
            'first_name': 'New',
            'last_name': 'Teacher',
            'email': 'newteacher@test.com',
            'role_id': '4',
            'site_id': '1',
            'status': 'Active',
            'password': 'Temp@Password1',
        }, follow_redirects=True)
        assert r.status_code == 200

        with app.app_context():
            from application.models import User
            from application.utils import hash_email
            key = app.config['SECRET_KEY']
            u = User.query.filter_by(email_hash=hash_email('newteacher@test.com', key)).first()
            assert u is not None
            assert u.first_name == 'New'

    def test_add_user_duplicate_email_rejected(self, admin_client):
        r = admin_client.post('/add_user', data={
            'first_name': 'Dupe',
            'last_name': 'User',
            'email': 'admin@test.com',   # already exists
            'role_id': '4',
            'site_id': '1',
            'status': 'Active',
            'password': 'Temp@Password1',
        }, follow_redirects=True)
        assert r.status_code == 200
        # Should show an error flash, not create another record
        assert b'already' in r.data.lower() or b'exists' in r.data.lower() or b'error' in r.data.lower() or b'duplicate' in r.data.lower()

    def test_add_user_missing_required_fields(self, admin_client):
        r = admin_client.post('/add_user', data={
            'first_name': '',
            'last_name': '',
            'email': '',
            'role_id': '',
            'site_id': '',
            'status': 'Active',
            'password': '',
        }, follow_redirects=True)
        assert r.status_code == 200


class TestEditUser:
    def _get_admin_id(self, app):
        with app.app_context():
            from application.models import User
            from application.utils import hash_email
            key = app.config['SECRET_KEY']
            u = User.query.filter_by(email_hash=hash_email('admin@test.com', key)).first()
            return u.id

    def test_edit_user_form_loads(self, app, admin_client):
        uid = self._get_admin_id(app)
        r = admin_client.get(f'/edit_user/{uid}')
        assert r.status_code == 200

    def test_edit_user_updates_name(self, app, admin_client):
        uid = self._get_admin_id(app)
        r = admin_client.post(f'/edit_user/{uid}', data={
            'first_name': 'UpdatedAdmin',
            'last_name': 'User',
            'email': 'admin@test.com',
            'role_id': '1',
            'site_id': '1',
            'status': 'Active',
            'password': '',
        }, follow_redirects=True)
        assert r.status_code == 200

        with app.app_context():
            from application.models import User
            u = User.query.get(uid)
            assert u.first_name == 'UpdatedAdmin'

        # Restore
        with app.app_context():
            from main import db
            from application.models import User
            u = User.query.get(uid)
            u.first_name = 'Admin'
            db.session.commit()


class TestEmailEncryption:
    def test_email_stored_encrypted(self, app):
        """The email column should be gone; email_enc must not contain plaintext."""
        with app.app_context():
            from application.models import User
            from application.utils import hash_email
            key = app.config['SECRET_KEY']
            user = User.query.filter_by(email_hash=hash_email('admin@test.com', key)).first()
            assert user is not None
            # email_enc should not literally be the plaintext email
            assert 'admin@test.com' not in (user.email_enc or '')
            # But the property should decrypt correctly
            assert user.email == 'admin@test.com'

    def test_email_hash_length(self, app):
        with app.app_context():
            from application.models import User
            from application.utils import hash_email
            key = app.config['SECRET_KEY']
            user = User.query.filter_by(email_hash=hash_email('admin@test.com', key)).first()
            assert len(user.email_hash) == 64

    def test_email_setter_updates_both_columns(self, app):
        with app.app_context():
            from application.models import User
            from application.utils import hash_email
            from main import db
            key = app.config['SECRET_KEY']
            user = User.query.filter_by(email_hash=hash_email('admin@test.com', key)).first()
            # Set same email again — enc token will differ (Fernet is nondeterministic)
            user.email = 'admin@test.com'
            db.session.commit()
            assert user.email_hash == hash_email('admin@test.com', key)
            assert user.email == 'admin@test.com'


class TestProfile:
    def test_profile_page_loads(self, admin_client):
        r = admin_client.get('/profile')
        assert r.status_code == 200

    def test_profile_shows_user_info(self, admin_client):
        r = admin_client.get('/profile')
        assert b'Admin' in r.data

    def test_profile_forbidden_unauthenticated(self, client):
        r = client.get('/profile', follow_redirects=False)
        assert r.status_code in (301, 302)
