from main import create_app, db
from application.models import Organization, User, Title, Role, Site
from werkzeug.security import generate_password_hash
import re, os
from dotenv import load_dotenv


load_dotenv()
app = create_app()

with app.app_context():
    db.create_all()


    # --- Create or Update Default Organization ---
    # --- Default organization User ---
    school_district_name = os.getenv('DEFAULT_ORGANIZATION_NAME')

    organization = Organization.query.get(1)
    if organization:
        organization.organization_name = school_district_name
        organization.site_version = '1.0'
        print("✅ Organization updated.")
    else:
        organization = Organization(
            id=1,
            organization_name='Default Organization',
            site_version='1.0'
        )
        db.session.add(organization)
        print("✅ Organization created.")

    # --- Default Roles ---
    default_roles = [
        ('1', 'Admin'),
        ('2', 'Specialist'),
        ('3', 'Technician'),
        ('4', 'Teacher'),
        ('5', 'Staff')
    ]
    for role_id, role_name in default_roles:
        existing_role = Role.query.filter_by(role_name=role_name).first()
        if not existing_role:
            db.session.add(Role(id=int(role_id), role_name=role_name))
            print(f"✅ Role added: {role_name}")
        else:
            print(f"⚠️ Role already exists: {role_name}")

    # --- Default Site ---
    default_site_data = {
        'id': 1,
        'site_name': 'District Office',
        'site_GU': 'y655987b8o76987bn9',
        'site_code': '000',
        'site_abb': 'DO',
        'site_cds': '99-99999-9999999',
        'site_address': '1234 Main St.',
        'site_type': 'DO'
    }

    existing_site = Site.query.filter_by(site_cds=default_site_data['site_cds']).first()
    if existing_site:
        for key, value in default_site_data.items():
            setattr(existing_site, key, value)
        print("✅ Default site updated.")
    else:
        db.session.add(Site(**default_site_data))
        print("✅ Default site created.")

    # --- Default Admin User ---
    lead_admin_email = os.getenv('DEFAULT_ADMIN_EMAIL')
    lead_admin_password = os.getenv('DEFAULT_ADMIN_PASSWORD')
    lead_admin_firstn = os.getenv('DEFAULT_ADMIN_FIRST_NAME')
    lead_admin_lastn = os.getenv('DEFAULT_ADMIN_LAST_NAME')


    if not lead_admin_email or not lead_admin_password:
        print("❌ Missing DEFAULT_ADMIN_EMAIL or DEFAULT_ADMIN_PASSWORD in environment.")
    elif len(lead_admin_password) < 10 or \
         not re.search(r'[A-Za-z]', lead_admin_password) or \
         not re.search(r'[0-9]', lead_admin_password) or \
         not re.search(r'[!@#$%^&*(),.?\":{}|<>]', lead_admin_password):
        print("❌ Default password does not meet complexity requirements.")
    else:
        user = User.query.filter_by(email=lead_admin_email).first()
        if user:
            user.first_name = lead_admin_firstn
            user.last_name = 'Wayne'
            user.password = generate_password_hash(lead_admin_password)
            print("✅ Default admin user updated.")
        else:
            user = User(
                id=99,
                first_name=lead_admin_firstn,
                middle_name='',
                last_name=lead_admin_lastn,
                email=lead_admin_email,
                password=generate_password_hash(lead_admin_password),
                status='Active',
                rm_num='999',
                site_id=1,
                role_id=1
            )
            db.session.add(user)
            print("✅ Default admin user created.")

    # --- Default Titles ---
    default_titles = [
        ('1', 'Other'),
        ('2', 'Badge Access/Key Card Issues'),
        ('3', 'Computer - Installation/Issues'),
        ('4', 'Digital Clock/Bell Schedule Sync'),
        ('5', 'Internet - Service Issues'),
        ('6', 'New Email Accounts'),
        ('7', 'Password Reset'),
        ('8', 'Printers Issues'),
        ('9', 'Projector/TV Issues'),
        ('10', 'Security Cameras'),
        ('11', 'SIS - Student Information System'),
        ('12', 'Software - Installation/Issues'),
        ('13', 'Student Website Account'),
        ('14', 'Telephone Issues (Office or Cell)'),
        ('15', 'Web Filter - Blacklist/Whitelist')
    ]


    for title_id, title_name in default_titles:
        existing_title = Title.query.filter_by(title_name=title_name).first()
        if not existing_title:
            db.session.add(Title(id=int(title_id), title_name=title_name))
            print(f"✅ Title added: {title_name}")
        else:
            print(f"⚠️ Title already exists: {title_name}")

    # --- Commit all changes ---
    db.session.commit()
    print("✅ All seed data committed.")
