# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - 2025-02-01

### Added
- Initial project structure and application scaffolding.
- User authentication (login/logout).
- Models for users, roles, sites, tickets, and notifications.
- CRUD routes and forms for all models.
- Base HTML templates and includes (header, footer, nav).
- Static files structure: CSS, JS, images, uploads.

## [1.0.0] - 2025-05-18

### Added
- First production release.

---

## [1.0.1] - 2025-05-19

### Changed
- Updated README.md file.

---

## [1.0.2] - 2025-05-19

### Added
- Installation scripts (`create_env.py`, `seed_data.py`).
- Updated documentation for setup and usage with UV.
- Updated `.gitignore` file.

---

## [1.1.0] - 2026-02-21

### Added
- Email notification system (`email_utils.py`) with support for five event types: ticket created, status changed, assigned, escalated, and new comment.
- Dynamic recipient resolution — notifications are sent to the relevant parties based on the event type.
- Configurable notification message templates stored in the database.
- Encrypted SMTP credential storage using Fernet symmetric encryption (`utils.py`).
- Reusable password validation utility enforcing minimum 12 characters with uppercase, lowercase, number, and special character requirements.
- Organization settings page for managing SMTP email configuration.
- Structured application logging to replace debug print statements.

### Changed
- Updated UV configuration (`pyproject.toml`).
- Password update workflow now uses the shared validation function.
- Corrected timestamp handling to resolve timezone inconsistencies.

### Fixed
- Fixed duplicate attachment creation when updating tickets.
- Fixed ticket assignment not saving correctly.

---
