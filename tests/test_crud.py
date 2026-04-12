"""
CRUD tests for Roles, Sites, Titles, and Notifications.
All actions require admin access.
"""
import pytest


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class TestRoles:
    def test_roles_page_loads(self, admin_client):
        r = admin_client.get('/roles')
        assert r.status_code == 200

    def test_add_role(self, app, admin_client):
        r = admin_client.post('/add_role', data={
            'role_name': 'TestRole',
        }, follow_redirects=True)
        assert r.status_code == 200

        with app.app_context():
            from application.models import Role
            role = Role.query.filter_by(role_name='TestRole').first()
            assert role is not None

    def test_add_role_form_loads(self, admin_client):
        r = admin_client.get('/add_role')
        assert r.status_code == 200

    def test_edit_role(self, app, admin_client):
        """Roles with ID > 5 can be edited; the seeded roles (1-5) are protected."""
        with app.app_context():
            from application.models import Role
            from main import db
            # Create a role with an id well above 5 for editing
            r = Role(role_name='EditableRole')
            db.session.add(r)
            db.session.commit()
            role_id = r.id

        resp = admin_client.post(f'/edit_role/{role_id}', data={
            'role_name': 'EditableRoleUpdated',
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            from application.models import Role
            from main import db
            role = db.session.get(Role, role_id)
            assert role.role_name == 'EditableRoleUpdated'

    def test_delete_role(self, app, admin_client):
        """Roles with ID > 5 can be deleted."""
        with app.app_context():
            from application.models import Role
            from main import db
            r = Role(role_name='DeletableRole')
            db.session.add(r)
            db.session.commit()
            role_id = r.id

        resp = admin_client.post(f'/delete_role/{role_id}', follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            from application.models import Role
            from main import db
            assert db.session.get(Role, role_id) is None

    def test_regular_user_cannot_add_role(self, user_client):
        r = user_client.post('/add_role', data={'role_name': 'HackerRole'})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------

class TestSites:
    def test_sites_page_loads(self, admin_client):
        r = admin_client.get('/sites')
        assert r.status_code == 200

    def test_add_site(self, app, admin_client):
        r = admin_client.post('/add_site', data={
            'site_name': 'Test School',
            'site_acronyms': 'TS',
            'site_code': 'TSC001',
            'site_cds': '00-001-0000001',
            'site_address': '456 Test Ave',
            'site_type': 'Middle',
        }, follow_redirects=True)
        assert r.status_code == 200

        with app.app_context():
            from application.models import Site
            site = Site.query.filter_by(site_name='Test School').first()
            assert site is not None

    def test_edit_site(self, app, admin_client):
        with app.app_context():
            from application.models import Site
            site = Site.query.filter_by(site_name='Test School').first()
            if site is None:
                pytest.skip('Test School not found')
            site_id = site.id

        r = admin_client.post(f'/edit_site/{site_id}', data={
            'site_name': 'Test School Edited',
            'site_acronyms': 'TSE',
            'site_code': 'TSC001',
            'site_cds': '00-001-0000001',
            'site_address': '456 Test Ave',
            'site_type': 'Middle',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_delete_site(self, app, admin_client):
        with app.app_context():
            from application.models import Site
            site = Site.query.filter_by(site_name='Test School Edited').first()
            if site is None:
                pytest.skip('Test School Edited not found')
            site_id = site.id

        r = admin_client.post(f'/delete_site/{site_id}', follow_redirects=True)
        assert r.status_code == 200

    def test_regular_user_cannot_add_site(self, user_client):
        r = user_client.get('/add_site')
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Titles
# ---------------------------------------------------------------------------

class TestTitles:
    def test_titles_page_loads(self, admin_client):
        r = admin_client.get('/titles')
        assert r.status_code == 200

    def test_add_title(self, app, admin_client):
        r = admin_client.post('/add_title', data={
            'title_name': 'Test Title',
        }, follow_redirects=True)
        assert r.status_code == 200

        with app.app_context():
            from application.models import Title
            title = Title.query.filter_by(title_name='Test Title').first()
            assert title is not None

    def test_delete_title(self, app, admin_client):
        with app.app_context():
            from application.models import Title
            title = Title.query.filter_by(title_name='Test Title').first()
            if title is None:
                pytest.skip('Test Title not found')
            title_id = title.id

        r = admin_client.post(f'/delete_title/{title_id}', follow_redirects=True)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class TestNotifications:
    def test_notifications_page_loads(self, admin_client):
        r = admin_client.get('/notifications')
        assert r.status_code == 200

    def test_add_notification(self, app, admin_client):
        r = admin_client.post('/add_notification', data={
            'msg_name': 'Test Notice',
            'msg_content': 'This is a test notification message.',
            'msg_status': 'active',
        }, follow_redirects=True)
        assert r.status_code == 200

        with app.app_context():
            from application.models import Notification
            n = Notification.query.filter_by(msg_name='Test Notice').first()
            assert n is not None

    def test_edit_notification(self, app, admin_client):
        with app.app_context():
            from application.models import Notification
            n = Notification.query.filter_by(msg_name='Test Notice').first()
            if n is None:
                pytest.skip('Test Notice not found')
            n_id = n.id

        r = admin_client.post(f'/edit_notification/{n_id}', data={
            'msg_name': 'Test Notice',
            'msg_content': 'Updated content.',
            'msg_status': 'inactive',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_delete_notification(self, app, admin_client):
        with app.app_context():
            from application.models import Notification
            n = Notification.query.filter_by(msg_name='Test Notice').first()
            if n is None:
                pytest.skip('Test Notice not found')
            n_id = n.id

        r = admin_client.post(f'/delete_notification/{n_id}', follow_redirects=True)
        assert r.status_code == 200

    def test_regular_user_cannot_access_notifications(self, user_client):
        r = user_client.get('/notifications')
        assert r.status_code == 403
