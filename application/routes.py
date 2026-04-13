from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app, send_from_directory, jsonify, session
from flask_limiter.util import get_remote_address
from flask_login import login_user, login_required, logout_user, current_user
from flask_paginate import Pagination, get_page_args
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from .models import User, Role, Site, Notification, Organization, Ticket, Title, Ticket_content, Ticket_attachment, BulkUploadLog
from .forms import LoginForm, UserForm, RoleForm, SiteForm, NotificationForm, OrganizationForm, EmailConfigForm, TicketForm, TitleForm, TicketContentForm
from .utils import validate_password, validate_file_upload, encrypt_mail_password, decrypt_mail_password, hash_email
from .email_utils import send_ticket_notification, send_temp_password_email, send_password_updated_email
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
    # Mapping paths to page names
    page_names = {'/': 'Dashboard'}
    current_path = request.path
    current_page_name = page_names.get(current_path, 'Unknown Page')

    # Get the current user's details
    current_user_role = current_user.role_id
    current_user_site_id = current_user.site_id
    current_user_id = current_user.id

    # Get the current year and selected year from query parameters
    current_year = datetime.now().year
    selected_year = request.args.get('year', type=int)  # Default is None for "All Years"

    # Fetch available years dynamically from ticket data
    available_years = sorted([
        int(year[0]) for year in Ticket.query.with_entities(
            db.func.extract('year', Ticket.created_at).distinct()
        ).all()
    ], reverse=True)


    # Role-based site filtering 
    if current_user_role in [1, 2]:  # Admin or Manager
        sites = Site.query.all()
        selected_site_id = request.args.get('site_id', type=int)  # Selected site from dropdown        
    elif current_user_role == 3:  # Limited user
        sites = Site.query.filter_by(id=current_user_site_id).all()
        selected_site_id = current_user_site_id
    else:  # Regular user
        sites = Site.query.filter_by(id=current_user_site_id).all()
        selected_site_id = current_user_site_id

    # Base query filter
    query_filter = []
    if selected_year:  # If a specific year is selected, filter by year
        query_filter.append(db.func.extract('year', Ticket.created_at) == selected_year)

    # Query ticket counts based on role and filters
    if current_user_role in [1, 2]:  # Admin or Manager
        if selected_site_id:  # Filter by selected site
            query_filter.append(Ticket.site_id == selected_site_id)
        pending_count = Ticket.query.filter(Ticket.tck_status == '1-pending', *query_filter).count()
        in_progress_count = Ticket.query.filter(Ticket.tck_status == '2-progress', *query_filter).count()
        completed_count = Ticket.query.filter(Ticket.tck_status == '3-completed', *query_filter).count()
    elif current_user_role == 3:  # Limited user: tickets for their site
        query_filter.append(Ticket.site_id == current_user_site_id)
        pending_count = Ticket.query.filter(Ticket.tck_status == '1-pending', *query_filter).count()
        in_progress_count = Ticket.query.filter(Ticket.tck_status == '2-progress', *query_filter).count()
        completed_count = Ticket.query.filter(Ticket.tck_status == '3-completed', *query_filter).count()
    else:  # Regular user: only their own tickets
        query_filter.append(Ticket.user_id == current_user_id)
        pending_count = Ticket.query.filter(Ticket.tck_status == '1-pending', *query_filter).count()
        in_progress_count = Ticket.query.filter(Ticket.tck_status == '2-progress', *query_filter).count()
        completed_count = Ticket.query.filter(Ticket.tck_status == '3-completed', *query_filter).count()

    # Calculate the total count
    total_count = pending_count + in_progress_count + completed_count

    # Query to get the top 5 most popular titles with filters applied
    top_titles_query = (
        db.session.query(Title.title_name,func.count(Ticket.id).label('ticket_count'))
        .join(Ticket, Title.id == Ticket.title_id).filter(*query_filter)  # Apply the filters
        .group_by(Title.title_name).order_by(func.count(Ticket.id).desc()).limit(5).all())

    # Add an index to the top_titles data
    top_titles = [
        {"rank": idx + 1, "title_name": title_name, "ticket_count": ticket_count}
        for idx, (title_name, ticket_count) in enumerate(top_titles_query)
    ]

    # Initialize counts for all 12 months
    ticket_counts = {month: 0 for month in range(1, 13)}

    # Fetch tickets and count them per month
    for ticket in db.session.query(Ticket).filter(*query_filter).all():
        month = ticket.created_at.month  # Ensure this is between 1 and 12
        if 1 <= month <= 12:  # Extra safeguard
            ticket_counts[month] += 1

    # Use full month names for clarity
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    counts = [ticket_counts[month] for month in range(1, 13)]  # Ensure all 12 months are included

        # Fetch ticket counts for each weekday (Monday to Friday) for the bar chart
    weekday_counts = {day: 0 for day in range(1, 6)}  # Initialize counts for Monday to Friday
    for ticket in db.session.query(Ticket).filter(*query_filter).all():
        weekday = ticket.created_at.weekday() + 1  # Monday = 1, Sunday = 7
        if weekday in weekday_counts:
            weekday_counts[weekday] += 1

    weekdays = ["M", "T", "W", "Th", "F"]
    weekday_counts_list = [weekday_counts[day] for day in range(1, 6)]


    # Render the template with the context
    return render_template(
        'index.html',
        available_years=available_years,
        selected_year=selected_year,
        sites=sites,
        current_page_name=current_page_name,
        selected_site_id=selected_site_id,
        pending_count=pending_count,
        in_progress_count=in_progress_count,
        completed_count=completed_count,
        total_count=total_count,
        top_titles=top_titles,
        months=months,
        counts=counts,
        weekdays=weekdays,
        weekday_counts=weekday_counts_list
    )


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




# *********************************************************************
# ****************** Tickets Management Page *******************************
@routes_blueprint.route('/tickets', methods=['GET'])
@login_required
def tickets():
    # Mapping paths to page names
    page_names = {'/tickets': 'Manage Tickets'}
    current_path = request.path
    current_page_name = page_names.get(current_path, 'Unknown Page')

    # Get query parameters
    site_filter = request.args.get('site_filter', '')
    status_filter = request.args.get('status_filter', '').strip()
    assigned_user_filter = request.args.get('assigned_user_filter', '')

    # Fetch the current user's role and site information
    current_user_role_id = current_user.role_id  
    current_user_site_id = current_user.site_id  

    # Start the query with explicit joins
    query = Ticket.query.join(User, Ticket.user_id == User.id).join(Site, Site.id == User.site_id)

    # Apply role-specific filtering
    if current_user_role_id == 3:
        query = query.filter(Site.id == current_user_site_id)
    elif current_user_role_id not in [1, 2, 3]:
        query = query.filter(Site.id == current_user_site_id, Ticket.user_id == current_user.id)

    # Apply site filter if provided
    if site_filter:
        try:
            query = query.filter(Site.id == int(site_filter))
        except ValueError:
            pass

    # Apply status filter
    if status_filter:
        query = query.filter(Ticket.tck_status == status_filter)
    
    # Apply assigned user filter
    if assigned_user_filter:
        try:
            query = query.filter(Ticket.assigned_to_id == int(assigned_user_filter))
        except ValueError:
            pass

    # Pagination setup
    page, per_page, offset = get_page_args(page_parameter="page", per_page_parameter="per_page")
    total = query.count()

    # Sorting logic
    order_by_clause = [
        case(
            # Priority 1: Open and escalated (highest priority)
            ((Ticket.tck_status == "1-pending") & (Ticket.escalated == 1), 1),
            # Priority 2: In progress and escalated
            ((Ticket.tck_status == "2-progress") & (Ticket.escalated == 1), 2),
            # Priority 3: Open and not escalated
            ((Ticket.tck_status == "1-pending") & (Ticket.escalated == 0), 3),
            # Priority 4: In progress and not escalated
            ((Ticket.tck_status == "2-progress") & (Ticket.escalated == 0), 4),
            # Default case
            else_=5
        ),
        Ticket.created_at.desc()  # For tickets with same priority, sort by most recent
    ]

    # Apply ordering
    tickets = query.order_by(*order_by_clause).offset(offset).limit(per_page).all()

    # Fetch sites for the dropdown
    if current_user_role_id in [1, 2]:
        sites = Site.query.order_by(Site.site_name).all()
    else:
        sites = Site.query.filter_by(id=current_user_site_id).order_by(Site.site_name).all()

    # Define status choices
    status_choices = [
        ('1-pending', 'Pending'),
        ('2-progress', 'In Progress'),
        ('3-completed', 'Completed')
    ]

    # Fetch only users with role_id 1 (admin) or 2 (specialist) for assigned user filter - tickets.html
    assigned_users = User.query.filter(User.role_id.in_([1, 2, 3])).order_by(User.first_name).all()

    # Pagination setup - tickets.html
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')

    return render_template(
        'tickets.html',
        tickets=tickets,
        pagination=pagination,
        per_page=per_page,
        total=total,
        current_path=current_path,
        current_page_name=current_page_name,
        statuses=status_choices,
        sites=sites,
        assigned_users=assigned_users  # Pass filtered users
    )







# ****************** Add Ticket Page *******************************
@routes_blueprint.route('/add_ticket', methods=['GET', 'POST'])
@login_required
def add_ticket():
    # Mapping paths to page names
    page_names = {'/add_ticket': 'New Tickets'}
    current_path = request.path
    current_page_name = page_names.get(current_path, 'Unknown Page')

    form = TicketForm()
    titles = Title.query.order_by(Title.title_name).all()  # Get all titles sorted by name
    tech_users = User.query.filter(User.role_id.in_([2, 3])).all()
    form.title_id.choices = [(title.id, title.title_name) for title in titles]
    form.assigned_to_id.choices = [(user.id, user.get_full_name()) for user in tech_users]
    
    if form.validate_on_submit():
        # Ensure site_id is set based on the logged-in user's site_id
        site_id = current_user.site_id  # Use current user's site_id directly
        # Find a user with role_id=3 in the same site to auto-assign
        assignee = User.query.filter_by(role_id=3, site_id=site_id).first()
        # Create new ticket
        ticket = Ticket(
            title_id=form.title_id.data,
            tck_status="1-pending",  # Ensure it's always 'Pending'
            assigned_to_id=assignee.id if assignee else None,
            escalated = 0,
            user_id=current_user.id,
            site_id=site_id,  # Assign site_id directly from current_user
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(ticket)
        db.session.flush()
        
    # Handle file upload
        uploaded_file = request.files.get('attachment')
        if uploaded_file and uploaded_file.filename:
            is_valid, error_message = validate_file_upload(uploaded_file)
            if not is_valid:
                flash(error_message, 'error')
                return redirect(request.url)

            file_ext = os.path.splitext(uploaded_file.filename)[1].lower()
            # Generate a unique filename
            new_filename = f"ticket_{ticket.id}_{datetime.now().strftime('%Y%m%d-%H%M%S')}{file_ext}"
            filename = secure_filename(new_filename)
            upload_folder = current_app.config['UPLOAD_ATTACHMENT']
            os.makedirs(upload_folder, exist_ok=True)
            filepath = os.path.join(upload_folder, filename)

            # Save the file to disk
            uploaded_file.save(filepath)

            # Verify the file was saved correctly
            if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
                flash('Failed to save attachment (empty file)', 'error')
                return redirect(request.url)

            # Check if this attachment already exists (prevent duplicates)
            existing_attachment = Ticket_attachment.query.filter_by(
                ticket_id=ticket.id,
                attach_image=filename
            ).first()

            if not existing_attachment:  # Only add if it doesn't exist
                new_attachment = Ticket_attachment(
                    ticket_id=ticket.id,
                    attach_image=filename,
                    uploaded_at=datetime.now(timezone.utc),
                    user_id=current_user.id
                )
                db.session.add(new_attachment)
            else:
                flash('This attachment already exists.', 'warning')

        # Add initial comment (if any)
        initial_comment = request.form.get('initial_comment')
        if initial_comment:
            new_content = Ticket_content(
                ticket_id=ticket.id,
                content=initial_comment,
                cnt_created_at=datetime.now(timezone.utc),
                user_id=current_user.id
            )
            db.session.add(new_content)

        # Commit all changes at once
        db.session.commit()
        send_ticket_notification('created', ticket, initial_comment=initial_comment or '')
        flash('Ticket created successfully!', 'success')
        return redirect(url_for('routes.tickets'))
    
    return render_template('add_ticket.html', form=form, titles=titles, 
        current_path=current_path,
        current_page_name=current_page_name
        )




@routes_blueprint.route('/download_attachment/<int:attachment_id>')
@login_required
def download_attachment(attachment_id):
    attachment = Ticket_attachment.query.get_or_404(attachment_id)
    ticket = Ticket.query.get_or_404(attachment.ticket_id)

    # Only allow: admins/tech roles, the ticket creator, or the assigned user
    if (current_user.role_id not in [1, 2, 3]
            and current_user.id != ticket.user_id
            and current_user.id != ticket.assigned_to_id):
        abort(403)

    filename = attachment.attach_image.split('/')[-1]
    upload_folder = current_app.config['UPLOAD_ATTACHMENT']

    file_path = os.path.join(upload_folder, filename)
    if not os.path.exists(file_path):
        current_app.logger.error(f"Attachment not found at: {file_path}")
        flash('File not found.', 'error')
        return redirect(url_for('routes.tickets'))

    return send_from_directory(upload_folder, filename, as_attachment=True)


# ****************** Delete attachment Page *******************************
@routes_blueprint.route('/delete_attachment/<int:attachment_id>', methods=['POST'])
@login_required
def delete_attachment(attachment_id):
    current_app.logger.info(f"Delete attachment request - Attachment ID: {attachment_id}, User: {current_user.id}")
    
    # Find attachment
    attachment = db.session.get(Ticket_attachment, attachment_id)
    if not attachment:
        flash('Attachment not found.', 'danger')
        return redirect(url_for('routes.dashboard'))
    
    # Get ticket id for redirect
    ticket_id = attachment.ticket_id
    
    # Check permissions (admin, ticket owner, attachment uploader, or assigned user)
    ticket = db.session.get(Ticket, ticket_id)
    if not (current_user.role_id in [1, 2, 3] or 
            current_user.id == ticket.user_id or
            current_user.id == attachment.user_id or
            current_user.id == ticket.assigned_to_id):
        flash('You do not have permission to delete this attachment.', 'danger')
        return redirect(url_for('routes.edit_ticket', ticket_id=ticket_id))
    
    try:
        # Get filename for file deletion
        if '/' in attachment.attach_image:
            filename = attachment.attach_image.split('/')[-1]
        else:
            filename = attachment.attach_image
        
        # Get filepath
        file_path = os.path.join(current_app.config['UPLOAD_ATTACHMENT'], filename)
        current_app.logger.debug(f"Attempting to delete file: {file_path}")
        
        # Delete physical file if it exists
        if os.path.exists(file_path):
            os.remove(file_path)
            current_app.logger.info(f"File deleted successfully: {file_path}")
        
        # Delete database record
        db.session.delete(attachment)
        ticket.updated_at = datetime.now(timezone.utc)  # Update ticket timestamp
        db.session.commit()
        current_app.logger.info(f"Attachment {attachment_id} deleted from database")
        
        flash('Attachment deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting attachment {attachment_id}: {str(e)}")
        flash('Error deleting attachment.', 'danger')
    
    return redirect(url_for('routes.edit_ticket', ticket_id=ticket_id))




# ****************** edit Ticket Page *******************************
@routes_blueprint.route('/edit_ticket/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
def edit_ticket(ticket_id):
    current_path = request.path
    current_page_name = 'Manage Ticket'

    ticket = Ticket.query.options(db.joinedload(Ticket.contents)).get_or_404(ticket_id)

    # Permission check
    if current_user.role_id not in [1, 2, 3] and current_user.id != ticket.user_id:
        flash('You do not have permission to edit this ticket.', 'danger')
        return redirect(url_for('routes.tickets'))

    form = TicketForm(obj=ticket)
    titles = Title.query.all()
    tech_users = User.query.filter(User.role_id.in_([2, 3])).all()
    form.title_id.choices = [(title.id, title.title_name) for title in titles]
    form.assigned_to_id.choices = [(user.id, user.get_full_name()) for user in tech_users]
    form.escalate.data = ticket.escalated

    if form.validate_on_submit():
        changes_made = False

        # Capture old values before any changes for email notifications
        old_status = ticket.tck_status
        old_assigned_to_id = ticket.assigned_to_id
        old_escalated = bool(ticket.escalated)

        # Check for changes in ticket fields
        if ticket.title_id != form.title_id.data:
            ticket.title_id = form.title_id.data
            changes_made = True
        if ticket.tck_status != form.tck_status.data:
            ticket.tck_status = form.tck_status.data
            changes_made = True
        if ticket.assigned_to_id != form.assigned_to_id.data:
            ticket.assigned_to_id = form.assigned_to_id.data
            changes_made = True

        # Only Admin, Specialist, and Technician can escalate/de-escalate
        if current_user.role_id in [1, 2, 3]:
            if 'escalate' in request.form:
                escalate_value = request.form.get('escalate') == '1'
            else:
                escalate_value = False

            if ticket.escalated != escalate_value:
                ticket.escalated = escalate_value
                changes_made = True
                flash(f'Ticket {"escalated" if ticket.escalated else "de-escalated"} successfully!', 'success')

            
        # Handle file upload
        uploaded_file = request.files.get('attachment')
        if uploaded_file and uploaded_file.filename != '':
            is_valid, error_message = validate_file_upload(uploaded_file)
            if not is_valid:
                flash(error_message, 'error')
                return redirect(request.url)

            file_ext = os.path.splitext(uploaded_file.filename)[1].lower()
            # Create filename with ticket ID
            new_filename = f"ticket_{ticket.id}_{datetime.now().strftime('%Y%m%d-%H%M%S')}{file_ext}"
            filename = secure_filename(new_filename)
            upload_folder = current_app.config['UPLOAD_ATTACHMENT']
            os.makedirs(upload_folder, exist_ok=True)
            filepath = os.path.join(upload_folder, filename)
            
            try:
                uploaded_file.save(filepath)
                # Verify file was saved
                if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
                    raise Exception("File saved as 0 bytes")
                    
                new_attachment = Ticket_attachment(
                    ticket_id=ticket.id,
                    attach_image=filename,
                    uploaded_at=datetime.now(timezone.utc),
                    user_id=current_user.id
                )
                db.session.add(new_attachment)
                changes_made = True
                flash('Attachment added successfully!', 'success')
                
            except Exception as e:
                current_app.logger.error(f"File save failed for ticket {ticket.id}: {e}", exc_info=True)
                flash('Failed to save attachment. Please try again.', 'danger')
                if os.path.exists(filepath):
                    os.remove(filepath)
                return redirect(request.url)

        # Add ticket contents (text-based)
        new_comments = [
            Ticket_content(
                ticket_id=ticket.id,
                content=subform.content.data,
                cnt_created_at=datetime.now(timezone.utc),
                user_id=current_user.id
            ) for subform in form.contents.entries if subform.content.data
        ]

        if new_comments:
            db.session.add_all(new_comments)
            changes_made = True

        if changes_made:
            ticket.updated_at = datetime.now(timezone.utc)
            db.session.add(ticket)
            db.session.commit()

            # Send email notifications for each change
            if ticket.tck_status != old_status:
                send_ticket_notification('status', ticket,
                                         old_status=old_status,
                                         new_status=ticket.tck_status)
            if ticket.assigned_to_id != old_assigned_to_id:
                new_assignee = db.session.get(User, ticket.assigned_to_id) if ticket.assigned_to_id else None
                send_ticket_notification('assigned', ticket, new_assignee=new_assignee)
            if bool(ticket.escalated) != old_escalated:
                send_ticket_notification('escalated', ticket, escalated=bool(ticket.escalated))
            if new_comments:
                send_ticket_notification('comment', ticket, commenter=current_user,
                                         comment_text=new_comments[-1].content)

            flash('Ticket updated successfully!', 'success')
        else:
            flash('No changes detected to update.', 'warning')

        return redirect(request.url)  # Stay on the same page after the changes
    return render_template('edit_ticket.html', form=form, ticket=ticket,
        current_path=current_path,
        current_page_name=current_page_name
        )




# ****************** Add Comment (AJAX) *******************************
@routes_blueprint.route('/add_comment/<int:ticket_id>', methods=['POST'])
@login_required
def add_comment(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)

    if current_user.role_id not in [1, 2, 3] and current_user.id != ticket.user_id:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    content = request.form.get('content', '').strip()
    if not content:
        return jsonify({'success': False, 'message': 'Comment cannot be empty'}), 400

    try:
        comment = Ticket_content(
            ticket_id=ticket.id,
            content=content,
            cnt_created_at=datetime.now(timezone.utc),
            user_id=current_user.id
        )
        db.session.add(comment)
        ticket.updated_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"add_comment failed: {e}")
        return jsonify({'success': False, 'message': 'Database error saving comment'}), 500

    send_ticket_notification('comment', ticket, commenter=current_user, comment_text=content)

    return jsonify({
        'success': True,
        'comment': {
            'author': current_user.get_full_name(),
            'date': comment.cnt_created_at.strftime('%m-%d-%Y %H:%M'),
            'content': content
        }
    })


# ****************** Delete Ticket Page *******************************
@routes_blueprint.route('/delete_ticket/<int:ticket_id>', methods=['POST'])
@login_required
def delete_ticket(ticket_id):
    is_admin()  # Ensure only admins can access this route
    ticket = Ticket.query.get_or_404(ticket_id)

    try:
        # Log ticket deletion
        current_app.logger.info(f"Deleting ticket ID: {ticket_id} by user: {current_user.id}")
        
        # Get all attachments for this ticket
        attachments = Ticket_attachment.query.filter_by(ticket_id=ticket_id).all()
        current_app.logger.debug(f"Found {len(attachments)} attachments to delete for ticket {ticket_id}")

        for attachment in attachments:
            if attachment.attach_image:
                # Extract filename safely
                filename = attachment.attach_image.split('/')[-1] if '/' in attachment.attach_image else attachment.attach_image
                
                # Construct full file path
                file_path = os.path.join(current_app.config['UPLOAD_ATTACHMENT'], filename)
                current_app.logger.debug(f"Attempting to delete file: {file_path}")
                
                # Verify and delete file
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        current_app.logger.info(f"File deleted successfully: {file_path}")
                    except OSError as e:
                        current_app.logger.error(f"Error deleting file {file_path}: {str(e)}")
                        raise  # Re-raise to trigger rollback
                else:
                    current_app.logger.warning(f"File not found: {file_path} (may have been deleted already)")
                
                # Delete attachment record
                db.session.delete(attachment)
                current_app.logger.debug(f"Attachment {attachment.id} marked for deletion")

        # Delete the ticket
        db.session.delete(ticket)
        db.session.commit()
        current_app.logger.info(f"Ticket {ticket_id} and attachments deleted successfully")
        
        flash('Ticket and all attachments deleted successfully', 'success')
        return redirect(url_for('routes.tickets'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting ticket {ticket_id}: {str(e)}", exc_info=True)
        flash('An error occurred while deleting the ticket. Please try again.', 'danger')
        return redirect(url_for('routes.tickets'))



# *********************************************************************
# ****************** Title Management Page *******************************
@routes_blueprint.route('/titles')
@login_required
def titles():
        # Mapping paths to page names
    page_names = {'/titles': 'Manage Ticket Titles'}
    current_path = request.path
    current_page_name = page_names.get(current_path, 'Unknown Page')
    is_admin()  # Ensure only admins can access this route
    # Get the page number and per_page from the query parameters, default to 10 for per_page
    page, per_page, offset = get_page_args(page_parameter="page", per_page_parameter="per_page")
    # Query the users
    sort = request.args.get('sort', 'asc')
    order = Title.title_name.desc() if sort == 'desc' else Title.title_name.asc()
    total = Title.query.count()
    titles = Title.query.order_by(order).offset(offset).limit(per_page).all()
    # Set up pagination with Bootstrap 5 styling
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')
    return render_template('titles.html', titles=titles, pagination=pagination, per_page=per_page, total=total,
        sort=sort,
        current_path=current_path,
        current_page_name=current_page_name
    )


# ****************** Add Title Page *******************************
@routes_blueprint.route('/add_title', methods=['GET', 'POST'])
@login_required
def add_title():
        # Mapping paths to page names
    page_names = {'/add_title': 'New Ticket Title'}
    current_path = request.path
    current_page_name = page_names.get(current_path, 'Unknown Page')
    is_admin()  # Ensure only admins can access this route
    form = TitleForm()
    if form.validate_on_submit():
        # Check if a title with the same name already exists
        existing_title = Title.query.filter_by(title_name=form.title_name.data).first()
        if existing_title:
            flash('This title already exists.', 'danger')
            return render_template('add_title.html', form=form)  # Re-render form with the error message
        # Create and add the new title
        new_title = Title(
            title_name=form.title_name.data
        )
        db.session.add(new_title)
        db.session.commit()
        flash('Title added successfully!', 'success')
        return redirect(url_for('routes.titles'))
    return render_template('add_title.html', form=form, 
        current_path=current_path, 
        current_page_name=current_page_name
    )

# ****************** Edit Title Page *******************************
@routes_blueprint.route('/edit_title/<int:title_id>', methods=['GET', 'POST'])
@login_required
def edit_title(title_id):
    is_admin()  # Ensure only admins can access this route
    title = Title.query.get_or_404(title_id)
    form = TitleForm(obj=title)
    if form.validate_on_submit():
        # Check for duplicate entries
        existing_title = Title.query.filter(Title.title_name == form.title_name.data, Title.id != title.id).first()
        if existing_title:
            flash('This title already exists.', 'danger')
            return render_template('add_title.html', form=form)  # Re-render form with the error message
        # Check if there are any changes to the form
        if (
            title.title_name == form.title_name.data
        ):
            flash('No changes were made.', 'info')
            return render_template('edit_title.html', form=form, title=title)
        title.title_name = form.title_name.data
        db.session.commit()
        flash('Title updated successfully!', 'success')
        return redirect(url_for('routes.titles'))
    return render_template('edit_title.html', form=form, title=title)

# ****************** Delete Title Page *******************************
@routes_blueprint.route('/delete_title/<int:title_id>', methods=['POST'])
@login_required
def delete_title(title_id):
    is_admin()  # Ensure only admins can access this route
    title = Title.query.get_or_404(title_id)
    db.session.delete(title)
    db.session.commit()
    flash('Title deleted successfully!', 'warning')
    return redirect(url_for('routes.titles'))




