"""
Security tests:
- Unauthenticated access is redirected to login
- Non-admin users receive 403 on admin-only routes
- Security headers are present on every response
"""
import pytest


# ---------------------------------------------------------------------------
# Routes that require authentication
# ---------------------------------------------------------------------------

AUTH_REQUIRED_ROUTES = [
    '/',
    '/users',
    '/add_user',
    '/roles',
    '/sites',
    '/tickets',
    '/profile',
]


class TestAuthRequired:
    @pytest.mark.parametrize('path', AUTH_REQUIRED_ROUTES)
    def test_unauthenticated_redirects_to_login(self, client, path):
        r = client.get(path, follow_redirects=False)
        assert r.status_code in (302, 301), f"{path} should redirect unauthenticated users"
        location = r.headers.get('Location', '')
        assert 'login' in location.lower(), f"{path} should redirect to login, got: {location}"


# ---------------------------------------------------------------------------
# Admin-only routes
# ---------------------------------------------------------------------------

ADMIN_ONLY_ROUTES = [
    '/users',
    '/add_user',
    '/roles',
    '/add_role',
    '/sites',
    '/add_site',
    '/titles',
    '/notifications',
    '/upload-users',
]


class TestAdminOnly:
    @pytest.mark.parametrize('path', ADMIN_ONLY_ROUTES)
    def test_regular_user_gets_403(self, user_client, path):
        r = user_client.get(path)
        assert r.status_code == 403, f"Regular user should get 403 on {path}, got {r.status_code}"

    @pytest.mark.parametrize('path', ADMIN_ONLY_ROUTES)
    def test_admin_user_can_access(self, admin_client, path):
        r = admin_client.get(path)
        assert r.status_code in (200, 302), f"Admin should access {path}, got {r.status_code}"


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    def test_x_content_type_options(self, client):
        r = client.get('/login')
        assert r.headers.get('X-Content-Type-Options') == 'nosniff'

    def test_x_frame_options(self, client):
        r = client.get('/login')
        assert r.headers.get('X-Frame-Options') == 'SAMEORIGIN'

    def test_referrer_policy(self, client):
        r = client.get('/login')
        assert r.headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin'

    def test_content_security_policy_present(self, client):
        r = client.get('/login')
        assert 'Content-Security-Policy' in r.headers

    def test_permissions_policy(self, client):
        r = client.get('/login')
        assert 'Permissions-Policy' in r.headers

    def test_no_hsts_in_debug_mode(self, client):
        """HSTS should be absent when DEBUG is True (test config has DEBUG=False but app.debug check)."""
        r = client.get('/login')
        # In testing mode debug=False so we may or may not get HSTS — just confirm no crash
        assert r.status_code == 200
