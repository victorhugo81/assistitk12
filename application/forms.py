from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, TextAreaField, FieldList, FormField, BooleanField, RadioField, DateTimeField, IntegerField
from wtforms.validators import DataRequired, Email, Length, Optional
from flask_wtf.file import FileField, FileRequired, FileAllowed
from datetime import datetime

class LoginForm(FlaskForm):
    email = StringField('Email:', validators=[DataRequired(), Email()])
    password = PasswordField('Password:', validators=[DataRequired()])
    submit = SubmitField('Login')


class UserForm(FlaskForm):
    first_name = StringField('First Name:', validators=[DataRequired()])
    middle_name = StringField('Middle Name:', validators=[Optional()])
    last_name = StringField('Last Name:', validators=[DataRequired()])
    email = StringField('Email:', validators=[DataRequired(), Email()])
    role_id = SelectField('Role:', coerce=int, choices=[], validators=[DataRequired()])
    site_id = SelectField('Site:', coerce=int, choices=[], validators=[DataRequired()])
    rm_num = StringField('Room:', validators=[Optional()])
    status = SelectField('Status:',
        choices=[('Active', 'Active'), ('Inactive', 'Inactive')],
        validators=[DataRequired()]    )
    password = PasswordField('New Password:', validators=[Optional(), Length(min=10)])
    submit = SubmitField('Save User')


class RoleForm(FlaskForm):
    role_name = StringField('Role Name:', validators=[DataRequired()])
    submit = SubmitField('Save Role')


class SiteForm(FlaskForm):
    site_name = StringField('Site Name:', validators=[DataRequired()])
    site_GU = StringField('Site GUID:', validators=[DataRequired()])
    site_code = StringField('Site Code:', validators=[DataRequired()])
    site_abb = StringField('Abbreviation:', validators=[DataRequired()])
    site_cds = StringField('CDS Code:', validators=[DataRequired()])
    site_address = StringField('Site Address:', validators=[DataRequired()])
    site_type = StringField('Site Type:', validators=[DataRequired()])
    submit = SubmitField('Save Site')


class NotificationForm(FlaskForm):
    msg_name = StringField('Message Name:', validators=[DataRequired()])
    msg_content = TextAreaField('Message:', validators=[DataRequired()])
    msg_status = RadioField('Status', choices=[('active', 'Active'), ('inactive', 'Inactive')], default='inactive', validators=[DataRequired()])
    submit = SubmitField('Save Notification Message')


class OrganizationForm(FlaskForm):
    organization_name = StringField('Organization Name', validators=[DataRequired()])
    site_version = StringField('Site Version', validators=[DataRequired()])
    submit = SubmitField('Save Settings')


class EmailConfigForm(FlaskForm):
    mail_server = StringField('SMTP Server', validators=[Optional()])
    mail_port = IntegerField('SMTP Port', validators=[Optional()])
    mail_use_tls = BooleanField('Use TLS (STARTTLS)')
    mail_use_ssl = BooleanField('Use SSL')
    mail_username = StringField('Username / Email', validators=[Optional()])
    mail_password = PasswordField('Password', validators=[Optional()])
    mail_default_sender = StringField('Default Sender Email', validators=[Optional(), Email()])
    submit_email = SubmitField('Save Email Settings')


class TicketContentForm(FlaskForm):
    user = StringField('User', render_kw={'readonly': True})  # Add User field
    content = TextAreaField('Content', validators=[DataRequired()])


class TicketForm(FlaskForm):
    title_id = SelectField('Ticket Title', choices=[], validators=[DataRequired()])
    contents = FieldList(FormField(TicketContentForm))
    tck_status = RadioField('Status', choices=[('1-pending', 'Pending'), ('2-progress', 'In Progress'), ('3-completed', 'Completed')], default='1-pending', validators=[DataRequired()])
    assigned_to_id = SelectField('Assign To', choices=[], coerce=int, validators=[Optional()])
    attachment = FileField('Attach Image')
    escalate = BooleanField('Escalate Ticket')
    submit = SubmitField('Submit')


class TitleForm(FlaskForm):
    title_name = StringField('Ticket Name:', validators=[DataRequired()])
    submit = SubmitField('Save Ticket Name')