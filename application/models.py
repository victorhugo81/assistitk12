from main import db  # Import db from main.py where it's initialized
from flask_login import UserMixin
from datetime import datetime


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
    email = db.Column(db.String(120), nullable=False, unique=True)
    status = db.Column(db.String(120), nullable=False)
    password = db.Column(db.String(255), nullable=False)
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
    site_GU = db.Column(db.String(36), nullable=False, unique=True)
    site_cds = db.Column(db.String(100), nullable=False, unique=True)
    site_code = db.Column(db.String(100), nullable=False, unique=True)
    site_abb = db.Column(db.String(100), nullable=False, unique=True)
    site_address = db.Column(db.String(100), nullable=False)
    site_type = db.Column(db.String(100), nullable=False)
    users = db.relationship('User', backref='site', lazy=True)
    tickets = db.relationship('Ticket', back_populates='site')  # Matches the relationship in Ticket


class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title_id = db.Column(db.Integer, db.ForeignKey('title.id'), nullable=False)
    tck_status = db.Column(db.String(45), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # User who created the ticket
    site_id = db.Column(db.Integer, db.ForeignKey('site.id'), nullable=False)  # Related site
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # User assigned to the ticket
    escalated = db.Column(db.Integer, nullable=True, default=0) 

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref='created_tickets')
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_id], backref='assigned_tickets')
    title = db.relationship('Title', backref='tickets')
    contents = db.relationship('Ticket_content', back_populates='ticket', cascade='all, delete-orphan')
    site = db.relationship('Site', back_populates='tickets')
    attachments = db.relationship('Ticket_attachment', backref='ticket', lazy=True, cascade='all, delete-orphan')
    
    @classmethod
    def get_tickets_by_status(cls, status):
        return cls.query.filter_by(tck_status=status).all()

    @classmethod
    def get_tickets_assigned_to_user(cls, user_id):
        return cls.query.filter_by(assigned_to_id=user_id).all()


class Title(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title_name = db.Column(db.String(100), unique=True, nullable=False)


class Ticket_content(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    cnt_created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Relationship back to the Ticket model
    ticket = db.relationship('Ticket', back_populates='contents')
    user = db.relationship('User', backref='comments')


class Ticket_attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    attach_image = db.Column(db.String(255), nullable=False)  # This column should exist
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)


class BulkUploadLog(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    total_records = db.Column(db.Integer, default=0)
    users_added = db.Column(db.Integer, default=0)
    users_updated = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='success')
    error_message = db.Column(db.Text, nullable=True)

    uploader = db.relationship('User', foreign_keys=[uploaded_by_id])
