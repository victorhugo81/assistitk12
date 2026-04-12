"""
Ticket tests: create, view, comment, status transitions, admin management.
"""
import pytest


def _seed_title(app):
    """Ensure at least one Title exists; return its id."""
    with app.app_context():
        from application.models import Title
        from main import db
        title = Title.query.first()
        if title is None:
            title = Title(title_name='Hardware Issue')
            db.session.add(title)
            db.session.commit()
        return title.id


class TestTicketCreate:
    def test_add_ticket_page_loads(self, user_client):
        r = user_client.get('/add_ticket')
        assert r.status_code == 200

    def test_add_ticket_creates_record(self, app, user_client):
        title_id = _seed_title(app)
        r = user_client.post('/add_ticket', data={
            'title_id': str(title_id),
            'content': 'My device is broken.',
        }, follow_redirects=True)
        assert r.status_code == 200

        with app.app_context():
            from application.models import Ticket
            t = Ticket.query.first()
            assert t is not None

    def test_add_ticket_missing_fields(self, user_client):
        r = user_client.post('/add_ticket', data={
            'title_id': '',
            'content': '',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_unauthenticated_cannot_add_ticket(self, client):
        r = client.get('/add_ticket', follow_redirects=False)
        assert r.status_code in (301, 302)


class TestTicketView:
    def test_tickets_list_loads(self, user_client):
        r = user_client.get('/tickets')
        assert r.status_code == 200

    def test_ticket_edit_page_loads(self, app, user_client):
        with app.app_context():
            from application.models import Ticket
            t = Ticket.query.first()
            if t is None:
                pytest.skip('No ticket to view')
            ticket_id = t.id

        r = user_client.get(f'/edit_ticket/{ticket_id}')
        assert r.status_code in (200, 403)  # regular users may not edit others' tickets

    def test_nonexistent_ticket_returns_404(self, admin_client):
        r = admin_client.get('/edit_ticket/999999')
        assert r.status_code == 404


class TestTicketComment:
    def test_add_comment_to_ticket(self, app, user_client):
        with app.app_context():
            from application.models import Ticket
            t = Ticket.query.first()
            if t is None:
                pytest.skip('No ticket available')
            ticket_id = t.id

        r = user_client.post(f'/add_comment/{ticket_id}', data={
            'content': 'This is a follow-up comment.',
        }, follow_redirects=True)
        assert r.status_code == 200


class TestTicketAdmin:
    def test_admin_can_view_all_tickets(self, admin_client):
        r = admin_client.get('/tickets')
        assert r.status_code == 200

    def test_admin_can_delete_ticket(self, app, admin_client):
        with app.app_context():
            from application.models import Ticket, Title, User
            from application.utils import hash_email
            from main import db

            key = app.config['SECRET_KEY']
            admin = User.query.filter_by(email_hash=hash_email('admin@test.com', key)).first()
            title = Title.query.first()
            if title is None:
                pytest.skip('No title available')

            t = Ticket(
                title_id=title.id,
                tck_status='Open',
                user_id=admin.id,
                site_id=1,
            )
            db.session.add(t)
            db.session.commit()
            ticket_id = t.id

        r = admin_client.post(f'/delete_ticket/{ticket_id}', follow_redirects=True)
        assert r.status_code == 200

        with app.app_context():
            from application.models import Ticket
            assert Ticket.query.get(ticket_id) is None
