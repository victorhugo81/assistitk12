# seed_data.py
import os
from getpass import getpass
from dotenv import load_dotenv

# Adjust these imports if installation/ is not a package or outside PYTHONPATH
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import create_app, db
from application.models import Organization, User, Title, Role, Site

from werkzeug.security import generate_password_hash
from sqlalchemy.exc import SQLAlchemyError






# Load environment variables
load_dotenv()
app = create_app()

admin_email = input("Enter admin email (e.g., admin@yourdomain.edu): ")
admin_password = getpass("Enter admin password (min 10 chars, letters, digits, symbol): ")
admin_first_name = input("Enter admin first name (default: Admin): ") or "Admin"
admin_last_name = input("Enter admin last name (default: User): ") or "User"

with app.app_context():
    try:
        db.create_all()
        
        # --- Organization ---
        school_district_name = os.getenv('DEFAULT_ORGANIZATION_NAME') or 'Default Organization'
        organization = db.session.get(Organization, 1)

        if organization:
            organization.organization_name = school_district_name
            organization.site_version = '1.0'
            print("✅ Organization updated.")
        else:
            organization = Organization(id=1, organization_name=school_district_name, site_version='1.0')
            db.session.add(organization)
            print("✅ Organization created.")

        # --- Roles ---
        roles = [
            ('1', 'Admin'),
            ('2', 'Specialist'),
            ('3', 'Technician'),
            ('4', 'Teacher'),
            ('5', 'Staff')
        ]
        for role_id, role_name in roles:
            if not Role.query.filter_by(role_name=role_name).first():
                db.session.add(Role(id=int(role_id), role_name=role_name))
                print(f"✅ Role added: {role_name}")
            else:
                print(f"⚠️ Role already exists: {role_name}")

        # --- Site ---
        site_data = {
            'id': 1,
            'site_name': 'District Office',
            'site_GU': 'y655987b8o76987bn9',
            'site_code': '000',
            'site_abb': 'DO',
            'site_cds': '99-99999-9999999',
            'site_address': '1234 Main St.',
            'site_type': 'DO'
        }
        existing_site = Site.query.filter_by(site_cds=site_data['site_cds']).first()
        if existing_site:
            for key, value in site_data.items():
                setattr(existing_site, key, value)
            print("✅ Site updated.")
        else:
            db.session.add(Site(**site_data))
            print("✅ Site created.")

        # --- Admin User ---
        user = User.query.filter_by(email=admin_email).first()
        if user:
            user.first_name = admin_first_name
            user.last_name = admin_last_name
            user.password = generate_password_hash(admin_password)
            print("✅ Admin user updated.")
        else:
            db.session.add(User(
                first_name=admin_first_name,
                middle_name='',
                last_name=admin_last_name,
                email=admin_email,
                password=generate_password_hash(admin_password),
                status='Active',
                rm_num='999',
                site_id=1,
                role_id=1
            ))
            print("✅ Admin user created.")

        # --- Titles ---
        titles = [
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
        for title_id, title_name in titles:
            if not Title.query.filter_by(title_name=title_name).first():
                db.session.add(Title(id=int(title_id), title_name=title_name))
                print(f"✅ Title added: {title_name}")
            else:
                print(f"⚠️ Title already exists: {title_name}")

        db.session.commit()
        print("✅ All data seeded successfully.")

    except SQLAlchemyError as err:
        db.session.rollback()
        print(f"❌ SQLAlchemy Error: {err}")
