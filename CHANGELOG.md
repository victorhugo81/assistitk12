# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.6] - 2026-08-16

### Added
- About modal, opened by clicking the footer copyright notice, showing the app name, description, version, and copyright year.

### Changed
- Logo update.
- Sidebar logo is now centered.
- About modal's version number is now read from this changelog at runtime instead of being hardcoded in the template.

## [1.2.0] - 2026-08-08

### Security
- Login now shows one generic "Login failed" message for every failure case (wrong password, inactive account, locked account) instead of a reason-specific one, and always performs a password-hash comparison — against a fixed dummy hash when no matching account exists — so failed logins can no longer be used to enumerate valid accounts via message text or response timing.
- `SESSION_COOKIE_SECURE` now defaults to `True` in the base `Config` (previously only set in `ProductionConfig`); `DevelopmentConfig` opts out explicitly for local HTTP testing.
- `create_app()`'s default config now resolves to `ProductionConfig` (previously `DevelopmentConfig`) when no config name is passed and `FLASK_CONFIG` is unset, so debug mode can no longer be left on by omission. Production startup guards now check the resolved config class instead of the string `'production'` key, so they still apply under the new default.
- Added a per-request CSP nonce (`g.csp_nonce`); inline `<script>` blocks in templates now opt in individually via `nonce="{{ g.csp_nonce }}"`, and the CSP no longer grants `'unsafe-inline'` to scripts globally.
- Added a global per-IP rate limit (200/hour, 50/minute) with static assets exempted; raised the login limit from 5/min to 10/min and added a 10/min limit to `/set-password` and `/email-config/test`.
- `edit_user`: Specialist/Technician (non-admin) users can no longer edit Admin accounts or users at other sites — the form's dynamic role/site choices and the submitted values are both checked server-side now.
- `delete_user`: an admin can no longer delete their own account, or delete the last remaining Admin account.
- Added a `can_access_ticket()` authorization check so Technicians can no longer view another site's ticket by guessing/incrementing the ticket ID in the URL.
- Bulk FTP user sync now validates each row's `role_id` against real roles before upserting, and excludes Admin accounts from the pass that deactivates users missing from the CSV — preventing accidental Admin lockout from a bad or stale import file.
- `installation/create_env.py`: the generated database user's password is now passed as a bound query parameter instead of being interpolated into the `CREATE USER` statement; the generated DB/user names are validated against a strict alphanumeric pattern before being interpolated into DDL.
- Removed the third-party `buttons.github.io/buttons.js` script include from the page footer.
- Added `pip-audit` as a dev dependency for scanning Python dependencies for known vulnerabilities.

### Changed
- Reverted the data model from the K-12 student-analytics schema (Student/Teacher/Course/Parent/Absence/Incident/Grade) back to the ticketing/helpdesk schema (`Ticket`, `Title`, `Ticket_content`, `Ticket_attachment`), restoring the ticket list, detail, and comment/attachment routes.
- Added email notifications for ticket lifecycle events (created, status change, reassignment, escalation, new comment) via `send_ticket_notification()`.
- Tickets list: added a "Filter By Category" (ticket title) filter alongside the existing site/status/assigned-user filters.
- Visual redesign of the sidebar, top navbar, and dashboard stat cards to a flatter, bordered style — removed drop-shadow icon badges and gradient nav highlighting; page header banners now use a solid brand-color background.
- Updated the primary brand color from `#153448` to `#12707F` (teal) across the theme, including a new `--color-text-on-dark` token for banner text; updated the favicon and login-page logo.
- Various mobile-responsiveness adjustments to dashboard stat cards and top navbar spacing at narrow viewports.
- README: documented the app's flat/bordered design system.

### Dependencies
- Updated: `cryptography` 46.0.7 → 50.0.0, `flask-wtf` 1.2.2 → 1.3.0, `flask-caching` 2.3.1 → 2.4.0, `click` 8.3.2 → 8.3.3, `greenlet` 3.4.0 → 3.5.0, `pymysql` 1.1.2 → 1.1.3, `idna` 3.11 → 3.18, `mako` 1.3.10 → 1.3.12, `packaging` 26.0 → 26.2, `tzdata` 2026.1 → 2026.2.

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


## [1.0.0] - 2025-04-27

### Added
 - update mobile resolution for dashboard
---
