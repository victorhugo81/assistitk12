from flask import current_app
from flask_mail import Message
from main import mail

STATUS_LABELS = {
    '1-pending': 'Pending',
    '2-progress': 'In Progress',
    '3-completed': 'Completed',
}


def send_ticket_notification(event, ticket, **kwargs):
    """
    Send email notifications for ticket events.

    Events:
        'created'   - ticket was just created (notifies assignee)
        'status'    - tck_status changed (kwargs: old_status, new_status) → notifies creator
        'assigned'  - ticket reassigned (kwargs: new_assignee) → notifies new assignee
        'escalated' - escalation toggled (kwargs: escalated bool) → notifies creator + assignee
        'comment'   - new comment added (kwargs: commenter) → notifies the other party
    """
    try:
        recipients = []
        subject = ''
        body = ''

        creator = ticket.user
        assignee = ticket.assigned_to
        ticket_label = f"Ticket #{ticket.id} – {ticket.title.title_name}"

        if event == 'created':
            if assignee and assignee.email:
                recipients = [assignee.email]
                subject = f"New Ticket Assigned to You: #{ticket.id}"
                initial_comment = kwargs.get('initial_comment', '').strip()
                comment_section = f"\nDescription:\n{initial_comment}\n" if initial_comment else ''
                body = (
                    f"Hi {assignee.first_name},\n\n"
                    f"A new ticket has been assigned to you.\n\n"
                    f"Ticket: {ticket_label}\n"
                    f"Status: {STATUS_LABELS.get(ticket.tck_status, ticket.tck_status)}\n"
                    f"Submitted by: {creator.get_full_name()}\n"
                    f"{comment_section}\n"
                    f"Please log in to the system to view and respond to this ticket.\n\n"
                    f"— AssistITK12 System"
                )

        elif event == 'status':
            old_label = STATUS_LABELS.get(kwargs.get('old_status', ''), kwargs.get('old_status', ''))
            new_label = STATUS_LABELS.get(kwargs.get('new_status', ''), kwargs.get('new_status', ''))
            if creator and creator.email:
                recipients = [creator.email]
                subject = f"Your Ticket #{ticket.id} Status Changed"
                body = (
                    f"Hi {creator.first_name},\n\n"
                    f"The status of your ticket has been updated.\n\n"
                    f"Ticket: {ticket_label}\n"
                    f"Status: {old_label} → {new_label}\n\n"
                    f"Please log in to view the details.\n\n"
                    f"— AssistITK12 System"
                )

        elif event == 'assigned':
            new_assignee = kwargs.get('new_assignee')
            if new_assignee and new_assignee.email:
                recipients = [new_assignee.email]
                subject = f"Ticket #{ticket.id} Assigned to You"
                body = (
                    f"Hi {new_assignee.first_name},\n\n"
                    f"A ticket has been assigned to you.\n\n"
                    f"Ticket: {ticket_label}\n"
                    f"Status: {STATUS_LABELS.get(ticket.tck_status, ticket.tck_status)}\n"
                    f"Submitted by: {creator.get_full_name()}\n\n"
                    f"Please log in to view and respond.\n\n"
                    f"— AssistITK12 System"
                )

        elif event == 'escalated':
            is_escalated = bool(kwargs.get('escalated', False))
            action = 'escalated' if is_escalated else 'de-escalated'
            emails = []
            if creator and creator.email:
                emails.append(creator.email)
            if assignee and assignee.email and assignee.email not in emails:
                emails.append(assignee.email)
            recipients = emails
            subject = f"Ticket #{ticket.id} Has Been {action.title()}"
            body = (
                f"This is a notification that Ticket #{ticket.id} has been {action}.\n\n"
                f"Ticket: {ticket_label}\n"
                f"Status: {STATUS_LABELS.get(ticket.tck_status, ticket.tck_status)}\n\n"
                f"Please log in to review.\n\n"
                f"— AssistITK12 System"
            )

        elif event == 'comment':
            commenter = kwargs.get('commenter')
            commenter_name = commenter.get_full_name() if commenter else 'Someone'
            comment_text = kwargs.get('comment_text', '').strip()
            comment_section = f"\nComment:\n{comment_text}\n" if comment_text else ''
            subject = f"New Comment on Ticket #{ticket.id}"

            # Notify both creator and assignee, but never the commenter themselves
            notify = {}
            if creator and creator.email and (not commenter or commenter.id != creator.id):
                notify[creator.email] = creator.first_name
            if assignee and assignee.email and assignee.email not in notify \
                    and (not commenter or commenter.id != assignee.id):
                notify[assignee.email] = assignee.first_name

            for email, first_name in notify.items():
                msg = Message(
                    subject=subject,
                    recipients=[email],
                    body=(
                        f"Hi {first_name},\n\n"
                        f"{commenter_name} added a comment to Ticket #{ticket.id}.\n\n"
                        f"Ticket: {ticket_label}\n"
                        f"{comment_section}\n"
                        f"Please log in to view and reply.\n\n"
                        f"— AssistITK12 System"
                    )
                )
                mail.send(msg)
                current_app.logger.info(f"Comment notification sent to {email}")
            return  # individual emails already sent above

        if recipients and subject and body:
            msg = Message(subject=subject, recipients=recipients, body=body)
            mail.send(msg)
            current_app.logger.info(f"Ticket notification '{event}' sent to {recipients}")

    except Exception as e:
        current_app.logger.error(f"Failed to send ticket notification (event={event}): {type(e).__name__}: {e}", exc_info=True)


def send_temp_password_email(user, temp_password):
    """Send a temporary password to a user and instruct them to change it on first login."""
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
