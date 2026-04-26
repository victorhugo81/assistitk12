# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.1] - 2026-04-26

### Changed
- UI redesign: migrated stylesheet to a CSS custom-property design system (color palette, shadow scale, border-radius scale, spacing scale, transition tokens).
- Switched body font to Inter via Google Fonts for a modern, neutral appearance.
- Login page: increased "Sign In" heading size and weight; adjusted login panel layout to `flex-direction: column` with `align-items: stretch` for better vertical alignment.

## [1.1.0] - 2026-04-12

### Added
- Production startup guards that raise `RuntimeError` on launch if `SECRET_KEY` or `RATELIMIT_STORAGE_URI` are misconfigured, preventing silent security issues.
- `ProxyFix` WSGI middleware so rate limiting and logging see the real client IP when the app runs behind Nginx or Apache.
- `_is_mail_configured()` guard in email utilities — all outbound email functions now silently skip sending if no SMTP credentials are saved in the database, preventing startup errors on fresh installs.
- `SQLALCHEMY_POOL_RECYCLE = 3600` to recycle MySQL connections before the server-side idle timeout (~8 h).
- `MAX_CONTENT_LENGTH = 16 MB` cap on request bodies to prevent denial-of-service via large file uploads.
- `PERMANENT_SESSION_LIFETIME = 8 hours` so sessions expire after inactivity.
- `testing` config entry in the config dictionary for use by the test suite.

### Changed
- Bulk data upload route renamed from `/upload-users` to `/bulk-data-upload` and page title updated to "Bulk Data Upload".
- Bulk upload log view simplified to a single unified log (previously split into user and site logs).
- All `Model.query.get()` calls replaced with `db.session.get()` (SQLAlchemy 2.0 style) throughout `main.py`.
- All `datetime.utcnow` references in models replaced with a timezone-aware `_utcnow()` helper to resolve deprecation warnings.
- FTP error handling: fixed variable shadowing bug in `error_perm` handler where `msg_lower` was assigned but the original `str(e)` was searched instead.
- Removed redundant `page_names` dict in `edit_ticket` — page name is now set directly.
- Production config guards moved from `ProductionConfig.__init__` into `create_app()` so they apply at runtime, not at import time.

### Fixed
- Suppressed Flask-Login's default "Please log in to access this page." flash message on login redirects by setting `login_manager.login_message = ""`.

### Dependencies
- Updated: `click` 8.3.1 → 8.3.2, `cryptography` 46.0.5 → 46.0.7, `flask` 3.1.2 → 3.1.3, `greenlet` 3.3.1 → 3.4.0, `python-dotenv` 1.2.1 → 1.2.2, `sqlalchemy` 2.0.46 → 2.0.49, `tzdata` 2025.3 → 2026.1, `werkzeug` 3.1.5 → 3.1.8, `wrapt` 2.1.1 → 2.1.2.

## [1.0.0] - 2025-05-18

### Added
- First production release.
- User authentication with login/logout and temporary password flow.
- Models for users, roles, sites, tickets, notifications, and organizations.
- CRUD routes and forms for all models.
- Role-based access control (Admin, Specialist, Technician).
- Account lockout after repeated failed login attempts.
- Ticket system with attachments, comments, escalation, and email notifications.
- Bulk user and site import via CSV upload and FTP.
- FTP scheduling with configurable cron-style triggers.
- Email notification system for ticket events (created, updated, escalated, commented).
- Organization-level SMTP configuration stored in the database.
- Rate limiting on authentication endpoints.
- Security headers (CSP, X-Frame-Options, HSTS, etc.) applied to all responses.
- Base HTML templates and includes (nav, footer).
- Static files structure: CSS, JS, images, uploads.

---
