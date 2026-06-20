from main import db  # Import db from main.py where it's initialized
from flask_login import UserMixin
from datetime import datetime, timezone


def _utcnow():
    """Return current UTC time as a naive datetime (compatible with legacy DateTime columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    organization_name = db.Column(db.String(100), nullable=False)
    site_version = db.Column(db.String(100), nullable=False)
    organization_logo = db.Column(db.String(100), nullable=True)
    # Flask-Mail configuration
    mail_server = db.Column(db.String(255), nullable=True)
    mail_port = db.Column(db.Integer, nullable=True)
    mail_use_tls = db.Column(db.Boolean, default=False, nullable=True)
    mail_use_ssl = db.Column(db.Boolean, default=False, nullable=True)
    mail_username = db.Column(db.String(255), nullable=True)
    mail_password = db.Column(db.String(255), nullable=True)
    mail_default_sender = db.Column(db.String(255), nullable=True)
    # FTP configuration (host, username, password stored encrypted)
    ftp_host_enc = db.Column(db.String(512), nullable=True)
    ftp_port = db.Column(db.Integer, default=21, nullable=True)
    ftp_username_enc = db.Column(db.String(512), nullable=True)
    ftp_password_enc = db.Column(db.String(512), nullable=True)
    ftp_path = db.Column(db.String(512), nullable=True)
    ftp_use_tls = db.Column(db.Boolean, default=False, nullable=True)
    # FTP schedule
    ftp_schedule_enabled = db.Column(db.Boolean, default=False, nullable=True)
    ftp_schedule_hour    = db.Column(db.Integer, nullable=True)
    ftp_schedule_minute  = db.Column(db.Integer, default=0, nullable=True)
    ftp_schedule_days    = db.Column(db.String(50), default='*', nullable=True)  # '*' or 'mon,tue,...'
    ftp_last_run_at      = db.Column(db.DateTime, nullable=True)
    ftp_last_run_status  = db.Column(db.String(20), nullable=True)
    ftp_schedule_start_date = db.Column(db.Date, nullable=True)
    ftp_schedule_stop_date  = db.Column(db.Date, nullable=True)
    # Dashboard card visibility
    show_demographics     = db.Column(db.Boolean, default=True, nullable=False, server_default='1')
    show_absenteeism      = db.Column(db.Boolean, default=True, nullable=False, server_default='1')
    show_discipline       = db.Column(db.Boolean, default=True, nullable=False, server_default='1')
    show_swd              = db.Column(db.Boolean, default=True, nullable=False, server_default='1')
    show_registration     = db.Column(db.Boolean, default=True, nullable=False, server_default='1')
    show_enrollment       = db.Column(db.Boolean, default=True, nullable=False, server_default='1')
    show_attendance_rates = db.Column(db.Boolean, default=True, nullable=False, server_default='1')


class Grade(db.Model):
    __tablename__ = 'grade'
    id                = db.Column(db.Integer, primary_key=True, autoincrement=True)
    grades_stuid      = db.Column(db.String(50),  nullable=False, index=True)
    grades_schoolid   = db.Column(db.String(100), nullable=True)
    grades_coursenum  = db.Column(db.String(50),  nullable=True)
    grades_teacherid  = db.Column(db.String(50),  nullable=True)
    grades_courseyr   = db.Column(db.String(20),  nullable=True)
    grades_term       = db.Column(db.String(20),  nullable=True)
    grades_grade      = db.Column(db.String(5),   nullable=True)
    grades_mark       = db.Column(db.Numeric(5, 2), nullable=True)
    grades_type       = db.Column(db.String(20),  nullable=True)
    grades_credatt    = db.Column(db.Numeric(5, 2), nullable=True)
    grades_credcomp   = db.Column(db.Numeric(5, 2), nullable=True)
    grades_currgrade  = db.Column(db.String(5),   nullable=True)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    msg_name = db.Column(db.String(100), unique=True, nullable=False)
    msg_content = db.Column(db.String(255), nullable=False)
    msg_status = db.Column(db.String(10), nullable=False)


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    first_name = db.Column(db.String(50), nullable=False)
    middle_name = db.Column(db.String(50), nullable=True)
    last_name = db.Column(db.String(50), nullable=False)
    email_enc  = db.Column(db.Text, nullable=False)
    email_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    status = db.Column(db.String(120), nullable=False)

    @property
    def email(self):
        from flask import current_app
        from application.utils import decrypt_mail_password
        return decrypt_mail_password(self.email_enc or '', current_app.config['SECRET_KEY'])

    @email.setter
    def email(self, value):
        from flask import current_app
        from application.utils import encrypt_mail_password, hash_email
        key = current_app.config['SECRET_KEY']
        self.email_enc = encrypt_mail_password(value or '', key)
        self.email_hash = hash_email(value or '', key)
    password = db.Column(db.String(255), nullable=False)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)
    rm_num = db.Column(db.String(45), nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id', ondelete='CASCADE'), nullable=False)
    site_id = db.Column(db.Integer, db.ForeignKey('site.id', ondelete='CASCADE'), nullable=False)

    def get_full_name(self):
        return f"{self.first_name} {self.middle_name or ''} {self.last_name}".strip()
    
    @property
    def is_admin(self):
        return self.role and self.role.role_name.lower() == "admin"

    @property
    def is_tech_role(self):
        return self.role and self.role.role_name.lower() in ["specialist", "technician"]


class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    role_name = db.Column(db.String(50), unique=True, nullable=False)
    users = db.relationship('User', backref='role', lazy=True)


class Site(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    site_name = db.Column(db.String(100), nullable=False, unique=True)
    site_acronyms = db.Column(db.String(36), nullable=False)
    site_cds = db.Column(db.String(100), nullable=False)
    site_code = db.Column(db.String(100), nullable=False)
    site_address = db.Column(db.String(100), nullable=False)
    site_type = db.Column(db.String(100), nullable=False)
    users = db.relationship('User', backref='site', lazy=True)


# Association tables for many-to-many relationships
student_course = db.Table('student_course',
    db.Column('student_id', db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), primary_key=True),
    db.Column('course_id',  db.Integer, db.ForeignKey('course.id',  ondelete='CASCADE'), primary_key=True)
)

student_parent = db.Table('student_parent',
    db.Column('student_id', db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), primary_key=True),
    db.Column('parent_id',  db.Integer, db.ForeignKey('parent.id',  ondelete='CASCADE'), primary_key=True)
)


class Student(db.Model):
    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    first_name    = db.Column(db.String(50), nullable=False)
    middle_name   = db.Column(db.String(50), nullable=True)
    last_name     = db.Column(db.String(50), nullable=False)
    student_id    = db.Column(db.String(20), unique=True, nullable=False)
    ssid          = db.Column(db.String(20), nullable=True)
    cds_code      = db.Column(db.String(14), nullable=True)
    grade         = db.Column(db.String(5),  nullable=False)
    gender        = db.Column(db.String(1),  nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    gradyr        = db.Column(db.String(4),  nullable=True)
    ethnicity     = db.Column(db.String(3),  nullable=True)
    frm_code      = db.Column(db.String(1),  nullable=True)
    english_status = db.Column(db.String(10), nullable=True)
    enter_date    = db.Column(db.Date, nullable=True)
    exit_date     = db.Column(db.Date, nullable=True)
    disability    = db.Column(db.String(20), nullable=True)
    sped_exdate   = db.Column(db.Date, nullable=True)
    dwelling      = db.Column(db.String(2),  nullable=True)
    migrant       = db.Column(db.Boolean, nullable=True, default=False)
    schoolyr      = db.Column(db.String(9),  nullable=True)
    foster        = db.Column(db.Boolean, nullable=True, default=False)
    sed504        = db.Column(db.Boolean, nullable=True, default=False)
    pk_yr_id      = db.Column(db.String(20), nullable=True)
    email         = db.Column(db.String(120), nullable=True)
    site_id       = db.Column(db.Integer, db.ForeignKey('site.id', ondelete='CASCADE'), nullable=False)
    site          = db.relationship('Site', backref=db.backref('students', lazy=True))

    @property
    def is_active(self):
        from datetime import date
        today = date.today()
        enter_ok = self.enter_date is None or self.enter_date <= today
        exit_ok  = self.exit_date  is None or self.exit_date  >= today
        return enter_ok and exit_ok

    @property
    def status(self):
        return 'Active' if self.is_active else 'Inactive'

    @status.setter
    def status(self, value):
        pass  # computed — assignment silently ignored for backward compat


class Absence(db.Model):
    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    site_id     = db.Column(db.Integer, db.ForeignKey('site.id', ondelete='CASCADE'), nullable=False)
    ssid        = db.Column(db.String(20), nullable=True)
    grade       = db.Column(db.String(5),  nullable=True)
    abs_date    = db.Column(db.Date,         nullable=True)
    abs_desc    = db.Column(db.String(200), nullable=True)
    abs_abbr    = db.Column(db.String(20),  nullable=True)
    bell_period = db.Column(db.String(20),  nullable=True)
    school_yr   = db.Column(db.String(9),   nullable=True)
    site        = db.relationship('Site', backref=db.backref('absences', lazy=True))


class Incident(db.Model):
    id             = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sisid          = db.Column(db.String(20),  nullable=True)
    site           = db.Column(db.String(100), nullable=True)
    cds_code       = db.Column(db.String(14),  nullable=True)
    incident_id    = db.Column(db.String(30),  nullable=True)
    incident_date  = db.Column(db.Date,         nullable=True)
    schoolyr       = db.Column(db.String(9),   nullable=True)
    incident_time  = db.Column(db.String(10),  nullable=True)
    day_of_week    = db.Column(db.String(10),  nullable=True)
    major          = db.Column(db.String(100), nullable=True)
    minor          = db.Column(db.String(100), nullable=True)
    suspended_days = db.Column(db.Float,        nullable=True)


class Teacher(db.Model):
    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    first_name  = db.Column(db.String(50), nullable=False)
    middle_name = db.Column(db.String(50), nullable=True)
    last_name   = db.Column(db.String(50), nullable=False)
    employee_id = db.Column(db.String(20), unique=True, nullable=False)
    email       = db.Column(db.String(120), nullable=True)
    department  = db.Column(db.String(100), nullable=True)
    status      = db.Column(db.String(20), nullable=False, default='Active')
    site_id     = db.Column(db.Integer, db.ForeignKey('site.id', ondelete='CASCADE'), nullable=False)
    site        = db.relationship('Site', backref=db.backref('teachers', lazy=True))


class Course(db.Model):
    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    course_name = db.Column(db.String(100), nullable=False)
    course_code = db.Column(db.String(20), unique=True, nullable=False)
    grade_level = db.Column(db.String(5),  nullable=True)
    period      = db.Column(db.String(20), nullable=True)
    description  = db.Column(db.Text, nullable=True)
    max_students = db.Column(db.Integer, nullable=True)
    status       = db.Column(db.String(20), nullable=False, default='Active')
    teacher_id  = db.Column(db.Integer, db.ForeignKey('teacher.id', ondelete='SET NULL'), nullable=True)
    site_id     = db.Column(db.Integer, db.ForeignKey('site.id', ondelete='CASCADE'), nullable=False)
    teacher     = db.relationship('Teacher', backref=db.backref('courses', lazy=True))
    site        = db.relationship('Site', backref=db.backref('courses', lazy=True))
    students    = db.relationship('Student', secondary=student_course,
                                  backref=db.backref('courses', lazy=True))


class Parent(db.Model):
    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    first_name   = db.Column(db.String(50), nullable=False)
    middle_name  = db.Column(db.String(50), nullable=True)
    last_name    = db.Column(db.String(50), nullable=False)
    relationship = db.Column(db.String(30), nullable=False)
    email        = db.Column(db.String(120), nullable=True)
    phone        = db.Column(db.String(20), nullable=True)
    status       = db.Column(db.String(20), nullable=False, default='Active')
    students     = db.relationship('Student', secondary=student_parent,
                                   backref=db.backref('parents', lazy=True))


class BulkUploadLog(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=_utcnow, nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    total_records = db.Column(db.Integer, default=0)
    users_added = db.Column(db.Integer, default=0)
    users_updated = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='success')
    error_message = db.Column(db.Text, nullable=True)

    uploader = db.relationship('User', foreign_keys=[uploaded_by_id])
