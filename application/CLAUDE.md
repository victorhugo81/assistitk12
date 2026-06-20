# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AssistITK12 is a Flask-based IT ticketing system for K-12 school districts. It supports multi-role access (Admin, Specialist, Technician, Teacher), encrypted email storage, SMTP notifications, FTP scheduling, and bulk user imports.

## Commands

**Run dev server:**
```bash
flask --app main.py run
```

**Run all tests:**
```bash
uv run pytest
```

**Run a single test file:**
```bash
uv run pytest tests/test_auth.py
```

**Run a single test by name:**
```bash
uv run pytest tests/test_auth.py::test_login_success
```

**Sync dependencies:**
```bash
uv sync
```

**Run database migrations:**
```bash
flask db upgrade
```

**Generate a new migration after model changes:**
```bash
flask db migrate -m "describe the change"
```

## Architecture

### App Factory

The canonical app factory is `create_app()` in [main.py](main.py). All Flask extensions (`db`, `login_manager`, `csrf`, `mail`, `limiter`, `scheduler`) are initialized there as module-level globals and re-used across the app. Models import `db` from `main`, not from `application`.

`application/__init__.py` is intentionally minimal — it only declares stub `db` and `login_manager` instances that are not used by the running application. Do not add a `create_app()` there; it would bypass all security middleware (CSRF, rate limiting, security headers, scheduler).

### Configuration

[config.py](config.py) defines `DevelopmentConfig`, `ProductionConfig`, and a `config` dict. The active config is selected by passing `config_name` to `create_app()`. The environment defaults to `development`. Tests inject their own `TestingConfig` via `conftest.py`.

Key env vars: `SECRET_KEY`, `DATABASE_URL` (MySQL in production, SQLite fallback for dev), `RATELIMIT_STORAGE_URI` (Redis required in production).

### Routing

All routes live in a single Blueprint (`routes_blueprint`) registered in [application/routes.py](application/routes.py). There is no sub-blueprint structure. Routes are organized by comment blocks within the single file.

### Models

Defined in [application/models.py](application/models.py). Key relationships:
- `User` → belongs to `Role` and `Site`
- `Ticket` → created by a `User`, optionally assigned to another `User`, belongs to a `Site` and `Title`
- `Ticket_content` — comments on a ticket
- `Ticket_attachment` — file attachments
- `Organization` (id=1 only) — stores org settings, SMTP config (encrypted), and FTP schedule config
- `BulkUploadLog` — audit trail for CSV user imports

### Encrypted Fields

User emails are **never stored in plain text**. Two columns exist on `User`:
- `email_enc` — Fernet-encrypted email
- `email_hash` — HMAC-SHA256 of the normalized email (used for lookup and uniqueness)

The `User.email` property transparently encrypts/decrypts using `SECRET_KEY`. Always query users by `email_hash` (via `hash_email()` from [application/utils.py](application/utils.py)), never by `email_enc`.

SMTP passwords and FTP credentials stored in `Organization` are also Fernet-encrypted using the same key.

### Roles

Fixed role IDs: Admin=1, Specialist=2, Technician=3, Teacher=4. Role-based access is checked via `current_user.is_admin` and `current_user.is_tech_role` properties on `User`.

### Email Notifications

Outgoing mail is handled in [application/email_utils.py](application/email_utils.py). SMTP settings are loaded from the `Organization` row on every app startup and override `.env` defaults (see `create_app()` in [main.py](main.py)).

### Scheduled Jobs

[application/scheduled_jobs.py](application/scheduled_jobs.py) contains the FTP transfer task. The APScheduler job (`org_ftp_schedule`) is registered/removed at startup based on `Organization.ftp_schedule_enabled`. Scheduler config is set in `main.py`; the REST API is disabled (`SCHEDULER_API_ENABLED = False`).

### Tests

Tests use SQLite in-memory with CSRF and rate limiting disabled. The session-scoped `app` fixture in [tests/conftest.py](tests/conftest.py) seeds a minimal dataset (roles, one site, one org, one admin, one teacher). Pre-authenticated clients (`admin_client`, `user_client`) inject the session directly without going through the login form.

## Security Invariants

These constraints must be preserved when modifying bulk import or user management code:

**Bulk CSV imports (manual and FTP, including the scheduled job)**
- `role_id` from CSV must be validated against the live `Role` table before any DB write. The validation pre-fetches `valid_role_ids` once per import, not per row.
- Admin accounts (`role_id=1`) must be excluded from the deactivation query/loop so a CSV that omits an admin cannot lock them out.
- Email addresses must be normalized to lowercase before hashing: `row['email'].strip().lower()`.

**Session cookies**
- `SESSION_COOKIE_SECURE = True` is set in the base `Config` class. `DevelopmentConfig` overrides it to `False` for local HTTP. Never remove the base-class default.

**Encrypted fields**
- `SECRET_KEY` is the single master key for Fernet encryption (emails, SMTP passwords, FTP credentials) and HMAC email hashes. Rotating `SECRET_KEY` without first re-encrypting all `email_enc` and `mail_password` rows will make all stored PII permanently unreadable. Any key-rotation work requires a migration script run before the key change.

**Access control helpers**
- `is_admin()` and `is_tech_role()` in [application/routes.py](application/routes.py) call `abort(403)` — they are not decorators. They must be called as the first statement inside the route function body (before any DB access) so that an early `abort` cannot be bypassed by later code.
