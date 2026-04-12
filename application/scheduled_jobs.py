"""
Background job functions for APScheduler.
Each function runs inside a Flask application context pushed explicitly.
"""
import ftplib
import io
import csv
import secrets
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def run_org_ftp_schedule():
    """Scheduled FTP import: downloads sites.csv then users CSV using credentials from Organization."""
    from main import db, scheduler

    with scheduler.app.app_context():
        from flask import current_app
        from application.models import Organization, BulkUploadLog, User, Site
        from application.utils import decrypt_mail_password, hash_email
        from application.routes import _process_sites_rows
        from werkzeug.security import generate_password_hash

        org = Organization.query.get(1)
        if not org or not org.ftp_schedule_enabled:
            return

        today = datetime.now(timezone.utc).date()
        if org.ftp_schedule_start_date and today < org.ftp_schedule_start_date:
            logger.info('Scheduled FTP import skipped: before start date (%s).', org.ftp_schedule_start_date)
            return
        if org.ftp_schedule_stop_date and today > org.ftp_schedule_stop_date:
            logger.info('Scheduled FTP import skipped: past stop date (%s).', org.ftp_schedule_stop_date)
            return

        key      = current_app.config['SECRET_KEY']
        ftp_host = decrypt_mail_password(org.ftp_host_enc or '', key)
        username = decrypt_mail_password(org.ftp_username_enc or '', key)
        password = decrypt_mail_password(org.ftp_password_enc or '', key)
        raw_path = org.ftp_path or ''
        if raw_path.lower().endswith('.csv'):
            import posixpath as _pp
            raw_path = _pp.dirname(raw_path)
        ftp_dir  = raw_path.rstrip('/')
        port     = org.ftp_port or 21
        use_tls  = bool(org.ftp_use_tls)

        if not all([ftp_host, username, ftp_dir]):
            logger.warning('Scheduled FTP import skipped: incomplete credentials in Organization.')
            return

        users_path = f'{ftp_dir}/users.csv'
        sites_path = f'{ftp_dir}/sites.csv'
        users_added   = users_updated = total_records = 0
        sites_added   = sites_updated = 0

        try:
            ftp = ftplib.FTP_TLS() if use_tls else ftplib.FTP()
            ftp.connect(ftp_host, port, timeout=30)
            ftp.login(username, password)
            if use_tls:
                ftp.prot_p()

            # --- sites.csv (optional) ---
            sites_buf = io.BytesIO()
            try:
                ftp.retrbinary(f'RETR {sites_path}', sites_buf.write)
                sites_buf.seek(0)
                site_rows   = list(csv.DictReader(sites_buf.read().decode('utf-8').splitlines()))
                sites_added, sites_updated = _process_sites_rows(site_rows)
                db.session.commit()
                db.session.add(BulkUploadLog(
                    filename='[Sites] [Scheduled] sites.csv',
                    total_records=len(site_rows),
                    users_added=sites_added,
                    users_updated=sites_updated,
                    status='success'
                ))
                db.session.commit()
            except ftplib.error_perm:
                pass  # sites.csv absent — skip

            # --- users.csv ---
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
                    raise ValueError('Some rows are missing required fields.')
                site = Site.query.filter_by(site_name=row['site_name']).first()
                if not site:
                    raise ValueError(f"Site '{row['site_name']}' not found.")
                csv_emails.add(row['email'].strip().lower())

            # Second pass: upsert users
            for row in rows:
                site = Site.query.filter_by(site_name=row['site_name']).first()
                existing = User.query.filter_by(email_hash=hash_email(row['email'].strip(), key)).first()
                if existing:
                    existing.first_name  = row['first_name']
                    existing.middle_name = row.get('middle_name') or None
                    existing.last_name   = row['last_name']
                    existing.rm_num      = row.get('rm_num') or existing.rm_num
                    existing.role_id     = int(row['role_id'])
                    existing.site_id     = site.id
                    existing.status      = row.get('status') or 'Active'
                    users_updated += 1
                else:
                    db.session.add(User(
                        first_name=row['first_name'],
                        middle_name=row.get('middle_name'),
                        last_name=row['last_name'],
                        email=row['email'].strip(),
                        status=row.get('status', 'Active'),
                        password=generate_password_hash(secrets.token_urlsafe(16)),
                        must_change_password=True,
                        rm_num=row.get('rm_num'),
                        role_id=row['role_id'],
                        site_id=site.id
                    ))
                    users_added += 1

            # Third pass: deactivate users absent from the CSV
            sched_csv_hashes = {hash_email(e, key) for e in csv_emails}
            for user in User.query.filter(User.status == 'Active').all():
                if user.email_hash not in sched_csv_hashes:
                    user.status = 'Inactive'

            db.session.commit()

            org.ftp_last_run_at     = datetime.now(timezone.utc)
            org.ftp_last_run_status = 'success'
            db.session.add(org)
            db.session.add(BulkUploadLog(
                filename='[FTP] [Scheduled] users.csv',
                total_records=total_records,
                users_added=users_added,
                users_updated=users_updated,
                status='success'
            ))
            db.session.commit()
            logger.info(f'Scheduled FTP import: +{users_added} users added, ~{users_updated} updated.')

        except Exception as e:
            db.session.rollback()
            org.ftp_last_run_at     = datetime.now(timezone.utc)
            org.ftp_last_run_status = 'error'
            try:
                db.session.add(org)
                db.session.add(BulkUploadLog(
                    filename='[FTP] [Scheduled] users.csv',
                    total_records=total_records,
                    users_added=users_added,
                    users_updated=users_updated,
                    status='error',
                    error_message=str(e)
                ))
                db.session.commit()
            except Exception:
                db.session.rollback()
            logger.error(f'Scheduled FTP import failed: {e}', exc_info=True)
