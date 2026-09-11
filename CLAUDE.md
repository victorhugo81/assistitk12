# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This App Is

**AssistITK12** is a Flask-based IT ticketing/helpdesk system for K-12 school districts. It supports multi-role access (Admin, Specialist, Technician, Teacher), encrypted email and credential storage, SMTP email notifications for ticket lifecycle events (created, assigned, status change, escalation, comment), a live ticket-notification bell for staff, FTP-based bulk user import with a configurable schedule, and per-site ticket/user scoping.

---

## Running the App

```bash
# Run dev server
uv run flask --app main.py run

# Or activate the venv and use flask directly
source .venv/bin/activate
flask --app main.py run
```

`flask run` with no config specified now resolves to `ProductionConfig` (secure by default — see "Configuration" below). For local HTTP development, set `FLASK_CONFIG=development` in `.env` first, or `SESSION_COOKIE_SECURE=True` will block session cookies over plain HTTP.

Dependencies are managed with `uv`. To add or sync packages:
```bash
uv sync
uv add <package>
```

**Tests:**
```bash
uv run pytest                              # full suite
uv run pytest tests/test_auth.py           # one file
uv run pytest tests/test_auth.py::test_login_success  # one test
```

**Dependency vulnerability scan** (`pip-audit` is a dev dependency):
```bash
uv run pip-audit
```

---

## Database

MySQL via PyMySQL. Connection string is in `.env` as `DATABASE_URL` (SQLite fallback for local dev if unset).

```bash
# Apply all pending migrations
flask --app main.py db upgrade

# Generate a new migration after model changes
flask --app main.py db migrate -m "description"

# Check current migration version
flask --app main.py db current
```

Migration files live in `migrations/versions/`. After adding or changing a model, always run `migrate` then `upgrade`.

**Before running `flask db upgrade` on an environment you haven't touched before, run `flask db current` first.** If it prints nothing, that database has no `alembic_version` table — its schema was likely created straight from the models (e.g. `db.create_all()`) rather than through migrations. Blindly upgrading in that state replays the *entire* history from base and fails on "already exists" errors. Instead: inspect the real schema, find the migration revision it actually matches, and `flask db stamp <that revision>` first — only then run `upgrade`, which will apply just the remaining steps.

---

## Seeding Data

```bash
# 1. Create MySQL DB and write .env (interactive)
python installation/create_env.py

# 2. Seed roles, default site, admin user (interactive)
python installation/seed_data.py
```

---

## Architecture

### App Factory

The canonical app factory is `create_app(config_name=None)` in `main.py`. All Flask extensions (`db`, `login_manager`, `csrf`, `mail`, `limiter`, `scheduler`) are initialized there as module-level globals and reused across the app. Models import `db` from `main`, not from `application`.

`application/__init__.py` is intentionally minimal — it only declares stub `db` and `login_manager` instances that are not used by the running application. Do not add a `create_app()` there; it would bypass all security middleware (CSRF, rate limiting, security headers, CSP nonce, scheduler).

### Configuration

`config.py` defines `DevelopmentConfig`, `ProductionConfig`, and a `config` dict. `create_app()` resolves `config_name` from its argument, then the `FLASK_CONFIG` env var, then falls back to `'default'` — which maps to **`ProductionConfig`** (secure by default: `DEBUG=False`, `SESSION_COOKIE_SECURE=True`). Local development must explicitly set `FLASK_CONFIG=development` in `.env` to get `DevelopmentConfig`. The production startup guards in `create_app()` (weak `SECRET_KEY`, in-memory `RATELIMIT_STORAGE_URI`) check the *resolved config class*, not the string `'production'`, so they still fire when `config_name` resolves to `'default'`.

Key env vars: `SECRET_KEY`, `DATABASE_URL` (MySQL in production, SQLite fallback for dev), `RATELIMIT_STORAGE_URI` (Redis required in production), `FLASK_CONFIG` (dev-only override).

Tests inject their own `TestingConfig` via `conftest.py` (in-memory SQLite, CSRF and rate limiting disabled).

### Routing

All routes live in a single Blueprint (`routes_blueprint`) registered in `application/routes.py`. There is no sub-blueprint structure. Routes are organized by comment blocks within the single file: Auth (login, logout, set-password, lockout), Users/Roles/Sites/Notifications/Organization (admin management), Tickets (list with site/status/assigned-user/category filters, add, edit, delete, AJAX comments, file attachments), Ticket Titles (categories), Dashboard (`/` — stat counts + Chart.js charts), Profile, Bulk user import (manual CSV upload and FTP), and the ticket-notification bell (context processor + mark-seen endpoint).

### Models (`application/models.py`)

| Model | Notes |
|---|---|
| `User` | Belongs to `Role` and `Site`. Email stored encrypted (`email_enc` + `email_hash`, see "Encrypted Fields"); password hashed with scrypt. `ticket_alerts_seen_at` tracks the notification bell's read state. |
| `Ticket` | Created by a `User`, optionally assigned to another `User`, belongs to a `Site` and `Title`. `tck_status` is one of `'1-pending'`, `'2-progress'`, `'3-completed'`. |
| `Ticket_content` | Comments on a ticket. |
| `Ticket_attachment` | File attachments (validated by extension + magic bytes, see `application/utils.py`). |
| `Title` | Ticket categories (e.g. "Printer Issues"), admin-managed. |
| `Organization` | Singleton (id=1 only) — org name, SMTP config (encrypted), and FTP schedule config (encrypted). |
| `Notification` | Admin-authored site-wide banner messages (only one `Active` at a time) — unrelated to the ticket-notification bell. |
| `BulkUploadLog` | Audit trail for CSV/FTP user imports. |

### Encrypted Fields

User emails are never stored in plain text. Two columns exist on `User`:
- `email_enc` — Fernet-encrypted email
- `email_hash` — HMAC-SHA256 of the normalized email (used for lookup and uniqueness)

The `User.email` property transparently encrypts/decrypts using `SECRET_KEY`. Always query users by `email_hash` (via `hash_email()` from `application/utils.py`), never by `email_enc`.

SMTP passwords and FTP credentials stored in `Organization` are also Fernet-encrypted using the same key.

### Roles

Fixed role IDs: Admin=1, Specialist=2, Technician=3, Teacher=4. Role-based access is checked via `current_user.is_admin` and `current_user.is_tech_role` (Specialist or Technician) properties on `User`.

### Ticket Authorization

`can_access_ticket(ticket)` in `application/routes.py` is the single authorization check for ticket detail/comment/attachment routes (`edit_ticket`, `add_comment`, `download_attachment`, `delete_attachment`). Admin/Specialist can access any ticket; Technician is scoped to their own site (matching the `/tickets` list filter); everyone else only their own tickets. New ticket-detail-style routes must call this helper rather than re-deriving a role check.

`edit_user`: non-admin "tech role" staff (Specialist/Technician) may only edit non-admin users at their own site — both the form's dynamic `role_id`/`site_id` choices and the submitted values are checked server-side. `delete_user` blocks deleting your own account or the last remaining Admin.

### Ticket Notification Bell

`User.ticket_alerts_seen_at` (nullable `DateTime`) records when a user last opened the bell dropdown; `NULL` means everything currently visible counts as new. `inject_new_ticket_alerts()` (an `app_context_processor` in `routes.py`) computes `new_ticket_count` and `new_tickets` for every template, using the same site scoping as the `/tickets` list, and returns zeroed defaults for anyone who isn't `is_admin`/`is_tech_role`. It deliberately **includes** tickets the viewer created themselves — the same admin/technician often both files and resolves tickets. `POST /notifications/tickets/mark-seen` sets the timestamp; the bell markup (`includes/nav.html`) and its mark-seen script (`includes/footer.html`) both need `nonce="{{ g.csp_nonce }}"` like every other inline script.

### Email Notifications

Outgoing mail is handled in `application/email_utils.py` (`send_ticket_notification`, `send_temp_password_email`, `send_password_updated_email`). SMTP settings are loaded from the `Organization` row on every app startup and override `.env` defaults (see `create_app()` in `main.py`).

### Scheduled Jobs

`application/scheduled_jobs.py` contains the FTP transfer task. The APScheduler job (`org_ftp_schedule`) is registered/removed at startup based on `Organization.ftp_schedule_enabled`. Scheduler config is set in `main.py`; the REST API is disabled (`SCHEDULER_API_ENABLED = False`).

### Templates & Frontend

- `application/templates/base.html` — main layout; includes `includes/nav.html` and `includes/footer.html`.
- `includes/nav.html` — dark sidebar + top navbar (welcome text, notification bell for staff).
- `includes/footer.html` — copyright/About modal, and most of the app's small inline `<script>` behaviors (mobile menu, delete-confirmation modal, unsaved-changes warning, bell mark-seen) — all require `nonce="{{ g.csp_nonce }}"`.
- One template per page under `application/templates/` (list/add/edit trio per resource: users, roles, sites, notifications, titles, tickets; plus `index.html` dashboard, `login.html`, `profile.html`, `organization.html`, `bulk_upload_data.html`).
- Dashboard charts use Chart.js (`static/js/plugins/chartjs.min.js` + `static/js/dashboard.js`).
- All styling lives in `application/static/css/style.css` as CSS custom properties (teal brand color, softly rounded/minimal design system, subtle motion) — see the "Frontend Visual Design System" notes in `application/CLAUDE.md` for the token/component conventions in detail.

### Tests

Tests use SQLite in-memory with CSRF and rate limiting disabled. The session-scoped `app` fixture in `tests/conftest.py` seeds a minimal dataset (roles, one site, one org, one admin, one teacher). Pre-authenticated clients (`admin_client`, `user_client`) inject the session directly without going through the login form.

---

## Security Invariants

These constraints must be preserved when modifying bulk import, auth, or user-management code (they came out of a full security audit — see `CHANGELOG.md` and `application/CLAUDE.md`'s "Backend Security Architecture" section for the fixes and reasoning):

**Bulk CSV imports (manual and FTP, including the scheduled job)**
- `role_id` from CSV must be validated against the live `Role` table before any DB write. The validation pre-fetches `valid_role_ids` once per import, not per row.
- Admin accounts (`role_id=1`) must be excluded from the deactivation query/loop so a CSV that omits an admin cannot lock them out.
- Email addresses must be normalized to lowercase before hashing: `row['email'].strip().lower()`.

**Session cookies**
- `SESSION_COOKIE_SECURE = True` is set in the base `Config` class. `DevelopmentConfig` overrides it to `False` for local HTTP only. Never remove the base-class default.

**Encrypted fields**
- `SECRET_KEY` is the single master key for Fernet encryption (emails, SMTP passwords, FTP credentials) and HMAC email hashes. Rotating `SECRET_KEY` without first re-encrypting all `email_enc`/`mail_password`/`ftp_*_enc` rows will make all stored PII permanently unreadable. Any key-rotation work requires a migration script run before the key change.

**Access control helpers**
- `is_admin()` and `is_tech_role()` in `application/routes.py` call `abort(403)` — they are not decorators. They must be called as the first statement inside the route function body (before any DB access) so an early abort can't be bypassed by later code.
- `can_access_ticket()` must be used by any route that reads/mutates a single ticket by ID (see "Ticket Authorization" above) — don't re-derive an inline `role_id in [...]` check.

**Login**
- Login always runs a password-hash comparison (against a fixed dummy hash for a nonexistent account) and shows one generic failure message, regardless of whether the account doesn't exist, has the wrong password, is inactive, or is locked. Don't reintroduce per-case messages or short-circuit the hash comparison — both were real account-enumeration vectors.

**Content-Security-Policy**
- `main.py` issues a fresh nonce per request (`g.csp_nonce`); `script-src` allows only `'self'` plus that nonce, with no `'unsafe-inline'`. Any new inline `<script>` block needs `nonce="{{ g.csp_nonce }}"` or the browser silently blocks it.

**Rate limiting**
- The `Limiter` in `main.py` has global `default_limits` (200/hour, 50/minute per IP), with `static` explicitly exempted. Login (10/min), `set_password`/`test_email` (10/min), and `add_comment` (20/min) carry their own tighter limits.
