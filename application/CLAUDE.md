CLAUDE.md
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

What This App Is
AnalyticsK12 is a K-12 school district analytics platform. It manages student demographics, attendance (absences), discipline (incidents), staffing (teachers, courses), and family contacts (parents) across multiple school sites. It includes role-based access control, bulk CSV import, encrypted credentials, and session-based global filters (school year, site, snap date, student status).

Running the App
# Run dev server
uv run flask --app main.py run

# Or activate the venv and use flask directly
source .venv/bin/activate
flask --app main.py run
Dependencies are managed with uv. To add or sync packages:

uv sync
uv add <package>
Database
MySQL via PyMySQL. Connection string is in .env as DATABASE_URL.

# Apply all pending migrations
flask --app main.py db upgrade

# Generate a new migration after model changes
flask --app main.py db migrate -m "description"

# Check current migration version
flask --app main.py db current
Migration files live in migrations/versions/. After adding or changing a model, always run migrate then upgrade.

Seeding Data
# 1. Create MySQL DB and write .env (interactive)
python installation/create_env.py

# 2. Seed roles, default site, admin user (interactive)
python installation/seed_data.py

# 3. Seed academic demo data (sites, students, teachers, courses, parents, absences, incidents)
python installation/seed_academic_data.py
Architecture
App Factory
main.py contains create_app(config_name). It initializes Flask extensions (SQLAlchemy, Flask-Login, CSRF, Flask-Mail, Flask-Limiter, APScheduler), registers the single blueprint, applies security headers, and wires database-stored SMTP config from the Organization model.

Single Blueprint
All routes live in application/routes.py under one blueprint (routes_blueprint). The file is large (~2700+ lines) and organized into labeled sections:

Auth — login, logout, set-password, account lockout
Users / Roles / Sites / Notifications / Organization — admin management
Global session filters — /set_school_year, /set_site_filter, /set_snap_date, /set_status_filter (store to session, redirect back)
Context processor — injects active_schoolyr, active_site_filter, active_snap_date, active_status_filter, global_sites, global_school_years into every template
Students — list (paginated, multi-filter), detail, edit, export CSV (/students/export/csv)
Demographics dashboard — /demographics (charts + tables)
SWD dashboard — /swd
Absences — /absences/dashboard, /absences (list)
Discipline dashboard — /discipline
Incidents — /incidents (list)
Teachers / Courses / Parents — list + detail + edit
Models (application/models.py)
Key models and their notable fields:

Model	Notes
Student	status is a computed @property from enter_date/exit_date — there is no status column in DB
User	Email stored encrypted (cryptography.fernet); password hashed with scrypt
Organization	Stores SMTP and FTP config with encrypted passwords; config overrides app.config at startup
Absence	Linked to student via ssid string (not FK), site via site_id FK
Incident	Linked to student via sisid string (not FK); site is stored as the site acronym string
Site	Has both site_name and site_acronyms — dashboards use acronyms for compact display
Global Session Filters
The context processor reads these four session keys and injects them into every template:

active_schoolyr — school year string (e.g. "2025-2026")
active_site_filter — site ID as string
active_snap_date — ISO date string for enrollment-as-of queries
active_status_filter — "active" | "inactive" | "all"
Routes that support site filtering from the URL (e.g. dashboard table links) check request.args.get('site_filter') first, then fall back to session.

Student Subgroup Filtering
/students supports multi-select subgroup filtering via repeated ?subgroup= URL params (getlist). The route applies AND logic across all selected subgroups. Supported values: homeless, frm, swd, foster, migrant, sed504, no_ssid.

English status and gender use single-value URL params (english_status, gender).

Templates
application/templates/base.html — main layout; includes includes/nav.html
application/templates/includes/nav.html — sidebar nav + top navbar with global filter bar
application/templates/dashboard/ — analytics dashboards (demographics, swd, discipline, absenteeism)
Chart rendering uses Chart.js loaded from static/js/plugins/chartjs.min.js
Print/PDF export uses a printDashboard() JS function that swaps canvas elements for images and applies a zoom factor
CSS / Print
application/static/css/dashboards.css contains shared dashboard styles including .demo-kpi, .chart-card, .chart-wrap and @media print rules for all dashboards.

Key Conventions
site_filter parameter: In the students route, URL param site_filter overrides session. In all other routes it comes from session only.
Ethnicity codes: Stored as 3-digit strings ('500' = Hispanic/Latino, '600' = African American, etc.). The ethnicity_table_data variable is always a list of (code, label, count) tuples.
Add pages removed: add_student, add_teacher, add_course, add_parent routes redirect to their list pages — the templates were intentionally deleted.
student.status: Never filter with Student.status == 'Active' in SQL — it's a Python property. Use enter_date/exit_date conditions instead.

Frontend Visual Design System
The UI was redesigned from a gradient-heavy "admin template" look to a flat, bordered, editorial style. Everything lives in application/static/css/style.css as CSS custom properties — there is no build step or preprocessor.

Design tokens (:root in style.css)
color-primary (#153448, fixed brand navy), color-secondary (slate), color-accent (terracotta, used sparingly for CTAs/active states), plus color-success/-warning/-danger/-info and neutral color-bg/-surface/-border/-border-strong/-text/-text-muted. Bootstrap's own bs-primary, bs-success, bs-warning, etc. are re-pointed at these so stock bg-success, badge, alert, and form-validation colors stay in sync without touching template markup.
radius scale is restrained (radius-sm 5px to radius-xl 14px) — avoid introducing new pill-shaped elements outside badges/switches.
shadow is used only for overlays (dropdowns, modals, the login card); flat surfaces get a 1px border instead of a shadow.
Inter is the only typeface, with a real weight/size hierarchy defined near the top of the file (space scale, h1 to h6 rules).

Component conventions
Buttons (.btn and variants) always carry a visible border in a matching darker shade — never a borderless flat fill — per the accessibility pass.
Page headers: templates still use the original markup classes (.custom-title-card, or .bg-gradient-main.shadow-dark.border-radius-lg on add/edit forms) — these are intentionally not gradient banners anymore. They are flattened entirely in CSS via compound selectors so the 20+ CRUD templates didn't need markup changes. If you add a new list/form page, reuse the same class pair rather than inventing a new header style.
Cards and tables are bordered, not shadowed; table headers use a light sunken background, not a solid dark fill.
Focus states use a global :focus-visible outline in the accent color — don't suppress it with outline: none on new interactive elements.

Navigation (application/templates/includes/nav.html)
The sidebar is a flush, full-height, dark-navy panel, not a floating white card. Active links get a left accent border, not a filled pill — set via a plain active class in the Jinja conditional, not bg-gradient-main text-white. The top bar's navbar-collapse has no real Bootstrap toggler anywhere in the markup, so ".navbar-main .navbar-collapse { display: flex !important }" in style.css keeps the mobile hamburger and user info visible at every breakpoint — don't remove that rule or mobile nav disappears.