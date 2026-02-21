from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app, send_from_directory, jsonify
from flask_login import login_user, login_required, logout_user, current_user
from flask_paginate import Pagination, get_page_args
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from .models import User, Role, Site, Notification, Organization, Ticket, Title, Ticket_content, Ticket_attachment
from .forms import LoginForm, UserForm, RoleForm, SiteForm, NotificationForm, OrganizationForm, TicketForm, TitleForm, TicketContentForm
from .utils import validate_password, validate_file_upload
from main import db, login_manager
from datetime import datetime, timedelta, timezone
import time, os, re, csv, logging
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

# *****************************************************************
#-------------------- Core Setup -------------------------
# -------------- Do not change this section --------------
# *****************************************************************

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
    return User.query.get(int(user_id))

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
def login():
    """
    Handle user login requests.
    
    GET: Display the login form
    POST: Process the login form submission
    
    Returns:
        Response: Rendered login template or redirect to index on successful login
    """
    # Fetch organization name for display on login page
    organization = Organization.query.get(1)
    organization_name = organization.organization_name if organization else "AssistITk12"

    # Fetch active notifications to display on login page
    active_notifications = []
    try:
        active_notifications = Notification.query.filter_by(msg_status="active").all()
    except Exception as e:
        print(f"Error fetching notifications: {e}")

    form = LoginForm()
    if form.validate_on_submit():
        # Find user by email and validate password
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user)
            return redirect(url_for('routes.index'))
        else:
            flash('Invalid email or password', 'danger')

    return render_template(
        'login.html',
        active_notifications=active_notifications,
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


# ****************** Change Password *******************************
@routes_blueprint.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """
    Handle password change requests securely.
    
    This function validates the current password, ensures the new password meets
    security requirements, and securely updates the password in the database.
    
    Returns:
        Response: JSON response indicating success or failure
    """
    try:
        # Extract form data
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # Input validation
        if not all([current_password, new_password, confirm_password]):
            return jsonify({"success": False, "message": "All fields are required"}), 400
            
        # Verify new passwords match
        if new_password != confirm_password:
            return jsonify({"success": False, "message": "New passwords do not match"}), 400
        
        # Validate password complexity
        is_valid, error_message = validate_password(new_password)
        if not is_valid:
            return jsonify({"success": False, "message": error_message}), 400
        
        # Get current user
        user = User.query.filter_by(id=current_user.id).first()
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404
            
        # Verify current password is correct
        if not check_password_hash(user.password, current_password):
            # Use consistent timing to prevent timing attacks
            # from time import sleep
            # sleep(0.5)  # Small delay to prevent rapid guessing
            return jsonify({"success": False, "message": "Current password is incorrect"}), 401
            
        # Hash the new password using werkzeug security functions
        password_hash = generate_password_hash(new_password, method='pbkdf2:sha256:150000')
        
        # Update the password in the database
        user.password = password_hash
        
        # Commit the changes to the database
        db.session.commit()
        
        # Log the password change event (but not the password itself)
        current_app.logger.info(f"Password changed for user ID: {user.id}")
        
        # Optionally, update session to require re-login after password change
        # This depends on your security requirements
        # logout_user()
        
        return jsonify({"success": True, "message": "Password changed successfully"}), 200
        
    except Exception as e:
        # Roll back any database changes that might have occurred
        db.session.rollback()
        
        # Log the error, but don't expose details to the user
        current_app.logger.error(f"Password change error: {str(e)}")
        
        # Generic error message to avoid exposing system details
        return jsonify({"success": False, "message": "An error occurred. Please try again later."}), 500


# ****************** Update Organization Page *******************************
@routes_blueprint.route('/organization', methods=['GET', 'POST'])
@login_required
def organization():
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

    if form.validate_on_submit():
        # Check for duplicate organization names (excluding the current one)
        existing_organization = Organization.query.filter(
            Organization.organization_name == form.organization_name.data,
            Organization.id != organization.id
        ).first()

        if existing_organization:
            flash('An organization with that name already exists.', 'danger') 
            return render_template('organization.html', form=form, organization=organization)

        # Update organization with form data
        organization.organization_name = form.organization_name.data
        organization.site_version = form.site_version.data
        db.session.commit()  # Save changes to database
        
        flash('Organization updated successfully!', 'success')
        return redirect(url_for('routes.organization'))

    # For GET requests or invalid form submissions, display the form
    return render_template('organization.html', 
                          form=form, 
                          organization=organization,
                          current_path=current_path, 
                          current_page_name=current_page_name)

# *****************************************************************
#-------------------- END Core Setup ---------------------
# -------------- Do not change this section --------------
# *****************************************************************



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

    # print("Months:", months)
    # print("Ticket Counts:", counts)

    # Fetch active notifications (optional)
    active_notifications = Notification.query.filter_by(msg_status="active").all()

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
        active_notifications=active_notifications,
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
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        # Validate passwords
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
            # Update password and save user
            current_user.password = generate_password_hash(password)
            try:
                db.session.commit()
                flash('Password updated successfully!', 'success')
            except Exception as e:
                flash(f'Error updating password: {str(e)}', 'danger')
                db.session.rollback()
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
    
    # Ensure only admins can access this route
    if current_user.is_admin:
        is_admin()  
    elif current_user.is_tech_role:
        is_tech_role()
    
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
                User.email.ilike(f"%{search}%")
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
        existing_user = User.query.filter_by(email=form.email.data).first()
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
@routes_blueprint.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    
    # Ensure only admins can access this route
    if current_user.is_admin:
        is_admin()  
    elif current_user.is_tech_role:
        is_tech_role()
        
    user = User.query.get_or_404(user_id)
    form = UserForm(obj=user)
    # Populate dynamic choices for role_id and site_id
    form.role_id.choices = [(role.id, role.role_name) for role in Role.query.all()]
    form.site_id.choices = [(site.id, site.site_name) for site in Site.query.all()]
    if form.validate_on_submit():
        # Check if a user with the same email already exists
        existing_user = User.query.filter(User.email == form.email.data, User.id != user.id).first()
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
        if form.password.data:
            password = form.password.data
            is_valid, error_message = validate_password(password)
            if not is_valid:
                flash(error_message, 'danger')
                return render_template('edit_user.html', form=form, user=user)
            user.password = generate_password_hash(password)
            changes_made = True
        # Commit changes only if any were made
        if changes_made:
            db.session.commit()
            flash('User updated successfully!', 'success')
            return redirect(url_for('routes.users'))
        else:
            flash('No changes were made.', 'info')
    return render_template('edit_user.html', form=form, user=user)



# ****************** Delete User Page *******************************
@routes_blueprint.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
# @csrf.exempt  # Optional: Exempt from CSRF if needed
def delete_user(user_id):
    is_admin()  # Ensure only admins can access this route
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully!', 'warning')
    return redirect(url_for('routes.users'))



# ****************** Import Bulk Users *******************************
@routes_blueprint.route('/bulk-upload-users', methods=['POST'])
@login_required
# @csrf.exempt  # Optional: Exempt from CSRF if needed
def bulk_upload_users():
    is_admin()  # Ensure only admins can access this route

    if 'csvFile' not in request.files:
        flash('No file part', 'danger')
        return redirect(url_for('routes.users'))

    file = request.files['csvFile']
    if file.filename == '':
        flash('No selected file', 'danger')
        return redirect(url_for('routes.users'))

    if not file.filename.endswith('.csv'):
        flash('Invalid file format. Please upload a CSV file.', 'danger')
        return redirect(url_for('routes.users'))

    try:
        # Decode the uploaded file
        stream = file.stream.read().decode("UTF-8")
        csv_reader = csv.DictReader(stream.splitlines())

        users_added = 0
        users_updated = 0

        for row in csv_reader:
            # Validate mandatory fields
            if not all([row.get('first_name'), row.get('last_name'), row.get('email'), row.get('role_id'), row.get('site_name'), row.get('rm_num')]):
                flash('Some rows in the CSV file are missing required fields.', 'danger')
                return redirect(url_for('routes.users'))

            # Find the site_id from site_name
            site = Site.query.filter_by(site_name=row['site_name']).first()
            if not site:
                flash(f"Site '{row['site_name']}' not found. Please verify the CSV file.", 'danger')
                return redirect(url_for('routes.users'))

            # Check for existing user
            existing_user = User.query.filter_by(email=row['email']).first()
            if existing_user:
                # Update only the allowed fields
                existing_user.rm_num = row.get('rm_num', existing_user.rm_num)
                existing_user.role_id = row['role_id']
                existing_user.site_id = site.id
                users_updated += 1
            else:
                # Create a new user
                new_user = User(
                    first_name=row['first_name'],
                    middle_name=row.get('middle_name', None),
                    last_name=row['last_name'],
                    email=row['email'],
                    status=row.get('status', 'Active'),
                    password=generate_password_hash('default_password'),  # Default password
                    rm_num=row.get('rm_num', None),
                    role_id=row['role_id'],
                    site_id=site.id
                )
                db.session.add(new_user)
                users_added += 1

        db.session.commit()
        flash(f'Successfully added {users_added} users and updated {users_updated} users.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred while processing the file: {e}', 'danger')

    return redirect(url_for('routes.organization'))




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
# @csrf.exempt  # Optional: Exempt from CSRF if needed
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
            site_GU=form.site_GU.data,
            site_code=form.site_code.data,
            site_abb=form.site_abb.data,
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
            site.site_GU == form.site_GU.data and
            site.site_code == form.site_code.data and
            site.site_abb == form.site_abb.data and
            site.site_cds == form.site_cds.data and
            site.site_address == form.site_address.data and
            site.site_type == form.site_type.data
        ):
            flash('No changes were made.', 'info')
            return render_template('edit_site.html', form=form, site=site)
        site.site_name = form.site_name.data
        site.site_GU = form.site_GU.data
        site.site_code = form.site_code.data
        site.site_abb = form.site_abb.data
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
# @csrf.exempt  # Optional: Exempt from CSRF if needed
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
        # Populate form with submitted data (but we'll override msg_status manually)
        form.populate_obj(notification)

        # Check for duplicate notification name
        existing_notification = Notification.query.filter(
            Notification.msg_name == form.msg_name.data,
            Notification.id != notification.id
        ).first()
        if existing_notification:
            flash('This notification name already exists.', 'danger')
            return render_template('edit_notification.html', form=form, notification=notification)

        # Determine new status based on checkbox (on = 'Active', off = 'Inactive')
        new_status = 'Active' if request.form.get('msg_status') else 'Inactive'

        # Check if no changes were made
        if (
            notification.msg_name == form.msg_name.data and
            notification.msg_content == form.msg_content.data and
            notification.msg_status == new_status
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
        notification.msg_status = new_status
        db.session.commit()
        flash('Notification updated successfully!', 'success')
        return redirect(url_for('routes.notifications'))

    return render_template('edit_notification.html', form=form, notification=notification)



# ****************** Delete Notification Page *********************
@routes_blueprint.route('/delete_notification/<int:notification_id>', methods=['POST'])
@login_required
# @csrf.exempt  # Optional: Exempt from CSRF if needed
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
            created_at=datetime.utcnow()
        )
        db.session.add(ticket)
        db.session.flush()
        
    # Handle file upload (only if file exists and has a valid name)
        uploaded_file = request.files.get('attachment')
        if uploaded_file and uploaded_file.filename:  # Check both file obj and filename
            allowed_extensions = {'.jpg', '.jpeg', '.png', '.pdf'}
            file_ext = os.path.splitext(uploaded_file.filename)[1].lower()

            if file_ext not in allowed_extensions:
                flash('Only JPG, PNG, and PDF files are allowed', 'error')
                return redirect(request.url)

            # Check file size (5MB max)
            uploaded_file.seek(0, os.SEEK_END)
            file_length = uploaded_file.tell()
            uploaded_file.seek(0)  # Reset file pointer

            if file_length > 5 * 1024 * 1024:
                flash('File size exceeds 5MB limit', 'error')
                return redirect(request.url)

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
                    uploaded_at=datetime.utcnow(),
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
                cnt_created_at=datetime.utcnow(),
                user_id=current_user.id
            )
            db.session.add(new_content)

        # Commit all changes at once
        db.session.commit()
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
    filename = attachment.attach_image.split('/')[-1]
    upload_folder = current_app.config['UPLOAD_ATTACHMENT']
    
    # Debug logging
    current_app.logger.debug(f"Looking for file: {filename} in folder: {upload_folder}")
    
    file_path = os.path.join(upload_folder, filename)
    if not os.path.exists(file_path):
        current_app.logger.error(f"File not found at: {file_path}")
        flash('File not found.', 'error')
        return redirect(url_for('routes.tickets'))
    
    return send_from_directory(upload_folder, filename, as_attachment=True)


# ****************** Delete attachment Page *******************************
@routes_blueprint.route('/delete_attachment/<int:attachment_id>', methods=['POST'])
@login_required
def delete_attachment(attachment_id):
    current_app.logger.info(f"Delete attachment request - Attachment ID: {attachment_id}, User: {current_user.id}")
    
    # Find attachment
    attachment = Ticket_attachment.query.get(attachment_id)
    if not attachment:
        flash('Attachment not found.', 'danger')
        return redirect(url_for('routes.dashboard'))
    
    # Get ticket id for redirect
    ticket_id = attachment.ticket_id
    
    # Check permissions (admin, ticket owner, attachment uploader, or assigned user)
    ticket = Ticket.query.get(ticket_id)
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
        ticket.updated_at = datetime.utcnow()  # Update ticket timestamp
        db.session.commit()
        current_app.logger.info(f"Attachment {attachment_id} deleted from database")
        
        flash('Attachment deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting attachment: {str(e)}")
        flash('Error deleting attachment.', 'danger')
    
    return redirect(url_for('routes.edit_ticket', ticket_id=ticket_id))




# ****************** edit Ticket Page *******************************
@routes_blueprint.route('/edit_ticket/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
def edit_ticket(ticket_id):
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

        # Ensure the escalate checkbox is correctly updated
        if 'escalate' in request.form:
            escalate_value = request.form.get('escalate') == '1'  # Convert to boolean
        else:
            escalate_value = False  # Ensure it's set to False when not checked

        if ticket.escalated != escalate_value:
            ticket.escalated = escalate_value
            changes_made = True
            flash(f'Ticket {"escalated" if ticket.escalated else "de-escalated"} successfully!', 'success')

            
        # In both routes, replace the file handling section with this:
        # Handle file upload
        uploaded_file = request.files.get('attachment')
        if uploaded_file and uploaded_file.filename != '':
            # Validate file type
            allowed_extensions = {'.jpg', '.jpeg', '.png', '.pdf'}
            file_ext = os.path.splitext(uploaded_file.filename)[1].lower()
            
            if file_ext not in allowed_extensions:
                flash('Only JPG, PNG, and PDF files are allowed', 'error')
                return redirect(request.url)
            
            # Validate file size (5MB max)
            uploaded_file.seek(0, os.SEEK_END)
            file_length = uploaded_file.tell()
            uploaded_file.seek(0)  # Reset file pointer to start
            
            if file_length > 5 * 1024 * 1024:  # 5MB
                flash('File size exceeds 5MB limit', 'error')
                return redirect(request.url)
            
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
                    uploaded_at=datetime.utcnow(),
                    user_id=current_user.id
                )
                db.session.add(new_attachment)
                changes_made = True
                flash('Attachment added successfully!', 'success')
                
            except Exception as e:
                flash(f'Failed to save attachment: {str(e)}', 'error')
                current_app.logger.error(f"File save failed: {str(e)}")
                if os.path.exists(filepath):
                    os.remove(filepath)
                return redirect(request.url)


            # # Ensure the new attachment is added only if it's different
            # existing_attachment = Ticket_attachment.query.filter_by(ticket_id=ticket.id, attach_image=new_filename).first()
            # if not existing_attachment:
            #     new_attachment = Ticket_attachment(
            #         ticket_id=ticket.id,
            #         attach_image=new_filename,
            #         uploaded_at=datetime.utcnow(),
            #         user_id=current_user.id
            #     )
            #     db.session.add(new_attachment)
            #     changes_made = True
            #     flash('Attachment added successfully!', 'success')

        # Add ticket contents (text-based)
        new_comments = [
            Ticket_content(
                ticket_id=ticket.id,
                content=subform.content.data,
                cnt_created_at=datetime.utcnow(),
                user_id=current_user.id
            ) for subform in form.contents.entries if subform.content.data
        ]

        if new_comments:
            db.session.add_all(new_comments)
            changes_made = True

        if changes_made:
            ticket.updated_at = datetime.utcnow()
            db.session.add(ticket)
            db.session.commit()
            flash('Ticket updated successfully!', 'success')
        else:
            flash('No changes detected to update.', 'warning')

        return redirect(request.url)  # Stay on the same page after the changes
    return render_template('edit_ticket.html', form=form, ticket=ticket)



# ****************** Delete Ticket Page *******************************
@routes_blueprint.route('/delete_ticket/<int:ticket_id>', methods=['POST'])
@login_required
# @csrf.exempt
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
        flash(f'Failed to delete ticket: {str(e)}', 'danger')
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
    total = Title.query.count()
    titles = Title.query.order_by(Title.title_name.asc()).offset(offset).limit(per_page).all()
    # Set up pagination with Bootstrap 5 styling
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')
    return render_template('titles.html', titles=titles, pagination=pagination, per_page=per_page, total=total, 
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
# @csrf.exempt  # Optional: Exempt from CSRF if needed
def delete_title(title_id):
    is_admin()  # Ensure only admins can access this route
    title = Title.query.get_or_404(title_id)
    db.session.delete(title)
    db.session.commit()
    flash('Title deleted successfully!', 'warning')
    return redirect(url_for('routes.titles'))




