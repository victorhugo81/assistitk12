from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app, send_from_directory, jsonify, session, make_response
from flask_limiter.util import get_remote_address
from flask_login import login_user, login_required, logout_user, current_user
from flask_paginate import Pagination, get_page_args
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from .models import User, Role, Site, Notification, Organization, BulkUploadLog, Student, Teacher, Course, Parent, Absence, Incident, Grade
from .forms import LoginForm, UserForm, RoleForm, SiteForm, NotificationForm, OrganizationForm, EmailConfigForm, StudentForm, TeacherForm, CourseForm, ParentForm
from .utils import validate_password, validate_file_upload, encrypt_mail_password, decrypt_mail_password, hash_email
from .email_utils import send_temp_password_email, send_password_updated_email
from main import db, login_manager, mail, limiter, scheduler
from flask_mail import Message
from datetime import datetime, timedelta, timezone
import time, os, re, csv, logging, secrets, ftplib, io, socket
from sqlalchemy.sql import func
from flask_caching import Cache
from sqlalchemy import case

# Cache configuration for storing database query results
# Using simple cache type with 2-hour expiration for assigned users query
cache = Cache(config={'CACHE_TYPE': 'simple'})

# Cached function to retrieve users with specific roles (1 and 2)
# This avoids repeated database queries for frequently accessed user data
@cache.cached(timeout=7200, key_prefix='assigned_users')
def get_assigned_users():
    """
    Retrieve all users with role IDs 1 or 2 from the database.
    Results are cached for 2 hours to improve performance.
    
    Returns:
        list: List of User objects with role_id 1 or 2
    """
    return User.query.filter(User.role_id.in_([1, 2])).all()


# Create a Blueprint for organizing routes
# This allows for modular application structure and route organization
routes_blueprint = Blueprint('routes', __name__)

@routes_blueprint.app_context_processor
def inject_active_notifications():
    try:
        notifications = Notification.query.filter_by(msg_status='Active').all()
    except Exception:
        notifications = []
    return dict(active_notifications=notifications)


@routes_blueprint.app_context_processor
def inject_org():
    try:
        org = db.session.get(Organization, 1)
    except Exception:
        org = None
    return dict(org=org)


@routes_blueprint.app_context_processor
def inject_global_school_year():
    try:
        school_years = [r[0] for r in
                        db.session.query(Student.schoolyr)
                        .filter(Student.schoolyr.isnot(None), Student.schoolyr != '')
                        .distinct().order_by(Student.schoolyr.desc()).all()]
        global_sites         = Site.query.order_by(Site.site_name).all()
        active_schoolyr      = session.get('active_schoolyr', '')
        active_status_filter = session.get('active_status_filter', 'active')
        active_site_filter   = session.get('active_site_filter', '')
        active_snap_date     = session.get('active_snap_date', '')
        active_site = next(
            (s.site_name for s in global_sites if str(s.id) == active_site_filter),
            ''
        )
    except Exception:
        school_years, global_sites                          = [], []
        active_schoolyr, active_status_filter               = '', 'active'
        active_site_filter, active_snap_date, active_site   = '', '', ''
    return dict(global_school_years=school_years, global_sites=global_sites,
                active_schoolyr=active_schoolyr, active_status_filter=active_status_filter,
                active_site_filter=active_site_filter, active_snap_date=active_snap_date,
                active_site=active_site)


@routes_blueprint.before_request
def set_session_defaults():
    """Set first-visit session defaults before any route reads them."""
    if not current_user.is_authenticated:
        return
    if 'active_schoolyr' not in session:
        try:
            row = db.session.query(Student.schoolyr)\
                    .filter(Student.schoolyr.isnot(None), Student.schoolyr != '')\
                    .distinct().order_by(Student.schoolyr.desc()).first()
            session['active_schoolyr'] = row[0] if row else ''
        except Exception:
            session['active_schoolyr'] = ''


@routes_blueprint.route('/set_school_year')
@login_required
def set_school_year():
    yr = request.args.get('yr', '').strip()
    if not yr:
        # Fall back to the most recent available year
        row = db.session.query(Student.schoolyr)\
                .filter(Student.schoolyr.isnot(None), Student.schoolyr != '')\
                .distinct().order_by(Student.schoolyr.desc()).first()
        yr = row[0] if row else ''
    session['active_schoolyr'] = yr
    return redirect(request.referrer or url_for('routes.index'))


@routes_blueprint.route('/set_site_filter')
@login_required
def set_site_filter():
    session['active_site_filter'] = request.args.get('sf', '').strip()
    return redirect(request.referrer or url_for('routes.index'))


@routes_blueprint.route('/set_snap_date')
@login_required
def set_snap_date():
    session['active_snap_date'] = request.args.get('d', '').strip()
    return redirect(request.referrer or url_for('routes.index'))


@routes_blueprint.route('/set_status_filter')
@login_required
def set_status_filter():
    sf = request.args.get('sf', 'active').strip()
    if sf not in ('active', 'inactive', 'all'):
        sf = 'active'
    session['active_status_filter'] = sf
    return redirect(request.referrer or url_for('routes.index'))


# *****************************************************************
#-------------------- Core Setup -------------------------
# -------------- Do not change this section --------------
# *****************************************************************


# ****************** Force Password Change Enforcement *************
@routes_blueprint.before_request
def enforce_password_change():
    """Redirect users with a temporary password to the set-password page before they can do anything else."""
    if current_user.is_authenticated and getattr(current_user, 'must_change_password', False):
        allowed = {'routes.set_password', 'routes.logout', 'static'}
        if request.endpoint not in allowed:
            return redirect(url_for('routes.set_password'))



# ****************** Set Password (temp password flow) *************
@routes_blueprint.route('/set-password', methods=['GET', 'POST'])
@login_required
def set_password():
    org = db.session.get(Organization, 1)
    organization_name = org.organization_name if org else 'AssistITk12'

    if request.method == 'POST':
        new_password     = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if not new_password or not confirm_password:
            flash('Both fields are required.', 'danger')
            return render_template('change_password.html', organization_name=organization_name)

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('change_password.html', organization_name=organization_name)

        is_valid, error_message = validate_password(new_password)
        if not is_valid:
            flash(error_message, 'danger')
            return render_template('change_password.html', organization_name=organization_name)

        current_user.password = generate_password_hash(new_password)
        current_user.must_change_password = False
        db.session.add(current_user)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"set_password failed for user {current_user.id}: {e}", exc_info=True)
            flash('An error occurred while saving your password. Please try again.', 'danger')
            return render_template('change_password.html', organization_name=organization_name)
        flash('Password updated successfully. Welcome!', 'success')
        return redirect(url_for('routes.index'))

    return render_template('change_password.html', organization_name=organization_name)



# ****************** Login Setup *******************************
@login_manager.user_loader
def load_user(user_id):
    """
    Flask-Login user loader callback.
    Loads a user from the database for session management.
    
    Args:
        user_id (str): The user ID to load from database
        
    Returns:
        User: The User object for the specified ID
    """
    return db.session.get(User, int(user_id))

# ****************** Admin *******************************
def is_admin():
    """
    Check if the current user has admin privileges.
    Abort with 403 Forbidden if the user is not an admin.
    
    Assumes role_id 1 represents Admin status.
    """
    if not current_user.is_authenticated or current_user.role_id != 1:  # Assuming 1 = Admin
        abort(403)

def is_tech_role():
    """
    Check if the current user has a technical role.
    Abort with 403 Forbidden if the user is not in a tech role.
    
    Technical roles are Specialist (role_id=2) and Technician (role_id=3).
    """
    if not current_user.is_authenticated or current_user.role_id not in [2, 3]:  # Assuming 2 = Specialist, 3 = Technician
        abort(403)

# ****************** Forbidden Error Page *******************************
@routes_blueprint.app_errorhandler(403)
def forbidden_error(error):
    """
    Custom 403 error handler for the application.
    Renders a custom error page when access is forbidden.
    
    Args:
        error: The error that triggered this handler
        
    Returns:
        tuple: Rendered error template and 403 status code
    """
    return render_template('error.html'), 403


# ****************** Login Page *******************************
@routes_blueprint.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", key_func=get_remote_address)
def login():
    """
    Handle user login requests.

    GET: Display the login form
    POST: Process the login form submission

    Returns:
        Response: Rendered login template or redirect to index on successful login
    """
    # Fetch organization name for display on login page
    organization = db.session.get(Organization, 1)
    organization_name = organization.organization_name if organization else "AssistITk12"

    _MAX_ATTEMPTS = 5
    _LOCKOUT_MINUTES = 15

    form = LoginForm()
    if form.validate_on_submit():
        _key = current_app.config['SECRET_KEY']
        user = User.query.filter_by(email_hash=hash_email(form.email.data, _key)).first()

        # Check lockout before verifying the password
        if user and user.locked_until and user.locked_until > datetime.now(timezone.utc).replace(tzinfo=None):
            remaining = int((user.locked_until - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() // 60) + 1
            flash(f'Account locked. Try again in {remaining} minute(s).', 'danger')
            return render_template('login.html', form=form, organization_name=organization_name)

        if user and check_password_hash(user.password, form.password.data):
            if user.status != 'Active':
                flash('Your account is inactive. Please contact your administrator.', 'danger')
            else:
                # Successful login — reset lockout counters
                user.failed_login_attempts = 0
                user.locked_until = None
                db.session.commit()
                session.clear()
                session.permanent = True  # enforce PERMANENT_SESSION_LIFETIME
                login_user(user)
                if user.must_change_password:
                    return redirect(url_for('routes.set_password'))
                return redirect(url_for('routes.index'))
        else:
            # Failed attempt — increment counter and lock if threshold reached
            if user:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= _MAX_ATTEMPTS:
                    user.locked_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=_LOCKOUT_MINUTES)
                    user.failed_login_attempts = 0
                    db.session.commit()
                    flash(f'Too many failed attempts. Account locked for {_LOCKOUT_MINUTES} minutes.', 'danger')
                    return render_template('login.html', form=form, organization_name=organization_name)
                db.session.commit()
            flash('Login failed. Please check your credentials.', 'danger')

    return render_template(
        'login.html',
        form=form,
        organization_name=organization_name
    )


# ****************** Logout *******************************
@routes_blueprint.route('/logout')
@login_required
def logout():
    """
    Log out the currently authenticated user.
    Redirects to the login page after logout.
    
    Returns:
        Response: Redirect to login page
    """
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('routes.login'))



# ****************** Update Organization Page *******************************
@routes_blueprint.route('/organization', methods=['GET', 'POST'])
@login_required
def organization():
    is_admin()
    """
    Display and process organization settings form.
    
    GET: Display the organization settings form
    POST: Process the form submission to update organization details
    
    Returns:
        Response: Rendered organization template or redirect on successful update
    """
    # Map URL paths to readable page names for navigation
    page_names = {'/organization': 'Data Integration'}
    # Get current path for navigation highlighting
    current_path = request.path
    # Get page name for display in UI
    current_page_name = page_names.get(current_path, 'Unknown Page')
    
    # Hardcoding organization_id to 1
    # NOTE: This assumes a single organization in the system
    organization_id = 1
    organization = Organization.query.get_or_404(organization_id)
    
    # Initialize form with current organization data
    form = OrganizationForm(obj=organization)

    # Initialize email config form (pre-populate from DB, but never show password)
    email_form = EmailConfigForm(obj=organization)
    email_form.mail_password.data = ''

    if form.validate_on_submit():
        # Check for duplicate organization names (excluding the current one)
        existing_organization = Organization.query.filter(
            Organization.organization_name == form.organization_name.data,
            Organization.id != organization.id
        ).first()

        if existing_organization:
            flash('An organization with that name already exists.', 'danger')
            return render_template('organization.html', form=form, email_form=email_form, organization=organization)

        # Update organization with form data
        organization.organization_name = form.organization_name.data
        organization.site_version = form.site_version.data
        db.session.commit()  # Save changes to database

        flash('Organization updated successfully!', 'success')
        return redirect(url_for('routes.organization'))

    # For GET requests or invalid form submissions, display the form
    return render_template('organization.html',
                          form=form,
                          email_form=email_form,
                          organization=organization,
                          current_path=current_path,
                          current_page_name=current_page_name)

# *****************************************************************
#-------------------- END Core Setup ---------------------
# -------------- Do not change this section --------------
# *****************************************************************


# ****************** Email Configuration *******************************
@routes_blueprint.route('/email-config', methods=['POST'])
@login_required
def email_config():
    """
    Save Flask-Mail SMTP configuration from the organization settings page.
    Updates the Organization record and immediately applies settings to the running app.
    """
    is_admin()
    organization = Organization.query.get_or_404(1)
    email_form = EmailConfigForm()

    if email_form.validate_on_submit():
        organization.mail_server = email_form.mail_server.data or None
        organization.mail_port = email_form.mail_port.data or None
        organization.mail_use_tls = email_form.mail_use_tls.data
        organization.mail_use_ssl = email_form.mail_use_ssl.data
        organization.mail_username = email_form.mail_username.data or None
        if email_form.mail_password.data:
            organization.mail_password = encrypt_mail_password(
                email_form.mail_password.data, current_app.config['SECRET_KEY']
            )
        organization.mail_default_sender = email_form.mail_default_sender.data or None
        db.session.commit()

        # Apply updated settings to the running Flask-Mail instance
        current_app.config['MAIL_SERVER'] = organization.mail_server or 'localhost'
        current_app.config['MAIL_PORT'] = organization.mail_port or 587
        current_app.config['MAIL_USE_TLS'] = bool(organization.mail_use_tls)
        current_app.config['MAIL_USE_SSL'] = bool(organization.mail_use_ssl)
        current_app.config['MAIL_USERNAME'] = organization.mail_username
        current_app.config['MAIL_PASSWORD'] = decrypt_mail_password(
            organization.mail_password or '', current_app.config['SECRET_KEY']
        )
        current_app.config['MAIL_DEFAULT_SENDER'] = organization.mail_default_sender
        mail.init_app(current_app)

        flash('Email settings updated successfully!', 'success')
    else:
        for field, errors in email_form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'danger')

    return redirect(url_for('routes.organization'))


# ****************** Test Email *******************************
@routes_blueprint.route('/email-config/test', methods=['POST'])
@login_required
def test_email():
    """
    Send a test email to verify the current Flask-Mail configuration.
    Returns JSON with success/error details.
    """
    is_admin()
    recipient = request.form.get('test_recipient', '').strip()
    if not recipient:
        return jsonify({'success': False, 'message': 'Recipient email is required.'}), 400

    try:
        msg = Message(
            subject='Test Email – AssistITK12',
            recipients=[recipient],
            body=(
                'This is a test email sent from AssistITK12.\n\n'
                'Your email configuration is working correctly.\n\n'
                '— AssistITK12 System'
            )
        )
        mail.send(msg)
        current_app.logger.info(f"Test email sent to {recipient} by user {current_user.id}")
        return jsonify({'success': True, 'message': f'Test email sent to {recipient}.'})
    except Exception as e:
        current_app.logger.error(f"Test email failed: {type(e).__name__}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# *****************************************************************
#-------------------- Site Template Pages ---------------------
# *****************************************************************

# *********************************************************************
# ****************** Dashboard Page *******************************
@routes_blueprint.route('/', methods=['GET', 'POST'])
@login_required
def index():
    org = db.session.get(Organization, 1)
    return render_template(
        'index.html',
        current_page_name='Dashboard',
        org=org,
    )


# ****************** Card Visibility *******************************
@routes_blueprint.route('/organization/card-visibility', methods=['POST'])
@login_required
def card_visibility():
    is_admin()
    org = Organization.query.get_or_404(1)
    cards = ['demographics', 'absenteeism', 'discipline', 'swd',
             'registration', 'enrollment', 'attendance_rates']
    for card in cards:
        setattr(org, f'show_{card}', f'show_{card}' in request.form)
    db.session.commit()
    flash('Dashboard card visibility updated.', 'success')
    return redirect(url_for('routes.organization') + '#dashboard-cards')


# ***************************************************************
# ****************** Profile Page *******************************
@routes_blueprint.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
        # Mapping paths to page names
    page_names = {'/profile': 'My Profile'}
    # Get the current path
    current_path = request.path
    # Get the corresponding page name or default to "Unknown Page"
    current_page_name = page_names.get(current_path, 'Unknown Page')
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        # Verify current password first
        if not current_password or not check_password_hash(current_user.password, current_password):
            flash('Current password is incorrect.', 'danger')
            return render_template('profile.html', user=current_user, role=current_user.role,
                current_path=current_path, current_page_name=current_page_name)
        # Validate new passwords
        if not password or not confirm_password:
            flash('Both password fields are required.', 'danger')
        elif password != confirm_password:
            flash('Passwords do not match. Please try again.', 'danger')
        else:
            # Validate password complexity
            is_valid, error_message = validate_password(password)
            if not is_valid:
                flash(error_message, 'danger')
                return render_template('profile.html', user=current_user, role=current_user.role,
                    current_path=current_path, current_page_name=current_page_name)

            # Password is valid, proceed with update
            current_user.password = generate_password_hash(password)
            current_user.must_change_password = False
            try:
                db.session.commit()
                flash('Password updated successfully!', 'success')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"profile password update failed for user {current_user.id}: {e}", exc_info=True)
                flash('An error occurred while updating your password. Please try again.', 'danger')
            return redirect(url_for('routes.profile'))
    role = current_user.role  # Assuming current_user has a 'role' attribute
    return render_template('profile.html', user=current_user, role=role,
        current_path=current_path, 
        current_page_name=current_page_name
    )



# *********************************************************************
# ****************** Users Management Page ****************************
@routes_blueprint.route('/users', methods=['GET'])
@login_required
def users():
    page_names = {'/users': 'Manage Users'}
    current_path = request.path
    current_page_name = page_names.get(current_path, 'Unknown Page')
    
    # Ensure only admins and tech roles can access this route
    if not (current_user.is_admin or current_user.is_tech_role):
        abort(403)

    page, per_page, offset = get_page_args(page_parameter="page", per_page_parameter="per_page")
    search = request.args.get('search', '').strip()
    site_filter = request.args.get('site_filter', '').strip()
    role_filter = request.args.get('role_filter', '').strip()
    query = User.query
    # Apply search filter
    if search:
        query = query.filter(
            db.or_(
                User.first_name.ilike(f"%{search}%"),
                User.last_name.ilike(f"%{search}%"),
            )
        )
    # Apply site filter
    if site_filter:
        query = query.filter(User.site_id == site_filter)
    # Apply role filter
    if role_filter:
        query = query.filter(User.role_id == role_filter)
    total = query.count()
    users = query.order_by(User.first_name.asc()).offset(offset).limit(per_page).all()
    # Fetch all sites and roles for the filter dropdowns
    sites = Site.query.order_by(Site.site_name.asc()).all()
    roles = Role.query.order_by(Role.role_name.asc()).all()
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')
    return render_template(
        'users.html',
        users=users,
        pagination=pagination,
        per_page=per_page,
        total=total,
        current_path=current_path,
        current_page_name=current_page_name,
        sites=sites,
        roles=roles,
        search=search,
        site_filter=site_filter,
        role_filter=role_filter
    )


# ****************** Add User Page *******************************
@routes_blueprint.route('/add_user', methods=['GET', 'POST'])
@login_required
def add_user():
    is_admin()  # Ensure only admins can access this route
    # Mapping paths to page names
    page_names = {'/add_user': 'Add User'}
    current_path = request.path
    current_page_name = page_names.get(current_path, 'Unknown Page')

    form = UserForm()
    form.role_id.choices = [(role.id, role.role_name) for role in Role.query.all()]
    form.site_id.choices = [(site.id, site.site_name) for site in Site.query.all()]
    if form.validate_on_submit():
        # Check if a user with the same email already exists
        _key = current_app.config['SECRET_KEY']
        existing_user = User.query.filter_by(email_hash=hash_email(form.email.data, _key)).first()
        if existing_user:
            flash('A user with this email already exists. Please use a different email.', 'danger')
            return render_template('add_user.html', form=form)
        # Validate password complexity
        password = form.password.data
        is_valid, error_message = validate_password(password)
        if not is_valid:
            flash(error_message, 'danger')
            return render_template('add_user.html', form=form)
        # Proceed with creating the new user
        hashed_password = generate_password_hash(form.password.data)
        new_user = User(
            first_name=form.first_name.data,
            middle_name=form.middle_name.data,
            last_name=form.last_name.data,
            email=form.email.data,
            status=form.status.data,
            rm_num=form.rm_num.data,
            site_id=form.site_id.data,
            role_id=form.role_id.data,
            password=hashed_password
        )
        db.session.add(new_user)
        db.session.commit()
        flash('User added successfully!', 'success')
        return redirect(url_for('routes.users'))
    return render_template('add_user.html', form=form,current_path=current_path,
        current_page_name=current_page_name)




# ****************** Edit User Page *******************************
# ****************** Send Temporary Password (AJAX) *******************************
@routes_blueprint.route('/send_temp_password/<int:user_id>', methods=['POST'])
@login_required
def send_temp_password(user_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    user = User.query.get_or_404(user_id)
    temp_password = secrets.token_urlsafe(12)

    try:
        send_temp_password_email(user, temp_password)
    except Exception:
        return jsonify({'success': False, 'message': 'Failed to send email. Check your SMTP configuration.'}), 500

    user.password = generate_password_hash(temp_password)
    user.must_change_password = True
    db.session.commit()

    return jsonify({'success': True, 'message': f'Temporary password sent to {user.email}'})



@routes_blueprint.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    # Ensure only admins and tech roles can access this route
    if not (current_user.is_admin or current_user.is_tech_role):
        abort(403)
    user = User.query.get_or_404(user_id)
    form = UserForm(obj=user)
    # Populate dynamic choices for role_id and site_id
    form.role_id.choices = [(role.id, role.role_name) for role in Role.query.all()]
    form.site_id.choices = [(site.id, site.site_name) for site in Site.query.all()]
    if form.validate_on_submit():
        # Check if a user with the same email already exists
        _key = current_app.config['SECRET_KEY']
        existing_user = User.query.filter(
            User.email_hash == hash_email(form.email.data, _key),
            User.id != user.id
        ).first()
        if existing_user:
            flash('A user with this email already exists. Please use a different email.', 'danger')
            return render_template('edit_user.html', form=form, user=user)
        # Track changes to avoid unnecessary updates
        changes_made = False
        # Update user details only if there are changes
        if user.first_name != form.first_name.data:
            user.first_name = form.first_name.data
            changes_made = True
        if user.middle_name != form.middle_name.data:
            user.middle_name = form.middle_name.data
            changes_made = True
        if user.last_name != form.last_name.data:
            user.last_name = form.last_name.data
            changes_made = True
        if user.email != form.email.data:
            user.email = form.email.data
            changes_made = True
        if user.status != form.status.data:
            user.status = form.status.data
            changes_made = True
        if user.rm_num != form.rm_num.data:
            user.rm_num = form.rm_num.data
            changes_made = True
        if user.site_id != form.site_id.data:
            user.site_id = form.site_id.data
            changes_made = True
        if user.role_id != form.role_id.data:
            user.role_id = form.role_id.data
            changes_made = True
        # Validate and update password only if provided
        password_changed = False
        if form.password.data:
            password = form.password.data
            is_valid, error_message = validate_password(password)
            if not is_valid:
                flash(error_message, 'danger')
                return render_template('edit_user.html', form=form, user=user)
            user.password = generate_password_hash(password)
            user.must_change_password = False
            changes_made = True
            password_changed = True
        # Commit changes only if any were made
        if changes_made:
            db.session.commit()
            if password_changed:
                send_password_updated_email(user)
            flash('User updated successfully!', 'success')
            return redirect(url_for('routes.users'))
        else:
            flash('No changes were made.', 'info')
    return render_template('edit_user.html', form=form, user=user)



# ****************** Delete User Page *******************************
@routes_blueprint.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    is_admin()  # Ensure only admins can access this route
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully!', 'warning')
    return redirect(url_for('routes.users'))



SITE_REQUIRED = ['site_name', 'site_acronyms', 'site_cds', 'site_code', 'site_address', 'site_type']

def _normalize_cds(raw):
    """Convert Excel scientific-notation CDS codes (e.g. '1.23457E+13') to integer strings."""
    raw = raw.strip()
    try:
        return str(int(float(raw)))
    except (ValueError, OverflowError):
        return raw


def _process_sites_rows(rows):
    """Upsert sites from a list of CSV dicts. Returns (added, updated). Raises ValueError on bad data."""
    added = updated = 0

    # Validate all rows first (no DB interaction)
    for i, row in enumerate(rows, start=2):
        missing = [f for f in SITE_REQUIRED if not row.get(f, '').strip()]
        if missing:
            raise ValueError(f'Row {i} is missing required fields: {", ".join(missing)}')

    # Pre-fetch all matching sites in one query to avoid mid-loop auto-flush
    names = [row['site_name'].strip() for row in rows]
    site_cache = {s.site_name: s for s in Site.query.filter(Site.site_name.in_(names)).all()}

    for row in rows:
        name = row['site_name'].strip()
        cds  = _normalize_cds(row['site_cds'])
        site = site_cache.get(name)
        if site:
            site.site_acronyms = row['site_acronyms'].strip()
            site.site_cds      = cds
            site.site_code     = row['site_code'].strip()
            site.site_address  = row['site_address'].strip()
            site.site_type     = row['site_type'].strip()
            updated += 1
        else:
            new_site = Site(
                site_name     = name,
                site_acronyms = row['site_acronyms'].strip(),
                site_cds      = cds,
                site_code     = row['site_code'].strip(),
                site_address  = row['site_address'].strip(),
                site_type     = row['site_type'].strip(),
            )
            db.session.add(new_site)
            site_cache[name] = new_site  # prevent duplicate inserts if name appears twice in CSV
            added += 1
    return added, updated


# ****************** Upload Users Page *******************************
@routes_blueprint.route('/bulk-data-upload', methods=['GET'])
@login_required
def upload_users():
    is_admin()
    log_page  = request.args.get('log_page', 1, type=int)
    per_page  = 10
    user_logs = BulkUploadLog.query.order_by(
        BulkUploadLog.uploaded_at.desc()
    ).paginate(page=log_page, per_page=per_page, error_out=False)
    org  = db.session.get(Organization, 1)
    ftp_host_plain     = ''
    ftp_username_plain = ''
    schedule_time = ''
    if org:
        key = current_app.config['SECRET_KEY']
        ftp_host_plain     = decrypt_mail_password(org.ftp_host_enc or '', key)
        ftp_username_plain = decrypt_mail_password(org.ftp_username_enc or '', key)
        if org.ftp_schedule_hour is not None:
            schedule_time = f"{org.ftp_schedule_hour:02d}:{org.ftp_schedule_minute or 0:02d}"
    return render_template('bulk_upload_data.html',
                           user_logs=user_logs,
                           org=org,
                           ftp_host_plain=ftp_host_plain,
                           ftp_username_plain=ftp_username_plain,
                           ftp_schedule_time=schedule_time,
                           current_page_name='Bulk Data Upload')


# ****************** Import Bulk Users *******************************
@routes_blueprint.route('/bulk-upload-users', methods=['POST'])
@login_required
def bulk_upload_users():
    is_admin()

    files = request.files.getlist('csvFile')
    files = [f for f in files if f and f.filename]
    if not files:
        flash('No file selected.', 'danger')
        return redirect(url_for('routes.upload_users'))

    for f in files:
        if not f.filename.lower().endswith('.csv'):
            flash(f'Invalid file: {f.filename}. Only .csv files are accepted.', 'danger')
            return redirect(url_for('routes.upload_users'))

    # Process sites.csv before users.csv
    files.sort(key=lambda f: (0 if f.filename.lower() == 'sites.csv' else 1))

    flash_messages = []

    for file in files:
        filename = secure_filename(file.filename)
        is_sites = filename.lower() == 'sites.csv'
        added = updated = total = 0

        try:
            stream = file.stream.read().decode('UTF-8')
            rows = list(csv.DictReader(stream.splitlines()))
            total = len(rows)

            if is_sites:
                added, updated = _process_sites_rows(rows)
                db.session.commit()
                db.session.add(BulkUploadLog(
                    filename=f'[Sites] {filename}',
                    uploaded_by_id=current_user.id,
                    total_records=total,
                    users_added=added,
                    users_updated=updated,
                    status='success'
                ))
                db.session.commit()
                flash_messages.append(f'Sites: {added} added, {updated} updated.')
            else:
                # Build site lookup cache and validate all rows
                csv_emails = set()
                site_cache = {}
                for row in rows:
                    if not all([row.get('first_name'), row.get('last_name'), row.get('email'),
                                row.get('role_id'), row.get('site_name'), row.get('rm_num')]):
                        raise ValueError('Some rows in the CSV file are missing required fields.')
                    name = row['site_name'].strip()
                    if name not in site_cache:
                        site = Site.query.filter_by(site_name=name).first()
                        if not site:
                            raise ValueError(f"Site '{name}' not found. Please verify the CSV file.")
                        site_cache[name] = site.id
                    csv_emails.add(row['email'].strip())

                # Upsert users
                _bulk_key = current_app.config['SECRET_KEY']
                for row in rows:
                    site_id = site_cache[row['site_name'].strip()]
                    existing_user = User.query.filter_by(email_hash=hash_email(row['email'].strip(), _bulk_key)).first()
                    if existing_user:
                        existing_user.first_name  = row['first_name']
                        existing_user.middle_name = row.get('middle_name') or None
                        existing_user.last_name   = row['last_name']
                        existing_user.rm_num      = row.get('rm_num') or existing_user.rm_num
                        existing_user.role_id     = int(row['role_id'])
                        existing_user.site_id     = site_id
                        existing_user.status      = row.get('status') or 'Active'
                        updated += 1
                    else:
                        db.session.add(User(
                            first_name=row['first_name'],
                            middle_name=row.get('middle_name') or None,
                            last_name=row['last_name'],
                            email=row['email'].strip(),
                            status=row.get('status') or 'Active',
                            password=generate_password_hash(secrets.token_urlsafe(16)),
                            must_change_password=True,
                            rm_num=row.get('rm_num') or None,
                            role_id=int(row['role_id']),
                            site_id=site_id
                        ))
                        added += 1

                # Flush pending inserts/updates, then deactivate absent users
                db.session.flush()
                csv_email_hashes = {hash_email(e, _bulk_key) for e in csv_emails}
                deactivated = User.query.filter(
                    User.status == 'Active',
                    ~User.email_hash.in_(csv_email_hashes)
                ).update({'status': 'Inactive'}, synchronize_session=False)

                db.session.commit()
                db.session.add(BulkUploadLog(
                    filename=filename,
                    uploaded_by_id=current_user.id,
                    total_records=total,
                    users_added=added,
                    users_updated=updated,
                    status='success'
                ))
                db.session.commit()
                msg = f'Users: {added} added, {updated} updated.'
                if deactivated:
                    msg += f' {deactivated} marked Inactive (not in file).'
                flash_messages.append(msg)

        except ValueError as e:
            db.session.rollback()
            db.session.add(BulkUploadLog(
                filename=f'[Sites] {filename}' if is_sites else filename,
                uploaded_by_id=current_user.id,
                total_records=total,
                users_added=added,
                users_updated=updated,
                status='error',
                error_message=str(e)
            ))
            db.session.commit()
            flash(f'Error processing {filename}: {e}', 'danger')
            return redirect(url_for('routes.upload_users'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Bulk upload failed for {filename}: {e}", exc_info=True)
            db.session.add(BulkUploadLog(
                filename=f'[Sites] {filename}' if is_sites else filename,
                uploaded_by_id=current_user.id,
                total_records=total,
                users_added=added,
                users_updated=updated,
                status='error',
                error_message=str(e)
            ))
            db.session.commit()
            flash(f'An unexpected error occurred while processing {filename}.', 'danger')
            return redirect(url_for('routes.upload_users'))

    if flash_messages:
        flash(' | '.join(flash_messages), 'success')

    return redirect(url_for('routes.upload_users'))


# ****************** FTP Bulk Upload Users *******************************
@routes_blueprint.route('/ftp-settings/save', methods=['POST'])
@login_required
def ftp_save_settings():
    """Save FTP credentials and schedule settings into the Organization record."""
    is_admin()
    org = Organization.query.get_or_404(1)
    key = current_app.config['SECRET_KEY']

    # --- Credentials ---
    raw_host = re.sub(r'^ftps?://', '', request.form.get('ftp_host', '').strip(), flags=re.IGNORECASE)
    username = request.form.get('ftp_username', '').strip()
    password = request.form.get('ftp_password', '').strip()
    if raw_host:
        org.ftp_host_enc = encrypt_mail_password(raw_host, key)
    if username:
        org.ftp_username_enc = encrypt_mail_password(username, key)
    if password:
        org.ftp_password_enc = encrypt_mail_password(password, key)
    org.ftp_port    = int(request.form.get('ftp_port') or 21)
    org.ftp_path    = request.form.get('ftp_path', '').strip() or None
    org.ftp_use_tls = request.form.get('ftp_use_tls') == 'on'

    # --- Schedule ---
    schedule_enabled = request.form.get('ftp_schedule_enabled') == 'on'
    org.ftp_schedule_enabled = schedule_enabled
    if schedule_enabled:
        schedule_time = (request.form.get('ftp_schedule_time') or '00:00').strip()
        try:
            hour, minute = map(int, schedule_time.split(':'))
        except ValueError:
            hour, minute = 0, 0
        days_list = request.form.getlist('ftp_schedule_days')
        all_days  = {'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'}
        org.ftp_schedule_hour   = hour
        org.ftp_schedule_minute = minute
        org.ftp_schedule_days   = '*' if not days_list or set(days_list) >= all_days else ','.join(days_list)

    from datetime import date as _date
    for attr, field in [('ftp_schedule_start_date', 'ftp_schedule_start_date'),
                        ('ftp_schedule_stop_date',  'ftp_schedule_stop_date')]:
        raw = request.form.get(field, '').strip()
        try:
            setattr(org, attr, _date.fromisoformat(raw) if raw else None)
        except ValueError:
            setattr(org, attr, None)

    db.session.add(org)
    db.session.commit()

    # Sync APScheduler job (non-fatal if scheduler unavailable)
    try:
        from application.scheduled_jobs import run_org_ftp_schedule
        if schedule_enabled and org.ftp_schedule_hour is not None:
            scheduler.add_job(
                id='org_ftp_schedule',
                func=run_org_ftp_schedule,
                trigger='cron',
                day_of_week=org.ftp_schedule_days,
                hour=org.ftp_schedule_hour,
                minute=org.ftp_schedule_minute,
                replace_existing=True
            )
        else:
            try:
                scheduler.remove_job('org_ftp_schedule')
            except Exception:
                pass
    except Exception:
        pass

    if schedule_enabled:
        flash('FTP settings and schedule saved.', 'success')
    else:
        flash('FTP settings saved. Schedule disabled.', 'success')

    return redirect(url_for('routes.upload_users') + '?tab=ftp')


@routes_blueprint.route('/ftp-upload-users', methods=['POST'])
@login_required
def ftp_bulk_upload_users():
    is_admin()

    ftp_host     = re.sub(r'^ftps?://', '', request.form.get('ftp_host', '').strip(), flags=re.IGNORECASE)
    ftp_port     = request.form.get('ftp_port', '21').strip()
    ftp_username = request.form.get('ftp_username', '').strip()
    ftp_path     = request.form.get('ftp_path', '').strip()
    use_tls      = request.form.get('ftp_use_tls') == 'on'
    ftp_password = request.form.get('ftp_password', '').strip()

    # Fall back to saved org credentials (decrypt) if form fields are blank
    org = db.session.get(Organization, 1)
    if org:
        key = current_app.config['SECRET_KEY']
        if not ftp_host and org.ftp_host_enc:
            ftp_host = decrypt_mail_password(org.ftp_host_enc, key)
        if not ftp_username and org.ftp_username_enc:
            ftp_username = decrypt_mail_password(org.ftp_username_enc, key)
        if not ftp_password and org.ftp_password_enc:
            ftp_password = decrypt_mail_password(org.ftp_password_enc, key)
        ftp_path = ftp_path or (org.ftp_path or '')
        ftp_port = ftp_port or str(org.ftp_port or 21)
        use_tls  = use_tls  or bool(org.ftp_use_tls)

    if not all([ftp_host, ftp_username, ftp_path]):
        flash('FTP host, username, and remote directory are required.', 'danger')
        return redirect(url_for('routes.upload_users') + '?tab=ftp')

    try:
        port = int(ftp_port)
    except ValueError:
        flash('FTP port must be a valid number.', 'danger')
        return redirect(url_for('routes.upload_users') + '?tab=ftp')

    # Normalise: if the stored path still has a .csv filename (old format), strip it
    if ftp_path.lower().endswith('.csv'):
        import posixpath as _pp
        ftp_path = _pp.dirname(ftp_path)
    ftp_dir = ftp_path.rstrip('/')
    users_path = f'{ftp_dir}/users.csv'
    sites_path = f'{ftp_dir}/sites.csv'

    users_added = users_updated = total_records = 0
    sites_added = sites_updated = sites_total = 0

    try:
        ftp = ftplib.FTP_TLS() if use_tls else ftplib.FTP()
        ftp.connect(ftp_host, port, timeout=30)
        ftp.login(ftp_username, ftp_password)
        if use_tls:
            ftp.prot_p()

        # --- Download and process sites.csv first ---
        sites_buf = io.BytesIO()
        try:
            ftp.retrbinary(f'RETR {sites_path}', sites_buf.write)
            sites_buf.seek(0)
            site_rows   = list(csv.DictReader(sites_buf.read().decode('utf-8').splitlines()))
            sites_total = len(site_rows)
            sites_added, sites_updated = _process_sites_rows(site_rows)
            db.session.commit()
            db.session.add(BulkUploadLog(
                filename='[FTP Sites] sites.csv',
                uploaded_by_id=current_user.id,
                total_records=sites_total,
                users_added=sites_added,
                users_updated=sites_updated,
                status='success'
            ))
            db.session.commit()
        except ftplib.error_perm:
            pass  # sites.csv not found on server — skip silently

        # --- Download and process users.csv ---
        user_buf = io.BytesIO()
        ftp.retrbinary(f'RETR {users_path}', user_buf.write)
        ftp.quit()

        user_buf.seek(0)
        rows = list(csv.DictReader(user_buf.read().decode('UTF-8').splitlines()))
        total_records = len(rows)

        # First pass: validate all rows and collect emails
        csv_emails = set()
        for row in rows:
            if not all([row.get('first_name'), row.get('last_name'), row.get('email'),
                        row.get('role_id'), row.get('site_name'), row.get('rm_num')]):
                raise ValueError('Some rows in the CSV file are missing required fields.')
            site = Site.query.filter_by(site_name=row['site_name']).first()
            if not site:
                raise ValueError(f"Site '{row['site_name']}' not found. Please verify the CSV file.")
            csv_emails.add(row['email'].strip().lower())

        # Second pass: upsert users
        for row in rows:
            site = Site.query.filter_by(site_name=row['site_name']).first()
            existing_user = User.query.filter_by(email_hash=hash_email(row['email'].strip(), key)).first()
            if existing_user:
                existing_user.first_name  = row['first_name']
                existing_user.middle_name = row.get('middle_name') or None
                existing_user.last_name   = row['last_name']
                existing_user.rm_num      = row.get('rm_num') or existing_user.rm_num
                existing_user.role_id     = int(row['role_id'])
                existing_user.site_id     = site.id
                existing_user.status      = row.get('status') or 'Active'
                users_updated += 1
            else:
                db.session.add(User(
                    first_name=row['first_name'],
                    middle_name=row.get('middle_name', None),
                    last_name=row['last_name'],
                    email=row['email'].strip(),
                    status=row.get('status', 'Active'),
                    password=generate_password_hash(secrets.token_urlsafe(16)),
                    must_change_password=True,
                    rm_num=row.get('rm_num', None),
                    role_id=row['role_id'],
                    site_id=site.id
                ))
                users_added += 1

        # Third pass: deactivate users absent from the CSV
        users_deactivated = 0
        ftp_csv_hashes = {hash_email(e, key) for e in csv_emails}
        for user in User.query.filter(User.status == 'Active').all():
            if user.email_hash not in ftp_csv_hashes:
                user.status = 'Inactive'
                users_deactivated += 1

        db.session.commit()

        db.session.add(BulkUploadLog(
            filename='[FTP] users.csv',
            uploaded_by_id=current_user.id,
            total_records=total_records,
            users_added=users_added,
            users_updated=users_updated,
            status='success'
        ))
        db.session.commit()

        msg = f'FTP import successful: {users_added} users added, {users_updated} updated.'
        if users_deactivated:
            msg += f' {users_deactivated} marked Inactive (not in file).'
        if sites_total:
            msg += f' Sites: {sites_added} added, {sites_updated} updated.'
        flash(msg, 'success')

    except (ftplib.Error, OSError, EOFError, UnicodeDecodeError, ValueError) as e:
        db.session.rollback()
        if isinstance(e, socket.gaierror):
            friendly = f"Cannot reach FTP host '{ftp_host}'. Check that the hostname is correct and the server is reachable."
        elif isinstance(e, ConnectionRefusedError):
            friendly = f"Connection refused by '{ftp_host}:{port}'. Check the port number and that the FTP service is running."
        elif isinstance(e, TimeoutError):
            friendly = f"Connection to '{ftp_host}' timed out. The server may be down or blocked by a firewall."
        elif isinstance(e, ftplib.error_perm):
            msg_lower = str(e)
            if any(code in msg_lower for code in ('530', '331', '332')):
                friendly = 'FTP login failed. Check your username and password.'
            else:
                friendly = f'FTP error: {e}'
        else:
            friendly = str(e)
        try:
            db.session.add(BulkUploadLog(
                filename='[FTP] users.csv',
                uploaded_by_id=current_user.id,
                total_records=total_records,
                users_added=users_added,
                users_updated=users_updated,
                status='error',
                error_message=friendly
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(friendly, 'danger')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'FTP bulk upload unexpected error: {e}', exc_info=True)
        flash('An unexpected error occurred during the FTP import.', 'danger')

    return redirect(url_for('routes.upload_users'))


# ****************** Bulk Upload Sites (CSV) *******************************
@routes_blueprint.route('/bulk-upload-sites', methods=['POST'])
@login_required
def bulk_upload_sites():
    is_admin()

    if 'csvFile' not in request.files:
        flash('No file selected.', 'danger')
        return redirect(url_for('routes.upload_users') + '?tab=sites')

    file = request.files['csvFile']
    if not file or file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('routes.upload_users') + '?tab=sites')

    if not file.filename.lower().endswith('.csv'):
        flash('Invalid file format. Please upload a CSV file.', 'danger')
        return redirect(url_for('routes.upload_users') + '?tab=sites')

    sites_added = sites_updated = total_records = 0
    filename = secure_filename(file.filename)

    try:
        stream = file.read().decode('utf-8')
        rows = list(csv.DictReader(stream.splitlines()))
        total_records = len(rows)
        if total_records == 0:
            flash('The CSV file is empty.', 'warning')
            return redirect(url_for('routes.upload_users') + '?tab=sites')

        sites_added, sites_updated = _process_sites_rows(rows)
        db.session.commit()

        db.session.add(BulkUploadLog(
            filename=f'[Sites] {filename}',
            uploaded_by_id=current_user.id,
            total_records=total_records,
            users_added=sites_added,
            users_updated=sites_updated,
            status='success'
        ))
        db.session.commit()
        flash(f'Sites import successful: {sites_added} added, {sites_updated} updated.', 'success')

    except UnicodeDecodeError as e:
        db.session.rollback()
        current_app.logger.error(f"Sites CSV encoding error for {filename}: {e}", exc_info=True)
        db.session.add(BulkUploadLog(
            filename=f'[Sites] {filename}',
            uploaded_by_id=current_user.id,
            total_records=total_records,
            users_added=sites_added,
            users_updated=sites_updated,
            status='error',
            error_message=str(e)
        ))
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash('Sites import failed: file encoding not supported. Please save the CSV as UTF-8.', 'danger')

    except ValueError as e:
        db.session.rollback()
        db.session.add(BulkUploadLog(
            filename=f'[Sites] {filename}',
            uploaded_by_id=current_user.id,
            total_records=total_records,
            users_added=sites_added,
            users_updated=sites_updated,
            status='error',
            error_message=str(e)
        ))
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(f'Sites import failed: {e}', 'danger')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Bulk upload sites unexpected error: {e}', exc_info=True)
        flash('An unexpected error occurred during the sites import.', 'danger')

    return redirect(url_for('routes.upload_users') + '?tab=sites')


# *********************************************************************
# ****************** Role Management Page *******************************
@routes_blueprint.route('/roles')
@login_required
def roles():
        # Mapping paths to page names
    page_names = {'/roles': 'Manage User Roles'}
    current_path = request.path
    current_page_name = page_names.get(current_path, 'Unknown Page')
    is_admin()  # Ensure only admins can access this route
    # Get the page number and per_page from the query parameters, default to 10 for per_page
    page, per_page, offset = get_page_args(page_parameter="page", per_page_parameter="per_page")
    # Query the users
    total = Role.query.count()
    roles = Role.query.order_by(Role.id.asc()).offset(offset).limit(per_page).all()    
    # Set up pagination with Bootstrap 5 styling
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')
    return render_template('roles.html', roles=roles, pagination=pagination, per_page=per_page, total=total, 
        current_path=current_path, 
        current_page_name=current_page_name
    )

# ****************** Add New Role Page *******************************
@routes_blueprint.route('/add_role', methods=['GET', 'POST'])
@login_required
def add_role():
            # Mapping paths to page names
    page_names = {'/add_role': 'New Role'}
    current_path = request.path
    current_page_name = page_names.get(current_path, 'Unknown Page')
    is_admin()  # Ensure only admins can access this route
    form = RoleForm()
    if form.validate_on_submit():
        # Check if a role with the same name already exists
        existing_role = Role.query.filter_by(role_name=form.role_name.data).first()
        if existing_role:
            flash('This role already exists.', 'danger')
            return render_template('add_role.html', form=form)  # Re-render form with the error message
        # Create and add the new role
        new_role = Role(
            role_name=form.role_name.data
        )
        db.session.add(new_role)
        db.session.commit()
        flash('Role added successfully!', 'success')
        return redirect(url_for('routes.roles'))
    return render_template('add_role.html', form=form,
        current_path=current_path, 
        current_page_name=current_page_name)

# ****************** Edit Role Page *******************************
@routes_blueprint.route('/edit_role/<int:role_id>', methods=['GET', 'POST'])
@login_required
def edit_role(role_id):
    is_admin()  # Ensure only admins can access this route
    
    # Restrict editing roles with IDs 1, 2, 3, 4, 5
    if role_id in {1, 2, 3, 4, 5}:
        flash('You are not allowed to edit this role.', 'danger')
        return redirect(url_for('routes.roles'))

    role = Role.query.get_or_404(role_id)
    form = RoleForm(obj=role)
    if form.validate_on_submit():
        # Check for duplicate entries
        existing_role = Role.query.filter(Role.role_name == form.role_name.data, Role.id != role.id).first()
        if existing_role:
            flash('This role already exists.', 'danger')
            return render_template('add_role.html', form=form)  # Re-render form with the error message
        # Check if there are any changes to the form
        if (
            role.role_name == form.role_name.data
        ):
            flash('No changes were made.', 'info')
            return render_template('edit_role.html', form=form, role=role)
        role.role_name = form.role_name.data
        db.session.commit()
        flash('Role updated successfully!', 'success')
        return redirect(url_for('routes.roles'))
    return render_template('edit_role.html', form=form, role=role)


# ****************** Delete Role Page *******************************
@routes_blueprint.route('/delete_role/<int:role_id>', methods=['POST'])
@login_required
def delete_role(role_id):
    is_admin()  # Ensure only admins can access this route

    # Restrict deleting roles with IDs 1, 2, 3, 4, 5
    if role_id in {1, 2, 3, 4, 5}:
        flash('You are not allowed to delete this role.', 'danger')
        return redirect(url_for('routes.roles'))
    
    role = Role.query.get_or_404(role_id)
    db.session.delete(role)
    db.session.commit()
    flash('Role deleted successfully!', 'warning')
    return redirect(url_for('routes.roles'))


# *********************************************************************
# ****************** Site Management Page *******************************
@routes_blueprint.route('/sites', methods=['GET'])
@login_required
def sites():
        # Mapping paths to page names
    page_names = {'/sites': 'Manage Sites'}
    current_path = request.path
    current_page_name = page_names.get(current_path, 'Unknown Page')
    is_admin()  # Ensure only admins can access this route
    # Get the page number and per_page from the query parameters, default to 10 for per_page
    page, per_page, offset = get_page_args(page_parameter="page", per_page_parameter="per_page")
    # Query the users
    total = Site.query.count()
    sites = Site.query.order_by(Site.id.asc()).offset(offset).limit(per_page).all()
    # Set up pagination with Bootstrap 5 styling
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')
    return render_template('sites.html', sites=sites, pagination=pagination, per_page=per_page, total=total, 
        current_path=current_path, 
        current_page_name=current_page_name
    )

# ****************** Add New Site Page *******************************
@routes_blueprint.route('/add_site', methods=['GET', 'POST'])
@login_required
def add_site():
            # Mapping paths to page names
    page_names = {'/add_site': 'New Site'}
    current_path = request.path
    current_page_name = page_names.get(current_path, 'Unknown Page')
    is_admin()  # Ensure only admins can access this route
    form = SiteForm()
    if form.validate_on_submit():
        # Check if a role with the same name already exists
        existing_site = Site.query.filter_by(site_cds=form.site_cds.data).first()
        if existing_site:
            flash('This site already exists.', 'danger')
            return render_template('add_site.html', form=form)  # Re-render form with the error message
        new_site = Site(
            site_name=form.site_name.data,
            site_acronyms=form.site_acronyms.data,
            site_code=form.site_code.data,
            site_cds=form.site_cds.data,
            site_address=form.site_address.data,
            site_type=form.site_type.data 
        )
        db.session.add(new_site)
        db.session.commit()
        flash('Site added successfully!', 'success')
        return redirect(url_for('routes.sites'))
    # Pass None for site to differentiate between add and edit
    return render_template('add_site.html', form=form,
        current_path=current_path, 
        current_page_name=current_page_name
    )


# ****************** Edit Site Page *******************************
@routes_blueprint.route('/edit_site/<int:site_id>', methods=['GET', 'POST'])
@login_required
def edit_site(site_id):
    is_admin()  # Ensure only admins can access this route
    site = Site.query.get_or_404(site_id)
    form = SiteForm(obj=site)
    if form.validate_on_submit():
        # Check if a role with the same name already exists
        existing_site = Site.query.filter(Site.site_cds == form.site_cds.data, Site.id != site.id).first()
        if existing_site:
            flash('This site already exists.', 'danger')
            return render_template('add_site.html', form=form)  # Re-render form with the error message
        # Check if there are any changes to the form
        if (
            site.site_name == form.site_name.data and
            site.site_acronyms == form.site_acronyms.data and
            site.site_code == form.site_code.data and
            site.site_cds == form.site_cds.data and
            site.site_address == form.site_address.data and
            site.site_type == form.site_type.data
        ):
            flash('No changes were made.', 'info')
            return render_template('edit_site.html', form=form, site=site)
        site.site_name = form.site_name.data
        site.site_acronyms = form.site_acronyms.data
        site.site_code = form.site_code.data
        site.site_cds = form.site_cds.data
        site.site_address = form.site_address.data
        site.site_type = form.site_type.data
        db.session.commit()
        flash('Site updated successfully!', 'success')
        return redirect(url_for('routes.sites'))
    return render_template('edit_site.html', form=form, site=site)

# ****************** Delete Site Page *******************************
@routes_blueprint.route('/delete_site/<int:site_id>', methods=['POST'])
@login_required
def delete_site(site_id):
    is_admin()  # Ensure only admins can access this route
    site = Site.query.get_or_404(site_id)
    db.session.delete(site)
    db.session.commit()
    flash('Site deleted successfully!', 'warning')
    return redirect(url_for('routes.sites'))


# *********************************************************************
# ****************** Notification Management Page *********************
@routes_blueprint.route('/notifications', methods=['GET'])
@login_required
def notifications():
        # Mapping paths to page names
    page_names = {'/notifications': 'Manage Notifications'}
    current_path = request.path
    current_page_name = page_names.get(current_path, 'Unknown Page')
    is_admin()  # Ensure only admins can access this route
    # Get the page number and per_page from the query parameters, default to 10 for per_page
    page, per_page, offset = get_page_args(page_parameter="page", per_page_parameter="per_page")
    # Query the users
    total = Notification.query.count()
    notifications = Notification.query.offset(offset).limit(per_page).all()
    # Set up pagination with Bootstrap 5 styling
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')
    return render_template('notifications.html', notifications=notifications, pagination=pagination, per_page=per_page, total=total, 
        current_path=current_path, 
        current_page_name=current_page_name
    )

# ****************** Add New Notification *********************
@routes_blueprint.route('/add_notification', methods=['GET', 'POST'])
@login_required
def add_notification():
    page_names = {'/add_notification': 'New Notification'}
    current_path = request.path
    current_page_name = page_names.get(current_path, 'Unknown Page')
    is_admin()  # Ensure only admins can access this route
    form = NotificationForm()
    if form.validate_on_submit():
        # Check if a notification with the same name already exists
        existing_notification = Notification.query.filter_by(msg_name=form.msg_name.data).first()
        if existing_notification:
            flash('This notification name already exists.', 'danger')
            return render_template('add_notification.html', form=form)  # Re-render form with the error message
        new_notification = Notification(
            msg_name=form.msg_name.data,
            msg_content=form.msg_content.data,
            msg_status="Inactive"
        )
        db.session.add(new_notification)
        db.session.commit()
        flash('Notification added successfully!', 'success')
        return redirect(url_for('routes.notifications'))
    # Pass None for notification to differentiate between add and edit
    return render_template('add_notification.html', form=form,
        current_path=current_path, 
        current_page_name=current_page_name
    )


# ****************** Edit Notification Page *********************
@routes_blueprint.route('/edit_notification/<int:notification_id>', methods=['GET', 'POST'])
@login_required
def edit_notification(notification_id):
    is_admin()  # Ensure only admins can access this route
    notification = Notification.query.get_or_404(notification_id)
    form = NotificationForm(obj=notification)

    if request.method == 'POST':
        # Capture original values before any mutation
        orig_name    = notification.msg_name
        orig_content = notification.msg_content
        orig_status  = notification.msg_status

        # Determine new status from checkbox
        new_status = 'Active' if request.form.get('msg_status') else 'Inactive'

        # Check for duplicate notification name
        existing_notification = Notification.query.filter(
            Notification.msg_name == form.msg_name.data,
            Notification.id != notification.id
        ).first()
        if existing_notification:
            flash('This notification name already exists.', 'danger')
            return render_template('edit_notification.html', form=form, notification=notification)

        # Check if no changes were made
        if (
            orig_name    == form.msg_name.data and
            orig_content == form.msg_content.data and
            orig_status  == new_status
        ):
            flash('No changes were made.', 'info')
            return render_template('edit_notification.html', form=form, notification=notification)

        # Enforce only one active notification
        if new_status == 'Active':
            active_notification = Notification.query.filter_by(msg_status='Active').first()
            if active_notification and active_notification.id != notification.id:
                flash('Only one notification can be active at a time. Please deactivate the current notification before activating a new one. ', 'danger')
                return render_template('edit_notification.html', form=form, notification=notification)

        # Update and save changes
        notification.msg_name    = form.msg_name.data
        notification.msg_content = form.msg_content.data
        notification.msg_status  = new_status
        db.session.commit()
        flash('Notification updated successfully!', 'success')
        return redirect(url_for('routes.notifications'))

    return render_template('edit_notification.html', form=form, notification=notification)



# ****************** Toggle Notification Status *********************
@routes_blueprint.route('/toggle_notification/<int:notification_id>', methods=['POST'])
@login_required
def toggle_notification(notification_id):
    is_admin()
    notification = Notification.query.get_or_404(notification_id)
    if notification.msg_status == 'Active':
        notification.msg_status = 'Inactive'
    else:
        # Deactivate all others first, then activate this one
        Notification.query.filter(Notification.id != notification_id).update({'msg_status': 'Inactive'})
        notification.msg_status = 'Active'
    db.session.commit()
    return redirect(url_for('routes.notifications'))


# ****************** Delete Notification Page *********************
@routes_blueprint.route('/delete_notification/<int:notification_id>', methods=['POST'])
@login_required
def delete_notification(notification_id):
    is_admin()  # Ensure only admins can access this route
    notification = Notification.query.get_or_404(notification_id)
    db.session.delete(notification)
    db.session.commit()
    flash('Notification deleted successfully!', 'warning')
    return redirect(url_for('routes.notifications'))


_GRADE_LIST = ['TK', 'KN', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12']


# =============================================================================
# STUDENTS
# =============================================================================

@routes_blueprint.route('/students', methods=['GET'])
@login_required
def students():
    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page')
    search          = request.args.get('search', '').strip()
    _url_site       = request.args.get('site_filter', '').strip()
    site_filter     = _url_site if _url_site else session.get('active_site_filter', '')
    grade_filter    = request.args.get('grade_filter', '').strip()
    subgroups       = [s.strip() for s in request.args.getlist('subgroup') if s.strip()]
    english_status  = [s.strip() for s in request.args.getlist('english_status') if s.strip()]
    gender_filters  = [s.strip() for s in request.args.getlist('gender') if s.strip()]
    status_filter   = session.get('active_status_filter', 'active')
    schoolyr_filter = session.get('active_schoolyr', '')
    today           = datetime.now().date()

    _SUBGROUP_LABELS = {
        'homeless': 'Homeless / Dwelling',
        'frm':      'Free / Reduced Meal',
        'swd':      'Students with Disability',
        'no_ssid':  'Missing SSID',
        'foster':   'Foster Youth',
        'migrant':  'Migrant',
        'sed504':   '504 Plan',
    }

    query = Student.query
    if status_filter == 'active':
        query = query.filter(
            db.or_(Student.enter_date.is_(None), Student.enter_date <= today),
            db.or_(Student.exit_date.is_(None),  Student.exit_date  >= today),
        )
    elif status_filter == 'inactive':
        query = query.filter(
            Student.exit_date.isnot(None),
            Student.exit_date < today,
        )
    if search:
        query = query.filter(
            db.or_(Student.first_name.ilike(f'%{search}%'),
                   Student.last_name.ilike(f'%{search}%'),
                   Student.student_id.ilike(f'%{search}%'))
        )
    if site_filter:
        query = query.filter(Student.site_id == site_filter)
    if grade_filter:
        query = query.filter(Student.grade == grade_filter)
    if subgroups:
        _sg_conditions = {
            'homeless': db.and_(Student.dwelling.isnot(None), Student.dwelling != ''),
            'frm':      Student.frm_code.in_(['F', 'R']),
            'swd':      db.and_(Student.disability.isnot(None), Student.disability != ''),
            'foster':   Student.foster == True,
            'migrant':  Student.migrant == True,
            'sed504':   Student.sed504 == True,
            'no_ssid':  db.or_(Student.ssid.is_(None), Student.ssid == ''),
        }
        conditions = [_sg_conditions[sg] for sg in subgroups if sg in _sg_conditions]
        if conditions:
            query = query.filter(db.and_(*conditions))
    ethnicity_filter = request.args.get('ethnicity', '').strip()
    if english_status:
        query = query.filter(Student.english_status.in_(english_status))
    if ethnicity_filter:
        query = query.filter(Student.ethnicity == ethnicity_filter)
    if gender_filters:
        query = query.filter(Student.gender.in_(gender_filters))
    if schoolyr_filter:
        query = query.filter(Student.schoolyr == schoolyr_filter)

    subgroup_label = ' + '.join(_SUBGROUP_LABELS[sg] for sg in subgroups if sg in _SUBGROUP_LABELS)
    if english_status:
        subgroup_label = (subgroup_label + ' · ' if subgroup_label else '') + 'English Status: ' + ', '.join(english_status)

    total      = query.count()
    students_q = query.order_by(Student.last_name.asc(), Student.first_name.asc()).offset(offset).limit(per_page).all()
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')
    sites = Site.query.order_by(Site.site_name.asc()).all()

    return render_template('students.html',
        students=students_q, pagination=pagination, per_page=per_page,
        total=total, sites=sites, grades=_GRADE_LIST,
        current_page_name='Students',
        subgroups=subgroups, english_status=english_status, gender_filters=gender_filters, subgroup_label=subgroup_label,
        schoolyr_filter=schoolyr_filter)


@routes_blueprint.route('/students/export/csv')
@login_required
def students_export_csv():
    import csv, io
    search          = request.args.get('search', '').strip()
    site_filter     = session.get('active_site_filter', '')
    grade_filter    = request.args.get('grade_filter', '').strip()
    subgroups       = [s.strip() for s in request.args.getlist('subgroup') if s.strip()]
    english_status  = request.args.get('english_status', '').strip()
    status_filter   = session.get('active_status_filter', 'active')
    schoolyr_filter = session.get('active_schoolyr', '')
    today           = datetime.now().date()

    query = Student.query
    if status_filter == 'active':
        query = query.filter(
            db.or_(Student.enter_date.is_(None), Student.enter_date <= today),
            db.or_(Student.exit_date.is_(None),  Student.exit_date  >= today),
        )
    elif status_filter == 'inactive':
        query = query.filter(Student.exit_date.isnot(None), Student.exit_date < today)
    if search:
        query = query.filter(db.or_(
            Student.first_name.ilike(f'%{search}%'),
            Student.last_name.ilike(f'%{search}%'),
            Student.student_id.ilike(f'%{search}%'),
        ))
    if site_filter:
        query = query.filter(Student.site_id == site_filter)
    if grade_filter:
        query = query.filter(Student.grade == grade_filter)
    if subgroups:
        _sg = {
            'homeless': db.and_(Student.dwelling.isnot(None), Student.dwelling != ''),
            'frm':      Student.frm_code.in_(['F', 'R']),
            'swd':      db.and_(Student.disability.isnot(None), Student.disability != ''),
            'foster':   Student.foster == True,
            'migrant':  Student.migrant == True,
            'sed504':   Student.sed504 == True,
            'no_ssid':  db.or_(Student.ssid.is_(None), Student.ssid == ''),
        }
        conditions = [_sg[s] for s in subgroups if s in _sg]
        if conditions:
            query = query.filter(db.and_(*conditions))
    if english_status:
        query = query.filter(Student.english_status == english_status)
    if schoolyr_filter:
        query = query.filter(Student.schoolyr == schoolyr_filter)

    _eth = {'100':'Native American','200':'Asian','300':'Pacific Islander','400':'Filipino',
            '500':'Hispanic/Latino','600':'African American','700':'White','900':'Two or More Races'}
    _gen = {'M':'Male','F':'Female','X':'Non-Binary','U':'Unknown'}
    _frm = {'F':'Free','R':'Reduced','P':'Paid'}
    _el  = {'EO':'English Only','EL':'English Learner','IFEP':'IFEP','RFEP':'RFEP','TBD':'TBD'}

    rows = query.order_by(Student.last_name, Student.first_name).all()
    out  = io.StringIO()
    w    = csv.writer(out)
    w.writerow(['Last Name','First Name','Middle Name','Student ID','SSID','Grade','Gender',
                'Date of Birth','Grad Year','Ethnicity','English Status','FRM','Disability',
                'Foster','Migrant','Homeless','504 Plan','Site','School Year','Status'])
    for s in rows:
        w.writerow([
            s.last_name, s.first_name, s.middle_name or '',
            s.student_id, s.ssid or '', s.grade,
            _gen.get(s.gender, s.gender or ''),
            s.date_of_birth or '', s.gradyr or '',
            _eth.get(s.ethnicity, s.ethnicity or ''),
            _el.get(s.english_status, s.english_status or ''),
            _frm.get(s.frm_code, s.frm_code or ''),
            s.disability or '',
            'Yes' if s.foster  else 'No',
            'Yes' if s.migrant else 'No',
            'Yes' if s.dwelling else 'No',
            'Yes' if s.sed504  else 'No',
            s.site.site_name, s.schoolyr or '', s.status,
        ])
    resp = make_response(out.getvalue())
    resp.headers['Content-Disposition'] = 'attachment; filename=students_export.csv'
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    return resp


@routes_blueprint.route('/add_student', methods=['GET', 'POST'])
@login_required
def add_student():
    return redirect(url_for('routes.students'))


@routes_blueprint.route('/student/<int:student_id>', methods=['GET'])
@login_required
def student_details(student_id):
    student = Student.query.get_or_404(student_id)
    student_absences = (Absence.query
                               .filter(Absence.ssid == student.ssid)
                               .order_by(Absence.school_yr.desc(), Absence.abs_date.desc())
                               .all()) if student.ssid else []
    student_incidents = (Incident.query
                                 .filter(Incident.sisid == student.ssid)
                                 .order_by(Incident.incident_date.desc())
                                 .all()) if student.ssid else []
    student_grade_records = (Grade.query
                                   .filter(Grade.grades_stuid == student.student_id)
                                   .order_by(Grade.grades_courseyr.desc(), Grade.grades_term, Grade.grades_coursenum)
                                   .all())
    return render_template('student_details.html', student=student,
                           student_absences=student_absences,
                           student_incidents=student_incidents,
                           student_grade_records=student_grade_records,
                           current_page_name=f'{student.first_name} {student.last_name}')


# =============================================================================
# STUDENT GRADES
# =============================================================================

@routes_blueprint.route('/student-grades', methods=['GET'])
@login_required
def student_grades():
    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page')
    search        = request.args.get('search', '').strip()
    site_filter   = session.get('active_site_filter', '')
    schoolyr      = session.get('active_schoolyr', '') or '2025-2026'
    term_filter   = request.args.get('term', '').strip()
    grade_filter  = request.args.get('grade_letter', '').strip()
    course_filter = request.args.get('course', '').strip()

    query = (db.session.query(Grade, Student)
             .join(Student, Student.student_id == Grade.grades_stuid)
             .filter(Grade.grades_courseyr == schoolyr))

    if search:
        query = query.filter(db.or_(
            Student.first_name.ilike(f'%{search}%'),
            Student.last_name.ilike(f'%{search}%'),
            Student.student_id.ilike(f'%{search}%'),
        ))
    if site_filter:
        query = query.filter(Student.site_id == site_filter)
    if term_filter:
        query = query.filter(Grade.grades_term == term_filter)
    if grade_filter:
        query = query.filter(Grade.grades_grade == grade_filter)
    if course_filter:
        query = query.filter(Grade.grades_coursenum == course_filter)

    total   = query.count()
    results = (query.order_by(Student.last_name, Student.first_name, Grade.grades_coursenum, Grade.grades_term)
               .offset(offset).limit(per_page).all())
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')

    terms   = [r[0] for r in db.session.query(Grade.grades_term).filter_by(grades_courseyr=schoolyr).distinct().order_by(Grade.grades_term).all()]
    courses = [r[0] for r in db.session.query(Grade.grades_coursenum).filter_by(grades_courseyr=schoolyr).distinct().order_by(Grade.grades_coursenum).all()]

    return render_template('student_grades.html',
        results=results, pagination=pagination, per_page=per_page,
        total=total, terms=terms, courses=courses,
        term_filter=term_filter, grade_filter=grade_filter, course_filter=course_filter,
        current_page_name='Student Grades',
    )


# =============================================================================
# DEMOGRAPHICS DASHBOARD
# =============================================================================

@routes_blueprint.route('/demographics')
@login_required
def demographics():
    import json

    site_filter   = session.get('active_site_filter', '')
    yr_filter     = session.get('active_schoolyr', '')
    status_filter = session.get('active_status_filter', 'active')
    snap_date_str = session.get('active_snap_date', '')

    # Parse snapshot date
    snap_date = None
    if snap_date_str:
        try:
            snap_date = datetime.strptime(snap_date_str, '%Y-%m-%d').date()
        except ValueError:
            snap_date_str = ''

    # Reference date: snapshot date if provided, otherwise today.
    ref_date = snap_date or datetime.now().date()

    def _date_filter(q):
        if status_filter == 'active':
            return q.filter(
                db.or_(Student.enter_date.is_(None), Student.enter_date <= ref_date),
                db.or_(Student.exit_date.is_(None),  Student.exit_date  >= ref_date),
            )
        elif status_filter == 'inactive':
            return q.filter(
                Student.exit_date.isnot(None),
                Student.exit_date < ref_date,
            )
        # 'all' — no date-based status restriction
        return q

    base = _date_filter(Student.query)
    if site_filter:
        base = base.filter(Student.site_id == site_filter)
    if yr_filter:
        base = base.filter(Student.schoolyr == yr_filter)

    def agg(col):
        q = _date_filter(db.session.query(col, func.count(Student.id)))
        if site_filter:
            q = q.filter(Student.site_id == site_filter)
        if yr_filter:
            q = q.filter(Student.schoolyr == yr_filter)
        return q.group_by(col).all()

    total = base.count()

    # KPI counts
    eo_count      = base.filter_by(english_status='EO').count()
    el_count      = base.filter_by(english_status='EL').count()
    ifep_count    = base.filter_by(english_status='IFEP').count()
    rfep_count    = base.filter_by(english_status='RFEP').count()
    homeless_count = base.filter(Student.dwelling.isnot(None), Student.dwelling != '').count()
    tbd_count      = base.filter(db.or_(Student.ssid.is_(None), Student.ssid == '')).count()
    frm_count     = base.filter(Student.frm_code.in_(['F', 'R'])).count()
    swd_count     = base.filter(Student.disability.isnot(None), Student.disability != '').count()
    foster_count  = base.filter_by(foster=True).count()
    migrant_count = base.filter_by(migrant=True).count()
    sed504_count  = base.filter_by(sed504=True).count()

    # Ethnicity
    _eth_map = {
        '100': 'Native American', '200': 'Asian', '300': 'Pacific Islander',
        '400': 'Filipino', '500': 'Hispanic/Latino', '600': 'African American',
        '700': 'White', '900': 'Two or More Races',
    }
    eth_rows = agg(Student.ethnicity)
    ethnicity_table_data = [
        (r[0] or '', _eth_map.get(r[0], r[0] or 'Unknown'), r[1]) for r in
        sorted(eth_rows, key=lambda x: x[1], reverse=True)
    ]

    # Gender
    _gen_map = {'M': 'Male', 'F': 'Female', 'X': 'Non-Binary', 'U': 'Unknown'}
    gen_rows      = agg(Student.gender)
    gender_labels = json.dumps([_gen_map.get(r[0], r[0] or 'Unknown') for r in gen_rows])
    gender_counts = json.dumps([r[1] for r in gen_rows])

    # Grade (ordered)
    _grade_order = ['TK', 'KN', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12']
    grade_dict   = {r[0]: r[1] for r in agg(Student.grade)}
    _g_labels    = [g for g in _grade_order if g in grade_dict]
    grade_labels = json.dumps(_g_labels)
    grade_counts = json.dumps([grade_dict[g] for g in _g_labels])

    # Enrollment by site — respects year & date filters but ignores site filter
    site_q = _date_filter(
        db.session.query(Site.id, Site.site_acronyms, func.count(Student.id))
        .join(Student, Site.id == Student.site_id)
    )
    if yr_filter:
        site_q = site_q.filter(Student.schoolyr == yr_filter)
    site_table_data = site_q.group_by(Site.id, Site.site_acronyms).order_by(Site.site_acronyms).all()
    site_grand_total = sum(r[2] for r in site_table_data)

    return render_template('dashboard/demographics.html',
        current_page_name='Demographics',
        snap_date_str=snap_date_str,
        total=total, eo_count=eo_count, el_count=el_count, ifep_count=ifep_count, rfep_count=rfep_count,
        homeless_count=homeless_count, tbd_count=tbd_count, frm_count=frm_count, swd_count=swd_count,
        foster_count=foster_count, migrant_count=migrant_count, sed504_count=sed504_count,
        ethnicity_table_data=ethnicity_table_data,
        gender_labels=gender_labels, gender_counts=gender_counts,
        grade_labels=grade_labels, grade_counts=grade_counts,
        site_table_data=site_table_data, site_grand_total=site_grand_total,
    )


# =============================================================================
# ENROLLMENT DASHBOARD
# =============================================================================

@routes_blueprint.route('/enrollment')
@login_required
def enrollment():
    import json
    from datetime import date as _date

    site_filter   = session.get('active_site_filter', '')
    yr_filter     = session.get('active_schoolyr', '')
    status_filter = session.get('active_status_filter', 'active')
    snap_date_str = session.get('active_snap_date', '')

    snap_date = None
    if snap_date_str:
        try:
            snap_date = datetime.strptime(snap_date_str, '%Y-%m-%d').date()
        except ValueError:
            snap_date_str = ''

    ref_date = snap_date or _date.today()

    def _status_filter(q):
        if status_filter == 'active':
            return q.filter(
                db.or_(Student.enter_date.is_(None), Student.enter_date <= ref_date),
                db.or_(Student.exit_date.is_(None),  Student.exit_date  >= ref_date),
            )
        elif status_filter == 'inactive':
            return q.filter(
                Student.exit_date.isnot(None),
                Student.exit_date < ref_date,
            )
        return q

    base = _status_filter(Student.query)
    if site_filter:
        base = base.filter(Student.site_id == site_filter)
    if yr_filter:
        base = base.filter(Student.schoolyr == yr_filter)

    total = base.count()

    # Teacher-to-student ratio
    teacher_q = Teacher.query.filter_by(status='Active')
    if site_filter:
        teacher_q = teacher_q.filter(Teacher.site_id == site_filter)
    teacher_count = teacher_q.count()
    teacher_ratio = f"1:{round(total / teacher_count)}" if teacher_count else '—'

    # Max students per course
    course_enrollment_q = (
        db.session.query(Course.id, func.count(Student.id).label('cnt'))
        .join(Course.students)
        .filter(Course.status == 'Active')
    )
    if site_filter:
        course_enrollment_q = course_enrollment_q.filter(Course.site_id == site_filter)
    course_counts = course_enrollment_q.group_by(Course.id).all()
    max_students_per_course = max((r.cnt for r in course_counts), default=0)

    # Subgroup KPIs
    el_count      = base.filter(Student.english_status == 'EL').count()
    frm_count     = base.filter(Student.frm_code.in_(['F', 'R'])).count()
    homeless_count = base.filter(Student.dwelling.isnot(None), Student.dwelling != '').count()
    swd_count     = base.filter(Student.disability.isnot(None), Student.disability != '').count()
    foster_count  = base.filter_by(foster=True).count()
    migrant_count = base.filter_by(migrant=True).count()
    sed504_count  = base.filter_by(sed504=True).count()

    def pct(n):
        return round(n / total * 100, 1) if total else 0.0

    subgroup_data = [
        ('English Learner',        el_count,      pct(el_count)),
        ('Free / Reduced Meal',    frm_count,     pct(frm_count)),
        ('Students w/ Disability', swd_count,     pct(swd_count)),
        ('Homeless',               homeless_count, pct(homeless_count)),
        ('Foster',                 foster_count,  pct(foster_count)),
        ('Migrant',                migrant_count, pct(migrant_count)),
        ('504 Plan',               sed504_count,  pct(sed504_count)),
    ]

    # Year-over-year enrollment — active students as of June 30 of each year, no session filters
    import re as _re
    def _yr_end(yr_str):
        m = _re.match(r'\d{4}-(\d{4})', yr_str)
        end_yr = int(m.group(1)) if m else _date.today().year
        return min(_date(end_yr, 6, 30), _date.today())

    all_yrs = sorted(set(
        r[0] for r in db.session.query(Student.schoolyr)
        .filter(Student.schoolyr.isnot(None), Student.schoolyr != '').all()
    ))
    yoy_rows = []
    for yr in all_yrs:
        yr_ref = _yr_end(yr)
        cnt = (Student.query
               .filter(Student.schoolyr == yr)
               .filter(db.or_(Student.exit_date.is_(None), Student.exit_date >= yr_ref))
               .count())
        yoy_rows.append((yr, cnt))

    yoy_labels = json.dumps([r[0] for r in yoy_rows])
    yoy_counts = json.dumps([r[1] for r in yoy_rows])

    # Determine previous school year
    prev_yr = None
    yoy_change = None
    yoy_change_pct = None
    if len(yoy_rows) >= 2 and yr_filter:
        yoy_dict = {r[0]: r[1] for r in yoy_rows}
        if yr_filter in yoy_dict:
            yrs = sorted(yoy_dict.keys())
            idx = yrs.index(yr_filter)
            if idx > 0:
                prev_yr    = yrs[idx - 1]
                prev_total = yoy_dict[prev_yr]
                yoy_change = total - prev_total
                yoy_change_pct = round(yoy_change / prev_total * 100, 1) if prev_total else None

    # Grade breakdown
    _grade_order = ['TK', 'KN', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12']
    grade_dict = {r[0]: r[1] for r in
                  base.with_entities(Student.grade, func.count(Student.id)).group_by(Student.grade).all()}

    prev_grade_dict = {}
    if prev_yr:
        prev_grade_q = (db.session.query(Student.grade, func.count(Student.id))
                        .filter(Student.schoolyr == prev_yr))
        if site_filter:
            prev_grade_q = prev_grade_q.filter(Student.site_id == site_filter)
        prev_grade_dict = {r[0]: r[1] for r in prev_grade_q.group_by(Student.grade).all()}

    grade_keys = [g for g in _grade_order if g in grade_dict]
    grade_table_data = [
        (g, grade_dict[g], grade_dict[g] - prev_grade_dict.get(g, grade_dict[g]))
        for g in grade_keys
    ]

    # Ethnicity breakdown
    _eth_map = {
        '100': 'Native American', '200': 'Asian', '300': 'Pacific Islander',
        '400': 'Filipino', '500': 'Hispanic/Latino', '600': 'African American',
        '700': 'White', '900': 'Two or More Races',
    }
    eth_rows = (base.with_entities(Student.ethnicity, func.count(Student.id))
                .group_by(Student.ethnicity).all())
    ethnicity_table_data = sorted(
        [(_eth_map.get(r[0], r[0] or 'Unknown'), r[1], pct(r[1])) for r in eth_rows],
        key=lambda x: x[1], reverse=True
    )

    # Enrollment by site — current year
    site_base = _status_filter(
        db.session.query(Site.site_acronyms, func.count(Student.id))
        .join(Student, Site.id == Student.site_id)
    )
    if yr_filter:
        site_base = site_base.filter(Student.schoolyr == yr_filter)
    curr_site_rows = site_base.group_by(Site.id, Site.site_acronyms).order_by(Site.site_acronyms).all()

    # Previous year enrollment by site (no status filter for historical data)
    prev_site_dict = {}
    if prev_yr:
        prev_site_q = (db.session.query(Site.site_acronyms, func.count(Student.id))
                       .join(Student, Site.id == Student.site_id)
                       .filter(Student.schoolyr == prev_yr)
                       .group_by(Site.id, Site.site_acronyms).all())
        prev_site_dict = {r[0]: r[1] for r in prev_site_q}

    # Build site table: (acronym, current_count, change)
    site_table_data = [
        (acronym, cnt, cnt - prev_site_dict.get(acronym, cnt))
        for acronym, cnt in curr_site_rows
    ]

    return render_template('dashboard/enrollment.html',
        current_page_name='Enrollment',
        total=total, el_count=el_count, frm_count=frm_count,
        teacher_ratio=teacher_ratio, max_students_per_course=max_students_per_course,
        yoy_change=yoy_change, yoy_change_pct=yoy_change_pct,
        subgroup_data=subgroup_data,
        grade_table_data=grade_table_data,
        ethnicity_table_data=ethnicity_table_data,
        site_table_data=site_table_data,
        yoy_labels=yoy_labels, yoy_counts=yoy_counts,
        yr_filter=yr_filter,
    )


# =============================================================================
# EARLY WARNING SYSTEM
# =============================================================================

@routes_blueprint.route('/early-warning')
@login_required
def early_warning():
    schoolyr     = session.get('active_schoolyr', '') or '2025-2026'
    site_filter  = session.get('active_site_filter', '')
    risk_filter  = request.args.get('risk_filter',  '').strip()
    grade_filter = request.args.get('grade_filter', '').strip()
    today        = datetime.now().date()
    page, per_page, _ = get_page_args(page_parameter='page', per_page_parameter='per_page')

    # Base student query — active students only
    sq = Student.query.filter(
        db.or_(Student.enter_date.is_(None), Student.enter_date <= today),
        db.or_(Student.exit_date.is_(None),  Student.exit_date  >= today),
        Student.schoolyr == schoolyr,
    )
    if site_filter:
        sq = sq.filter(Student.site_id == site_filter)
    if grade_filter:
        sq = sq.filter(Student.grade == grade_filter)
    students = sq.all()

    # Pre-aggregate absences and incidents by SSID
    abs_counts = dict(
        db.session.query(Absence.ssid, func.count(Absence.id))
        .filter(Absence.school_yr == schoolyr)
        .group_by(Absence.ssid).all()
    )
    inc_counts = dict(
        db.session.query(Incident.sisid, func.count(Incident.id))
        .filter(Incident.schoolyr == schoolyr)
        .group_by(Incident.sisid).all()
    )
    # F grades by student_id
    f_stuids = set(
        r[0] for r in db.session.query(Grade.grades_stuid)
        .filter(Grade.grades_courseyr == schoolyr, Grade.grades_grade == 'F')
        .distinct().all()
    )

    # Build EWS rows
    _ABS_THRESHOLD = 10
    _INC_THRESHOLD = 3

    ews_rows = []
    for s in students:
        absences  = abs_counts.get(s.ssid or '', 0)
        incidents = inc_counts.get(s.ssid or '', 0)
        has_f     = s.student_id in f_stuids

        att_flag  = absences  >= _ABS_THRESHOLD
        beh_flag  = incidents >= _INC_THRESHOLD
        grd_flag  = has_f

        flag_count = sum([att_flag, beh_flag, grd_flag])
        if grd_flag or flag_count >= 2:
            risk = 'high'
        elif flag_count == 1:
            risk = 'medium'
        else:
            risk = 'on_track'

        site_obj = db.session.get(Site, s.site_id)
        ews_rows.append({
            'student':   s,
            'site_name': site_obj.site_name if site_obj else '',
            'absences':  absences,
            'incidents': incidents,
            'has_f':     has_f,
            'att_flag':  att_flag,
            'beh_flag':  beh_flag,
            'grd_flag':  grd_flag,
            'risk':      risk,
        })

    if risk_filter:
        ews_rows = [r for r in ews_rows if r['risk'] == risk_filter]

    ews_rows.sort(key=lambda r: (['high','medium','on_track'].index(r['risk']), r['student'].last_name))

    high_count     = sum(1 for r in ews_rows if r['risk'] == 'high')
    medium_count   = sum(1 for r in ews_rows if r['risk'] == 'medium')
    on_track_count = sum(1 for r in ews_rows if r['risk'] == 'on_track')
    total          = len(ews_rows)

    offset     = (page - 1) * per_page
    ews_page   = ews_rows[offset: offset + per_page]
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')

    return render_template('dashboard/early_warning.html',
        ews_rows=ews_page,
        high_count=high_count,
        medium_count=medium_count,
        on_track_count=on_track_count,
        total=total,
        per_page=per_page,
        pagination=pagination,
        risk_filter=risk_filter,
        grade_filter=grade_filter,
        grades=_GRADE_LIST,
        current_page_name='Early Warning System',
    )


# =============================================================================
# ENROLLMENT K-6 AVAILABILITY
# =============================================================================

@routes_blueprint.route('/enrollment-k6')
@login_required
def enrollment_k6():
    _grade_order = ['TK', 'KN', '1', '2', '3', '4', '5', '6']

    yr_filter = session.get('active_schoolyr', '')

    # Only elementary grades (TK–6) that have at least one active course
    all_grades = sorted(
        set(c.grade_level for c in Course.query.filter_by(status='Active').all()
            if c.grade_level in _grade_order),
        key=lambda g: _grade_order.index(g)
    )

    grade_filter = request.args.get('grade', all_grades[0] if all_grades else '')

    sites = Site.query.order_by(Site.site_name).all()

    _sdc_keywords = ('special', 'sped', 'sdc', 'resource')

    def _inst(teacher):
        dept = (teacher.department or '').lower()
        return 'SDC' if any(k in dept for k in _sdc_keywords) else 'S'

    site_data = []
    summary_rows = []
    grand_total = 0

    for site in sites:
        courses = (Course.query
                   .filter_by(status='Active', site_id=site.id, grade_level=grade_filter)
                   .join(Teacher, Course.teacher_id == Teacher.id)
                   .order_by(Teacher.last_name, Course.period)
                   .all())
        if not courses:
            continue

        rows = []
        site_total = 0
        for course in courses:
            teacher  = course.teacher
            enrolled = len(course.students)
            capacity = course.max_students or 0
            rows.append({
                'teacher':   f'{teacher.last_name}, {teacher.first_name}',
                'inst':      _inst(teacher),
                'grade':     course.grade_level,
                'totals':    enrolled,
                'capacity':  capacity,
                'available': capacity - enrolled,
            })
            site_total += enrolled

        site_available = sum(r['available'] for r in rows)
        site_data.append({
            'site_name': site.site_name,
            'rows':      rows,
            'total':     site_total,
            'available': site_available,
        })

    total_available = sum(s['available'] for s in site_data)
    total_enrolled  = sum(s['total']     for s in site_data)
    total_capacity  = sum(
        r['capacity'] for s in site_data for r in s['rows']
    )

    return render_template('dashboard/enrollment_k6.html',
        current_page_name='Enrollment K-6',
        all_grades=all_grades,
        grade_filter=grade_filter,
        site_data=site_data,
        total_available=total_available,
        total_enrolled=total_enrolled,
        total_capacity=total_capacity,
    )


# =============================================================================
# ENROLLMENT MS AVAILABILITY
# =============================================================================

@routes_blueprint.route('/enrollment-ms')
@login_required
def enrollment_ms():
    _grade_order = ['7', '8']

    yr_filter = session.get('active_schoolyr', '')

    all_grades = sorted(
        set(c.grade_level for c in Course.query.filter_by(status='Active').all()
            if c.grade_level in _grade_order),
        key=lambda g: _grade_order.index(g)
    )

    grade_filter = request.args.get('grade', all_grades[0] if all_grades else '')

    sites = Site.query.order_by(Site.site_name).all()

    _sdc_keywords = ('special', 'sped', 'sdc', 'resource')

    def _inst(teacher):
        dept = (teacher.department or '').lower()
        return 'SDC' if any(k in dept for k in _sdc_keywords) else 'S'

    site_data = []

    for site in sites:
        courses = (Course.query
                   .filter_by(status='Active', site_id=site.id, grade_level=grade_filter)
                   .join(Teacher, Course.teacher_id == Teacher.id)
                   .order_by(Teacher.last_name, Course.period)
                   .all())
        if not courses:
            continue

        rows = []
        site_total = 0
        for course in courses:
            teacher  = course.teacher
            enrolled = len(course.students)
            capacity = course.max_students or 0
            rows.append({
                'teacher':   f'{teacher.last_name}, {teacher.first_name}',
                'inst':      _inst(teacher),
                'grade':     course.grade_level,
                'totals':    enrolled,
                'capacity':  capacity,
                'available': capacity - enrolled,
            })
            site_total += enrolled

        site_available = sum(r['available'] for r in rows)
        site_data.append({
            'site_name': site.site_name,
            'rows':      rows,
            'total':     site_total,
            'available': site_available,
        })

    total_available = sum(s['available'] for s in site_data)
    total_enrolled  = sum(s['total']     for s in site_data)
    total_capacity  = sum(r['capacity'] for s in site_data for r in s['rows'])

    return render_template('dashboard/enrollment_ms.html',
        current_page_name='Enrollment MS',
        all_grades=all_grades,
        grade_filter=grade_filter,
        site_data=site_data,
        total_available=total_available,
        total_enrolled=total_enrolled,
        total_capacity=total_capacity,
    )


# =============================================================================
# ENROLLMENT HS AVAILABILITY
# =============================================================================

@routes_blueprint.route('/enrollment-hs')
@login_required
def enrollment_hs():
    _grade_order = ['9', '10', '11', '12']

    yr_filter = session.get('active_schoolyr', '')

    all_grades = sorted(
        set(c.grade_level for c in Course.query.filter_by(status='Active').all()
            if c.grade_level in _grade_order),
        key=lambda g: _grade_order.index(g)
    )

    grade_filter = request.args.get('grade', all_grades[0] if all_grades else '')

    sites = Site.query.order_by(Site.site_name).all()

    _sdc_keywords = ('special', 'sped', 'sdc', 'resource')

    def _inst(teacher):
        dept = (teacher.department or '').lower()
        return 'SDC' if any(k in dept for k in _sdc_keywords) else 'S'

    site_data = []

    for site in sites:
        courses = (Course.query
                   .filter_by(status='Active', site_id=site.id, grade_level=grade_filter)
                   .join(Teacher, Course.teacher_id == Teacher.id)
                   .order_by(Teacher.last_name, Course.period)
                   .all())
        if not courses:
            continue

        rows = []
        site_total = 0
        for course in courses:
            teacher  = course.teacher
            enrolled = len(course.students)
            capacity = course.max_students or 0
            rows.append({
                'teacher':   f'{teacher.last_name}, {teacher.first_name}',
                'inst':      _inst(teacher),
                'grade':     course.grade_level,
                'totals':    enrolled,
                'capacity':  capacity,
                'available': capacity - enrolled,
            })
            site_total += enrolled

        site_available = sum(r['available'] for r in rows)
        site_data.append({
            'site_name': site.site_name,
            'rows':      rows,
            'total':     site_total,
            'available': site_available,
        })

    total_available = sum(s['available'] for s in site_data)
    total_enrolled  = sum(s['total']     for s in site_data)
    total_capacity  = sum(r['capacity'] for s in site_data for r in s['rows'])

    return render_template('dashboard/enrollment_hs.html',
        current_page_name='Enrollment HS',
        all_grades=all_grades,
        grade_filter=grade_filter,
        site_data=site_data,
        total_available=total_available,
        total_enrolled=total_enrolled,
        total_capacity=total_capacity,
    )


# =============================================================================
# SWD DASHBOARD
# =============================================================================

@routes_blueprint.route('/swd')
@login_required
def swd_dashboard():
    import json

    site_filter   = session.get('active_site_filter', '')
    yr_filter     = session.get('active_schoolyr', '')
    status_filter = session.get('active_status_filter', 'active')
    snap_date_str = session.get('active_snap_date', '')

    snap_date = None
    if snap_date_str:
        try:
            snap_date = datetime.strptime(snap_date_str, '%Y-%m-%d').date()
        except ValueError:
            snap_date_str = ''

    ref_date = snap_date or datetime.now().date()

    def _date_filter(q):
        if status_filter == 'active':
            return q.filter(
                db.or_(Student.enter_date.is_(None), Student.enter_date <= ref_date),
                db.or_(Student.exit_date.is_(None),  Student.exit_date  >= ref_date),
            )
        elif status_filter == 'inactive':
            return q.filter(Student.exit_date.isnot(None), Student.exit_date < ref_date)
        return q

    # Total enrollment (for % context)
    enrollment_base = _date_filter(Student.query)
    if site_filter:
        enrollment_base = enrollment_base.filter(Student.site_id == site_filter)
    if yr_filter:
        enrollment_base = enrollment_base.filter(Student.schoolyr == yr_filter)
    total_enrollment = enrollment_base.count()

    # SWD base — all above filters + must have a disability code
    base = enrollment_base.filter(Student.disability.isnot(None), Student.disability != '')
    total_swd = base.count()

    # KPI counts — all scoped to SWD students
    sped_exited     = base.filter(Student.sped_exdate.isnot(None)).count()
    sed504_count    = base.filter_by(sed504=True).count()
    el_count        = base.filter_by(english_status='EL').count()
    homeless_count  = base.filter(Student.dwelling.isnot(None), Student.dwelling != '').count()
    frm_count       = base.filter(Student.frm_code.in_(['F', 'R'])).count()
    foster_count    = base.filter_by(foster=True).count()
    migrant_count   = base.filter_by(migrant=True).count()

    def agg(col):
        q = _date_filter(db.session.query(col, func.count(Student.id)))
        q = q.filter(Student.disability.isnot(None), Student.disability != '')
        if site_filter:
            q = q.filter(Student.site_id == site_filter)
        if yr_filter:
            q = q.filter(Student.schoolyr == yr_filter)
        return q.group_by(col).all()

    # Disability breakdown (sorted by count desc)
    _dis_map = {
        'AU':  'Autism',              'DB':  'Deaf-Blindness',
        'DD':  'Developmental Delay', 'ED':  'Emotional Disturbance',
        'HH':  'Hard of Hearing',     'ID':  'Intellectual Disability',
        'MD':  'Multiple Disabilities','OHI': 'Other Health Impairment',
        'OI':  'Orthopedic Impairment','SLD': 'Specific Learning Disability',
        'SLI': 'Speech/Language',     'TBI': 'Traumatic Brain Injury',
        'VI':  'Visual Impairment',
    }
    dis_rows = agg(Student.disability)
    dis_rows_sorted = sorted(dis_rows, key=lambda x: x[1], reverse=True)
    disability_labels = json.dumps([_dis_map.get(r[0], r[0] or 'Unknown') for r in dis_rows_sorted])
    disability_counts = json.dumps([r[1] for r in dis_rows_sorted])

    # Grade breakdown
    _grade_order = ['TK','KN','1','2','3','4','5','6','7','8','9','10','11','12']
    grade_dict   = {r[0]: r[1] for r in agg(Student.grade)}
    _g_labels    = [g for g in _grade_order if g in grade_dict]
    grade_labels = json.dumps(_g_labels)
    grade_counts = json.dumps([grade_dict[g] for g in _g_labels])

    # Gender breakdown
    _gen_map = {'M': 'Male', 'F': 'Female', 'X': 'Non-Binary', 'U': 'Unknown'}
    gen_rows      = agg(Student.gender)
    gender_labels = json.dumps([_gen_map.get(r[0], r[0] or 'Unknown') for r in gen_rows])
    gender_counts = json.dumps([r[1] for r in gen_rows])

    # Ethnicity table
    _eth_map = {
        '100': 'Native American', '200': 'Asian', '300': 'Pacific Islander',
        '400': 'Filipino', '500': 'Hispanic/Latino', '600': 'African American',
        '700': 'White', '900': 'Two or More Races',
    }
    eth_rows = agg(Student.ethnicity)
    ethnicity_table_data = [
        (r[0] or '', _eth_map.get(r[0], r[0] or 'Unknown'), r[1]) for r in
        sorted(eth_rows, key=lambda x: x[1], reverse=True)
    ]

    # Site table (SWD by site, ignores site filter)
    site_q = _date_filter(
        db.session.query(Site.id, Site.site_name, func.count(Student.id))
        .join(Student, Site.id == Student.site_id)
    ).filter(Student.disability.isnot(None), Student.disability != '')
    if yr_filter:
        site_q = site_q.filter(Student.schoolyr == yr_filter)
    site_table_data  = site_q.group_by(Site.id, Site.site_name).order_by(Site.site_name).all()
    site_grand_total = sum(r[2] for r in site_table_data)

    return render_template('dashboard/swd.html',
        current_page_name='SWD',
        snap_date_str=snap_date_str,
        total=total_swd, total_swd=total_swd, total_enrollment=total_enrollment,
        sped_exited=sped_exited, sed504_count=sed504_count, el_count=el_count,
        homeless_count=homeless_count, frm_count=frm_count,
        foster_count=foster_count, migrant_count=migrant_count,
        disability_labels=disability_labels, disability_counts=disability_counts,
        grade_labels=grade_labels, grade_counts=grade_counts,
        gender_labels=gender_labels, gender_counts=gender_counts,
        ethnicity_table_data=ethnicity_table_data,
        site_table_data=site_table_data, site_grand_total=site_grand_total,
    )


# =============================================================================
# ABSENTEEISM DASHBOARD
# =============================================================================

@routes_blueprint.route('/absenteeism')
@login_required
def absenteeism():
    import json, calendar

    site_filter   = session.get('active_site_filter', '')
    yr_filter     = session.get('active_schoolyr', '')
    snap_date_str = session.get('active_snap_date', '')

    snap_date = None
    if snap_date_str:
        try:
            snap_date = datetime.strptime(snap_date_str, '%Y-%m-%d').date()
        except ValueError:
            snap_date_str = ''

    def base_q():
        q = Absence.query.filter(Absence.abs_date.isnot(None))
        if site_filter:
            q = q.filter(Absence.site_id == site_filter)
        if yr_filter:
            q = q.filter(Absence.school_yr == yr_filter)
        if snap_date:
            q = q.filter(Absence.abs_date <= snap_date)
        return q

    total_absences = base_q().count()

    # Enrolled students for Absenteeism rate
    from datetime import date as _date
    today = _date.today()
    student_base = Student.query
    status_filter = session.get('active_status_filter', 'active')
    if status_filter == 'active':
        student_base = student_base.filter(
            db.or_(Student.enter_date.is_(None), Student.enter_date <= today),
            db.or_(Student.exit_date.is_(None),  Student.exit_date  >= today),
        )
    if site_filter:
        student_base = student_base.filter(Student.site_id == site_filter)
    if yr_filter:
        student_base = student_base.filter(Student.schoolyr == yr_filter)
    total_students = student_base.count()
    avg_absences_per_student = round(total_absences / total_students, 1) if total_students else 0.0

    # School days elapsed (approx: weekdays since Aug 25 of the start year)
    if yr_filter and '-' in yr_filter:
        start_year = int(yr_filter.split('-')[0])
    else:
        start_year = today.year if today.month >= 8 else today.year - 1
    school_start = _date(start_year, 8, 25)
    ref_end      = today if today <= _date(start_year + 1, 6, 10) else _date(start_year + 1, 6, 10)
    from datetime import timedelta
    school_days  = sum(1 for i in range((ref_end - school_start).days + 1)
                       if (school_start + timedelta(i)).weekday() < 5)
    school_days  = max(school_days, 1)

    total_possible  = total_students * school_days
    absence_rate    = round(total_absences / total_possible * 100, 1) if total_possible else 0.0

    # Chronic absenteeism — per student (ssid), count absences vs school_days
    ssid_rows = (base_q()
                 .with_entities(Absence.ssid, func.count(Absence.id).label('cnt'))
                 .group_by(Absence.ssid).all())
    threshold       = school_days * 0.10
    borderline_lo   = school_days * 0.07
    borderline_hi   = school_days * 0.09
    chronic_hi      = school_days * 0.25

    borderline_count = sum(1 for r in ssid_rows if borderline_lo <= r.cnt <= borderline_hi)
    chronic_count    = sum(1 for r in ssid_rows if threshold     <= r.cnt < chronic_hi)
    severe_count     = sum(1 for r in ssid_rows if r.cnt         >= chronic_hi)
    chronic_students = chronic_count + severe_count
    chronic_pct      = round(chronic_students / total_students * 100, 1) if total_students else 0.0

    # Fetch all absences in one pass; group in Python to avoid SQL dialect issues
    all_abs = (base_q()
               .with_entities(Absence.abs_date, Absence.grade,
                               Absence.abs_abbr, Absence.ssid, Absence.site_id)
               .all())

    # Absences per month
    from collections import defaultdict
    month_dict = defaultdict(int)
    for a in all_abs:
        if a.abs_date:
            month_dict[a.abs_date.month] += 1
    _month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    month_labels = json.dumps([_month_names[m-1] for m in sorted(month_dict)])
    month_counts = json.dumps([month_dict[m] for m in sorted(month_dict)])

    # Absences per grade
    grade_dict = defaultdict(int)
    for a in all_abs:
        grade_dict[a.grade or 'N/A'] += 1
    _grade_order = ['TK','KN','1','2','3','4','5','6','7','8','9','10','11','12','N/A']
    grade_sorted = sorted(grade_dict.items(), key=lambda x: _grade_order.index(x[0]) if x[0] in _grade_order else len(_grade_order))
    grade_labels = json.dumps([g for g, _ in grade_sorted])
    grade_counts = json.dumps([c for _, c in grade_sorted])
    grade_pcts   = json.dumps([round(c / total_absences * 100, 1) if total_absences else 0
                                for _, c in grade_sorted])

    # Absences per ethnicity (join in Python via ssid → Student lookup)
    _eth_map = {'100':'Native American','200':'Asian','300':'Pacific Islander',
                '400':'Filipino','500':'Hispanic/Latino','600':'African American',
                '700':'White','900':'Two or More Races'}
    ssid_eth = {s.ssid: s.ethnicity for s in
                Student.query.with_entities(Student.ssid, Student.ethnicity)
                .filter(Student.ssid.isnot(None)).all()}
    eth_dict = defaultdict(int)
    for a in all_abs:
        eth = ssid_eth.get(a.ssid, None)
        eth_dict[_eth_map.get(eth, 'Unknown')] += 1
    ethnicity_data = sorted(
        [(label, cnt, round(cnt / total_absences * 100, 1) if total_absences else 0)
         for label, cnt in eth_dict.items()],
        key=lambda x: x[1], reverse=True
    )

    # Most absences in a day — direct SQL GROUP BY so filters are always applied
    top_days = (base_q()
                .with_entities(Absence.abs_date, func.count(Absence.id).label('cnt'))
                .group_by(Absence.abs_date)
                .order_by(func.count(Absence.id).desc())
                .limit(10)
                .all())

    # Totals by site
    _excused_set   = {'EA', 'ET', 'MED'}
    _unexcused_set = {'UA', 'UT', 'ISS', 'SS'}
    site_excused   = defaultdict(int)
    site_unexcused = defaultdict(int)
    site_total_abs = defaultdict(int)
    for a in all_abs:
        site_total_abs[a.site_id] += 1
        if a.abs_abbr in _excused_set:
            site_excused[a.site_id] += 1
        elif a.abs_abbr in _unexcused_set:
            site_unexcused[a.site_id] += 1
    sites_all = Site.query.order_by(Site.site_name).all()
    site_table = []
    for s in sites_all:
        if s.id not in site_total_abs:
            continue
        sp  = max(student_base.filter(Student.site_id == s.id).count() * school_days, 1)
        att = round(site_total_abs[s.id] / sp * 100, 1)
        site_table.append((s.site_acronyms, site_excused[s.id], site_unexcused[s.id], att))

    # Absences by day of week
    _dow_names = {0:'Monday',1:'Tuesday',2:'Wednesday',3:'Thursday',4:'Friday',5:'Saturday',6:'Sunday'}
    dow_dict   = defaultdict(int)
    for a in all_abs:
        if a.abs_date:
            dow_dict[a.abs_date.weekday()] += 1  # 0=Mon, 6=Sun
    weekday_keys = sorted(k for k in dow_dict if k < 5)  # Mon–Fri only
    dow_labels  = json.dumps([_dow_names[k] for k in weekday_keys])
    dow_counts  = json.dumps([dow_dict[k] for k in weekday_keys])

    return render_template('dashboard/absenteeism.html',
        current_page_name='Absenteeism',
        total_absences=total_absences, total_students=total_students,
        avg_absences_per_student=avg_absences_per_student,
        absence_rate=absence_rate, chronic_pct=chronic_pct,
        borderline_count=borderline_count, chronic_count=chronic_count, severe_count=severe_count,
        month_labels=month_labels, month_counts=month_counts,
        grade_labels=grade_labels, grade_counts=grade_counts, grade_pcts=grade_pcts,
        ethnicity_data=ethnicity_data,
        top_days=top_days,
        site_table=site_table,
        dow_labels=dow_labels, dow_counts=dow_counts,
    )


@routes_blueprint.route('/attendance-rates')
@login_required
def attendance_rates():
    from collections import defaultdict
    from datetime import timedelta, date as _date

    yr_filter   = session.get('active_schoolyr', '')
    site_filter = session.get('active_site_filter', '')
    today       = _date.today()

    # School days elapsed
    if yr_filter and '-' in yr_filter:
        start_year = int(yr_filter.split('-')[0])
    else:
        start_year = today.year if today.month >= 8 else today.year - 1
    school_start = _date(start_year, 8, 25)
    ref_end      = today if today <= _date(start_year + 1, 6, 10) else _date(start_year + 1, 6, 10)
    school_days  = max(sum(1 for i in range((ref_end - school_start).days + 1)
                           if (school_start + timedelta(i)).weekday() < 5), 1)

    # Absence counts per SSID
    abs_q = Absence.query
    if yr_filter:
        abs_q = abs_q.filter(Absence.school_yr == yr_filter)
    if site_filter:
        site_obj = Site.query.get(site_filter)
        if site_obj:
            abs_q = abs_q.filter(Absence.site_id == site_obj.id)
    ssid_abs = defaultdict(int)
    for a in abs_q.with_entities(Absence.ssid, func.count(Absence.id)).group_by(Absence.ssid).all():
        if a[0]:
            ssid_abs[a[0]] = a[1]

    # Build per-course data
    _grade_order = ['TK', 'KN', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12']
    courses_q = Course.query.filter_by(status='Active')
    if site_filter:
        courses_q = courses_q.filter(Course.site_id == site_filter)

    grades_data = defaultdict(list)
    for course in courses_q.order_by(Course.grade_level, Course.course_name).all():
        grade       = course.grade_level or 'N/A'
        enrolled    = [s for s in course.students]
        n_enrolled  = len(enrolled)
        absences    = sum(ssid_abs.get(s.ssid, 0) for s in enrolled if s.ssid)
        possible    = n_enrolled * school_days
        att_pct     = round((possible - absences) / possible * 100, 1) if possible else 100.0
        grades_data[grade].append({
            'teacher':     f'{course.teacher.last_name}, {course.teacher.first_name}',
            'teacher_id':  course.teacher.id,
            'course_name': course.course_name,
            'course_code': course.course_code,
            'course_id':   course.id,
            'enrolled':    n_enrolled,
            'absences':    absences,
            'att_pct':     att_pct,
        })

    sorted_grades = sorted(grades_data.keys(),
                           key=lambda g: _grade_order.index(g) if g in _grade_order else 99)

    # KPI summary
    all_rows       = [r for rows in grades_data.values() for r in rows]
    enrolled_q = Student.query.filter(
        db.or_(Student.enter_date.is_(None), Student.enter_date <= today),
        db.or_(Student.exit_date.is_(None),  Student.exit_date  >= today),
    )
    if yr_filter:
        enrolled_q = enrolled_q.filter(Student.schoolyr == yr_filter)
    if site_filter:
        enrolled_q = enrolled_q.filter(Student.site_id == site_filter)
    total_enrolled = enrolled_q.count()
    total_absences = sum(r['absences'] for r in all_rows)
    possible_all   = total_enrolled * school_days
    overall_att    = round((possible_all - total_absences) / possible_all * 100, 1) if possible_all else 100.0
    # Best / worst grade
    grade_avgs  = {g: round(sum(r['att_pct'] for r in rows) / len(rows), 1)
                   for g, rows in grades_data.items() if rows}
    best_grade  = max(grade_avgs, key=grade_avgs.get) if grade_avgs else '—'
    worst_grade = min(grade_avgs, key=grade_avgs.get) if grade_avgs else '—'

    # Best course
    best_course = max(all_rows, key=lambda r: r['att_pct']) if all_rows else None

    return render_template('dashboard/attendance_rates.html',
        current_page_name='Attendance Rates',
        overall_att=overall_att, total_enrolled=total_enrolled,
        best_course=best_course,
        best_grade=best_grade, best_grade_att=grade_avgs.get(best_grade, 0),
        worst_grade=worst_grade, worst_grade_att=grade_avgs.get(worst_grade, 0),
        grades_data=grades_data, sorted_grades=sorted_grades,
        school_days=school_days,
    )


@routes_blueprint.route('/absences', methods=['GET'])
@login_required
def absences():
    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page')
    search         = request.args.get('search', '').strip()
    grade_filter   = request.args.get('grade_filter', '').strip()
    abs_types      = request.args.getlist('abs_type')
    subgroups      = [s.strip() for s in request.args.getlist('subgroup') if s.strip()]
    english_status = [s.strip() for s in request.args.getlist('english_status') if s.strip()]
    gender_filters = [s.strip() for s in request.args.getlist('gender') if s.strip()]
    site_filter    = session.get('active_site_filter', '')
    yr_filter      = session.get('active_schoolyr', '')

    query = Absence.query
    if site_filter:
        query = query.filter(Absence.site_id == site_filter)
    if yr_filter:
        query = query.filter(Absence.school_yr == yr_filter)
    if grade_filter:
        query = query.filter(Absence.grade == grade_filter)
    if abs_types:
        query = query.filter(Absence.abs_abbr.in_(abs_types))
    if search:
        name_ssids = db.session.query(Student.ssid).filter(
            db.or_(
                Student.first_name.ilike(f'%{search}%'),
                Student.last_name.ilike(f'%{search}%'),
            ),
            Student.ssid.isnot(None), Student.ssid != ''
        ).subquery()
        query = query.filter(
            db.or_(
                Absence.ssid.ilike(f'%{search}%'),
                Absence.abs_desc.ilike(f'%{search}%'),
                Absence.abs_abbr.ilike(f'%{search}%'),
                Absence.ssid.in_(name_ssids),
            )
        )

    # Demographic filters — resolve matching SSIDs via Student table
    if subgroups or english_status or gender_filters:
        stu_q = Student.query.with_entities(Student.ssid).filter(Student.ssid.isnot(None), Student.ssid != '')
        if english_status:
            stu_q = stu_q.filter(Student.english_status.in_(english_status))
        if gender_filters:
            stu_q = stu_q.filter(Student.gender.in_(gender_filters))
        if subgroups:
            _sg = {
                'homeless': db.and_(Student.dwelling.isnot(None), Student.dwelling != ''),
                'frm':      Student.frm_code.in_(['F', 'R']),
                'swd':      db.and_(Student.disability.isnot(None), Student.disability != ''),
                'foster':   Student.foster == True,
                'migrant':  Student.migrant == True,
                'sed504':   Student.sed504 == True,
            }
            conds = [_sg[sg] for sg in subgroups if sg in _sg]
            if conds:
                stu_q = stu_q.filter(db.and_(*conds))
        matching_ssids = [r[0] for r in stu_q.all()]
        query = query.filter(Absence.ssid.in_(matching_ssids))

    total      = query.count()
    absences_q = query.order_by(Absence.school_yr.desc(), Absence.site_id.asc()).offset(offset).limit(per_page).all()
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')
    grades     = _GRADE_LIST

    # Build ssid → full name and ssid → student.id lookups for the current page
    page_ssids = {a.ssid for a in absences_q if a.ssid}
    if page_ssids:
        stu_rows = (Student.query
                           .with_entities(Student.ssid, Student.id, Student.first_name, Student.last_name)
                           .filter(Student.ssid.in_(page_ssids)).all())
        ssid_names = {s.ssid: f"{s.last_name}, {s.first_name}" for s in stu_rows}
        ssid_ids   = {s.ssid: s.id for s in stu_rows}
    else:
        ssid_names = {}
        ssid_ids   = {}

    return render_template('absences.html',
        absences=absences_q, pagination=pagination, per_page=per_page,
        total=total, grades=grades,
        grade_filter=grade_filter, abs_types=abs_types,
        subgroups=subgroups, english_status=english_status, gender_filters=gender_filters,
        ssid_names=ssid_names, ssid_ids=ssid_ids,
        current_page_name='Absences')


# =============================================================================
# DISCIPLINE DASHBOARD
# =============================================================================

@routes_blueprint.route('/discipline')
@login_required
def discipline_dashboard():
    import json
    from collections import defaultdict

    yr_filter   = session.get('active_schoolyr', '')
    site_filter = session.get('active_site_filter', '')

    base = Incident.query
    if yr_filter:
        base = base.filter(Incident.schoolyr == yr_filter)
    if site_filter:
        site_obj = Site.query.get(site_filter)
        if site_obj:
            base = base.filter(Incident.site == site_obj.site_acronyms)

    all_inc = base.all()

    total_incidents = len(all_inc)
    major_count     = sum(1 for i in all_inc if i.major)
    minor_count     = sum(1 for i in all_inc if i.minor)
    total_susp_days = sum(i.suspended_days or 0 for i in all_inc)

    # Student lookup: ssid → (gender, grade)
    students_all = Student.query.with_entities(Student.ssid, Student.gender, Student.grade).filter(Student.ssid.isnot(None)).all()
    ssid_gender  = {s.ssid: s.gender for s in students_all}
    ssid_grade   = {s.ssid: s.grade  for s in students_all}

    # Incident rate per 100 enrolled students
    enrolled_q = Student.query.filter(
        db.or_(Student.enter_date.is_(None), Student.enter_date <= datetime.now().date()),
        db.or_(Student.exit_date.is_(None),  Student.exit_date  >= datetime.now().date()),
    )
    if site_filter:
        enrolled_q = enrolled_q.filter(Student.site_id == site_filter)
    total_enrolled  = enrolled_q.count() or 1
    incident_rate   = round(total_incidents / total_enrolled * 100, 1)

    # By month
    month_dict = defaultdict(int)
    _mon_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    for i in all_inc:
        if i.incident_date:
            month_dict[i.incident_date.month] += 1
    month_labels = json.dumps([_mon_names[m-1] for m in sorted(month_dict)])
    month_counts = json.dumps([month_dict[m] for m in sorted(month_dict)])

    # By site (bar chart)
    site_dict  = defaultdict(int)
    for i in all_inc:
        site_dict[i.site or 'Unknown'] += 1
    site_items  = sorted(site_dict.items(), key=lambda x: x[1], reverse=True)
    site_labels = json.dumps([s for s, _ in site_items])
    site_counts = json.dumps([c for _, c in site_items])

    # Top infractions
    infraction_dict = defaultdict(int)
    for i in all_inc:
        label = i.major or i.minor
        if label:
            infraction_dict[label] += 1
    top_infractions   = sorted(infraction_dict.items(), key=lambda x: x[1], reverse=True)[:8]
    infraction_labels = json.dumps([k for k, _ in top_infractions])
    infraction_counts = json.dumps([v for _, v in top_infractions])

    # By day of week
    dow_order = ['Monday','Tuesday','Wednesday','Thursday','Friday']
    dow_dict  = defaultdict(int)
    for i in all_inc:
        if i.day_of_week and i.day_of_week in dow_order:
            dow_dict[i.day_of_week] += 1
    dow_labels = json.dumps(dow_order)
    dow_counts = json.dumps([dow_dict[d] for d in dow_order])

    # By gender
    _gen_map   = {'M': 'Male', 'F': 'Female', 'X': 'Non-Binary', 'U': 'Unknown'}
    gender_dict = defaultdict(int)
    for i in all_inc:
        g = ssid_gender.get(i.sisid, 'Unknown') if i.sisid else 'Unknown'
        gender_dict[_gen_map.get(g, 'Unknown')] += 1
    gender_labels = json.dumps(list(gender_dict.keys()))
    gender_counts = json.dumps(list(gender_dict.values()))

    # By grade
    _grade_order = ['TK','KN','1','2','3','4','5','6','7','8','9','10','11','12']
    grade_dict   = defaultdict(int)
    for i in all_inc:
        gr = ssid_grade.get(i.sisid, 'N/A') if i.sisid else 'N/A'
        grade_dict[gr] += 1
    grade_sorted  = sorted(grade_dict.items(), key=lambda x: _grade_order.index(x[0]) if x[0] in _grade_order else 99)
    grade_labels  = json.dumps([g for g, _ in grade_sorted])
    grade_counts  = json.dumps([c for _, c in grade_sorted])

    # Site table
    site_table = defaultdict(lambda: {'major': 0, 'minor': 0, 'susp': 0.0})
    for i in all_inc:
        s = i.site or 'Unknown'
        if i.major:   site_table[s]['major'] += 1
        elif i.minor: site_table[s]['minor'] += 1
        site_table[s]['susp'] += i.suspended_days or 0
    site_table_data = sorted(site_table.items(), key=lambda x: x[1]['major'] + x[1]['minor'], reverse=True)

    return render_template('dashboard/discipline.html',
        current_page_name='Discipline',
        total_incidents=total_incidents, major_count=major_count,
        minor_count=minor_count, total_susp_days=total_susp_days,
        incident_rate=incident_rate,
        month_labels=month_labels, month_counts=month_counts,
        site_labels=site_labels, site_counts=site_counts,
        infraction_labels=infraction_labels, infraction_counts=infraction_counts,
        dow_labels=dow_labels, dow_counts=dow_counts,
        gender_labels=gender_labels, gender_counts=gender_counts,
        grade_labels=grade_labels, grade_counts=grade_counts,
        site_table_data=site_table_data,
    )


# =============================================================================
# INCIDENTS
# =============================================================================

@routes_blueprint.route('/incidents', methods=['GET'])
@login_required
def incidents():
    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page')
    search      = request.args.get('search', '').strip()
    site_filter = request.args.get('site_filter', '').strip()
    type_filter = request.args.get('type_filter', '').strip()
    yr_filter   = request.args.get('schoolyr', '').strip() or session.get('active_schoolyr', '')

    query = Incident.query
    if search:
        query = query.filter(db.or_(
            Incident.sisid.ilike(f'%{search}%'),
            Incident.incident_id.ilike(f'%{search}%'),
            Incident.major.ilike(f'%{search}%'),
            Incident.minor.ilike(f'%{search}%'),
        ))
    if site_filter:
        query = query.filter(Incident.site == site_filter)
    if type_filter == 'major':
        query = query.filter(Incident.major.isnot(None), Incident.major != '')
    elif type_filter == 'minor':
        query = query.filter(Incident.minor.isnot(None), Incident.minor != '')
    if yr_filter:
        query = query.filter(Incident.schoolyr == yr_filter)

    total       = query.count()
    incidents_q = query.order_by(Incident.incident_date.desc()).offset(offset).limit(per_page).all()
    pagination  = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')
    sites       = sorted({i.site for i in Incident.query.with_entities(Incident.site).distinct() if i.site})
    ssid_to_id  = {s.ssid: s.id for s in Student.query.with_entities(Student.ssid, Student.id).filter(Student.ssid.isnot(None)).all()}

    return render_template('incidents.html',
        incidents=incidents_q, pagination=pagination, per_page=per_page,
        total=total, sites=sites, site_filter=site_filter,
        type_filter=type_filter, yr_filter=yr_filter,
        ssid_to_id=ssid_to_id,
        current_page_name='Incidents')


# =============================================================================
# TEACHERS
# =============================================================================

@routes_blueprint.route('/teachers', methods=['GET'])
@login_required
def teachers():
    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page')
    search      = request.args.get('search', '').strip()
    site_filter = request.args.get('site_filter', '').strip()
    dept_filter = request.args.get('dept_filter', '').strip()

    query = Teacher.query
    if search:
        query = query.filter(
            db.or_(Teacher.first_name.ilike(f'%{search}%'),
                   Teacher.last_name.ilike(f'%{search}%'),
                   Teacher.employee_id.ilike(f'%{search}%'))
        )
    if site_filter:
        query = query.filter(Teacher.site_id == site_filter)
    if dept_filter:
        query = query.filter(Teacher.department == dept_filter)

    total      = query.count()
    teachers_q = query.order_by(Teacher.last_name.asc(), Teacher.first_name.asc()).offset(offset).limit(per_page).all()
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')
    sites      = Site.query.order_by(Site.site_name.asc()).all()
    departments = sorted({t.department for t in Teacher.query.all() if t.department})

    return render_template('teachers.html',
        teachers=teachers_q, pagination=pagination, per_page=per_page,
        sites=sites, departments=departments, dept_filter=dept_filter,
        current_page_name='Teachers')


@routes_blueprint.route('/add_teacher', methods=['GET', 'POST'])
@login_required
def add_teacher():
    return redirect(url_for('routes.teachers'))


@routes_blueprint.route('/teacher/<int:teacher_id>', methods=['GET'])
@login_required
def teacher_details(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    # Flat, deduplicated list of students across all teacher's courses
    seen = set()
    teacher_students = []
    for course in teacher.courses:
        for student in course.students:
            if student.id not in seen:
                seen.add(student.id)
                teacher_students.append((student, course))
    teacher_students.sort(key=lambda x: (x[0].last_name, x[0].first_name))
    return render_template('teacher_details.html', teacher=teacher,
                           teacher_students=teacher_students,
                           current_page_name=f'{teacher.first_name} {teacher.last_name}')


@routes_blueprint.route('/edit_teacher/<int:teacher_id>', methods=['GET', 'POST'])
@login_required
def edit_teacher(teacher_id):
    is_admin()
    teacher = Teacher.query.get_or_404(teacher_id)
    form = TeacherForm(obj=teacher)
    form.site_id.choices = [(s.id, s.site_name) for s in Site.query.order_by(Site.site_name).all()]

    if form.validate_on_submit():
        conflict = Teacher.query.filter(
            Teacher.employee_id == form.employee_id.data.strip(),
            Teacher.id != teacher.id
        ).first()
        if conflict:
            flash('A teacher with this Employee ID already exists.', 'danger')
            return render_template('add_teacher.html', form=form, current_page_name='Edit Teacher')
        teacher.first_name  = form.first_name.data
        teacher.middle_name = form.middle_name.data or None
        teacher.last_name   = form.last_name.data
        teacher.employee_id = form.employee_id.data.strip()
        teacher.email       = form.email.data or None
        teacher.department  = form.department.data or None
        teacher.site_id     = form.site_id.data
        teacher.status      = form.status.data
        db.session.commit()
        flash('Teacher updated successfully!', 'success')
        return redirect(url_for('routes.teacher_details', teacher_id=teacher.id))

    return render_template('add_teacher.html', form=form, current_page_name='Edit Teacher')


@routes_blueprint.route('/delete_teacher/<int:teacher_id>', methods=['POST'])
@login_required
def delete_teacher(teacher_id):
    is_admin()
    teacher = Teacher.query.get_or_404(teacher_id)
    db.session.delete(teacher)
    db.session.commit()
    flash('Teacher deleted successfully!', 'warning')
    return redirect(url_for('routes.teachers'))


# =============================================================================
# COURSES
# =============================================================================

@routes_blueprint.route('/courses', methods=['GET'])
@login_required
def courses():
    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page')
    search       = request.args.get('search', '').strip()
    site_filter  = request.args.get('site_filter', '').strip()
    grade_filter = request.args.get('grade_filter', '').strip()
    dept_filter  = request.args.get('dept_filter', '').strip()

    query = Course.query.join(Teacher, Course.teacher_id == Teacher.id)
    if search:
        query = query.filter(
            db.or_(Course.course_name.ilike(f'%{search}%'),
                   Course.course_code.ilike(f'%{search}%'))
        )
    if site_filter:
        query = query.filter(Course.site_id == site_filter)
    if grade_filter:
        query = query.filter(Course.grade_level == grade_filter)
    if dept_filter:
        query = query.filter(Teacher.department == dept_filter)

    total       = query.count()
    courses_q   = query.order_by(Course.course_name.asc()).offset(offset).limit(per_page).all()
    pagination  = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')
    sites       = Site.query.order_by(Site.site_name.asc()).all()
    departments = sorted({t.department for t in Teacher.query.all() if t.department})

    return render_template('courses.html',
        courses=courses_q, pagination=pagination, per_page=per_page,
        sites=sites, grades=_GRADE_LIST, departments=departments,
        dept_filter=dept_filter, current_page_name='Courses')


@routes_blueprint.route('/add_course', methods=['GET', 'POST'])
@login_required
def add_course():
    return redirect(url_for('routes.courses'))


@routes_blueprint.route('/course/<int:course_id>', methods=['GET'])
@login_required
def course_details(course_id):
    course = Course.query.get_or_404(course_id)
    return render_template('course_details.html', course=course,
                           current_page_name=course.course_name)


@routes_blueprint.route('/edit_course/<int:course_id>', methods=['GET', 'POST'])
@login_required
def edit_course(course_id):
    is_admin()
    course = Course.query.get_or_404(course_id)
    form = CourseForm(obj=course)
    form.teacher_id.choices = [
        (t.id, f'{t.last_name}, {t.first_name}')
        for t in Teacher.query.order_by(Teacher.last_name).all()
    ]
    form.site_id.choices = [(s.id, s.site_name) for s in Site.query.order_by(Site.site_name).all()]

    if form.validate_on_submit():
        conflict = Course.query.filter(
            Course.course_code == form.course_code.data.strip().upper(),
            Course.id != course.id
        ).first()
        if conflict:
            flash('A course with this code already exists.', 'danger')
            return render_template('add_course.html', form=form, current_page_name='Edit Course')
        course.course_name   = form.course_name.data
        course.course_code   = form.course_code.data.strip().upper()
        course.grade_level   = form.grade_level.data or None
        course.period        = form.period.data or None
        course.description   = form.description.data or None
        course.max_students  = form.max_students.data or None
        course.status        = form.status.data
        course.teacher_id    = form.teacher_id.data
        course.site_id       = form.site_id.data
        db.session.commit()
        flash('Course updated successfully!', 'success')
        return redirect(url_for('routes.course_details', course_id=course.id))

    return render_template('add_course.html', form=form, current_page_name='Edit Course')


@routes_blueprint.route('/delete_course/<int:course_id>', methods=['POST'])
@login_required
def delete_course(course_id):
    is_admin()
    course = Course.query.get_or_404(course_id)
    db.session.delete(course)
    db.session.commit()
    flash('Course deleted successfully!', 'warning')
    return redirect(url_for('routes.courses'))


# =============================================================================
# PARENTS
# =============================================================================

@routes_blueprint.route('/parents', methods=['GET'])
@login_required
def parents():
    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page')
    search = request.args.get('search', '').strip()

    query = Parent.query
    if search:
        query = query.filter(
            db.or_(Parent.first_name.ilike(f'%{search}%'),
                   Parent.last_name.ilike(f'%{search}%'),
                   Parent.email.ilike(f'%{search}%'))
        )

    total      = query.count()
    parents_q  = query.order_by(Parent.last_name.asc(), Parent.first_name.asc()).offset(offset).limit(per_page).all()
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')

    return render_template('parents.html',
        parents=parents_q, pagination=pagination, per_page=per_page,
        current_page_name='Parents')


@routes_blueprint.route('/add_parent', methods=['GET', 'POST'])
@login_required
def add_parent():
    return redirect(url_for('routes.parents'))


@routes_blueprint.route('/parent/<int:parent_id>', methods=['GET'])
@login_required
def parent_details(parent_id):
    parent = Parent.query.get_or_404(parent_id)
    return render_template('parent_details.html', parent=parent,
                           current_page_name=f'{parent.first_name} {parent.last_name}')


@routes_blueprint.route('/edit_parent/<int:parent_id>', methods=['GET', 'POST'])
@login_required
def edit_parent(parent_id):
    is_admin()
    parent = Parent.query.get_or_404(parent_id)
    form = ParentForm(obj=parent)
    form.student_ids.choices = [
        (s.id, f'{s.last_name}, {s.first_name} ({s.student_id})')
        for s in Student.query.order_by(Student.last_name).all()
    ]

    if request.method == 'GET':
        form.student_ids.data = [s.id for s in parent.students]

    if form.validate_on_submit():
        parent.first_name   = form.first_name.data
        parent.middle_name  = form.middle_name.data or None
        parent.last_name    = form.last_name.data
        parent.relationship = form.relationship.data
        parent.email        = form.email.data or None
        parent.phone        = form.phone.data or None
        parent.status       = form.status.data
        parent.students     = Student.query.filter(Student.id.in_(form.student_ids.data or [])).all()
        db.session.commit()
        flash('Parent updated successfully!', 'success')
        return redirect(url_for('routes.parent_details', parent_id=parent.id))

    return render_template('add_parent.html', form=form, current_page_name='Edit Parent')


@routes_blueprint.route('/delete_parent/<int:parent_id>', methods=['POST'])
@login_required
def delete_parent(parent_id):
    is_admin()
    parent = Parent.query.get_or_404(parent_id)
    db.session.delete(parent)
    db.session.commit()
    flash('Parent deleted successfully!', 'warning')
    return redirect(url_for('routes.parents'))


