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
                body = (
                    f"Hi {assignee.first_name},\n\n"
                    f"A new ticket has been assigned to you.\n\n"
                    f"Ticket: {ticket_label}\n"
                    f"Status: {STATUS_LABELS.get(ticket.tck_status, ticket.tck_status)}\n"
                    f"Submitted by: {creator.get_full_name()}\n\n"
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
            recipient_name = ''
            if commenter and creator and commenter.id == creator.id:
                # Creator commented → notify assignee
                if assignee and assignee.email:
                    recipients = [assignee.email]
                    recipient_name = assignee.first_name
            else:
                # Tech/assignee commented → notify creator
                if creator and creator.email:
                    recipients = [creator.email]
                    recipient_name = creator.first_name

            if recipients:
                commenter_name = commenter.get_full_name() if commenter else 'Someone'
                subject = f"New Comment on Ticket #{ticket.id}"
                body = (
                    f"Hi {recipient_name},\n\n"
                    f"{commenter_name} added a comment to your ticket.\n\n"
                    f"Ticket: {ticket_label}\n\n"
                    f"Please log in to view the comment and reply.\n\n"
                    f"— AssistITK12 System"
                )

        if recipients and subject and body:
            msg = Message(subject=subject, recipients=recipients, body=body)
            mail.send(msg)
            current_app.logger.info(f"Ticket notification '{event}' sent to {recipients}")

    except Exception as e:
        current_app.logger.error(f"Failed to send ticket notification (event={event}): {type(e).__name__}: {e}", exc_info=True)
