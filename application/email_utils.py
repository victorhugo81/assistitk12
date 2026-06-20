from flask import current_app
from flask_mail import Message
from main import mail, db

STATUS_LABELS = {
    '1-pending': 'Pending',
    '2-progress': 'In Progress',
    '3-completed': 'Completed',
}


def _is_mail_configured():
    """Return True only if the Organization has SMTP credentials saved."""
    from application.models import Organization
    org = db.session.get(Organization, 1)
    return bool(org and org.mail_server and org.mail_username)


def send_temp_password_email(user, temp_password):
    """Send a temporary password to a user and instruct them to change it on first login."""
    if not _is_mail_configured():
        current_app.logger.info("Temp password email skipped — no SMTP configuration saved.")
        return
    try:
        msg = Message(
            subject="Your Temporary Password — AssistITK12",
            recipients=[user.email],
            body=(
                f"Hi {user.first_name},\n\n"
                f"An administrator has reset your password. Use the temporary password below to log in.\n\n"
                f"Temporary Password: {temp_password}\n\n"
                f"You will be required to change your password immediately after logging in.\n\n"
                f"— AssistITK12 System"
            )
        )
        mail.send(msg)
        current_app.logger.info(f"Temporary password email sent to {user.email}")
    except Exception as e:
        current_app.logger.error(f"Failed to send temp password email to {user.email}: {type(e).__name__}: {e}", exc_info=True)
        raise


def send_password_updated_email(user):
    """Notify a user that their password was manually updated by an administrator."""
    if not _is_mail_configured():
        return
    try:
        msg = Message(
            subject="Your Password Has Been Updated — AssistITK12",
            recipients=[user.email],
            body=(
                f"Hi {user.first_name},\n\n"
                f"This is a confirmation that your password has been updated by an administrator.\n\n"
                f"If you did not expect this change, please contact your system administrator immediately.\n\n"
                f"— AssistITK12 System"
            )
        )
        mail.send(msg)
        current_app.logger.info(f"Password updated notification sent to {user.email}")
    except Exception as e:
        current_app.logger.error(f"Failed to send password updated email to {user.email}: {type(e).__name__}: {e}", exc_info=True)
