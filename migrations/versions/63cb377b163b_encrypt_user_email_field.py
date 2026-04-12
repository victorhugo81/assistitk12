"""encrypt user email field

Revision ID: 63cb377b163b
Revises: f0a9192f6bd2
Create Date: 2026-04-08 20:14:49.541715

"""
import os
import hmac as _hmac
import hashlib
import base64
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from cryptography.fernet import Fernet

# revision identifiers, used by Alembic.
revision = '63cb377b163b'
down_revision = 'f0a9192f6bd2'
branch_labels = None
depends_on = None


def _get_fernet(secret_key: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
    return Fernet(key)


def _hash_email(email: str, secret_key: str) -> str:
    return _hmac.new(
        secret_key.encode('utf-8'),
        email.strip().lower().encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def upgrade():
    bind = op.get_bind()
    secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')
    f = _get_fernet(secret_key)

    # 1. Add new columns as nullable so existing rows don't violate NOT NULL
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_enc', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('email_hash', sa.String(length=64), nullable=True))

    # 2. Backfill: encrypt and hash every existing email
    rows = bind.execute(sa.text("SELECT id, email FROM `user`")).fetchall()
    for row_id, email in rows:
        email = email or ''
        enc = f.encrypt(email.encode('utf-8')).decode('utf-8')
        hsh = _hash_email(email, secret_key)
        bind.execute(
            sa.text("UPDATE `user` SET email_enc = :enc, email_hash = :hsh WHERE id = :id"),
            {"enc": enc, "hsh": hsh, "id": row_id}
        )

    # 3. Tighten columns: NOT NULL + unique index, then drop old plaintext column
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('email_enc', existing_type=sa.Text(), nullable=False)
        batch_op.alter_column('email_hash', existing_type=sa.String(64), nullable=False)
        batch_op.create_index('ix_user_email_hash', ['email_hash'], unique=True)
        batch_op.drop_index('email')   # drops the unique index on the old email column
        batch_op.drop_column('email')


def downgrade():
    bind = op.get_bind()
    secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')
    f = _get_fernet(secret_key)

    # 1. Re-add the plaintext column as nullable
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', mysql.VARCHAR(length=120), nullable=True))

    # 2. Decrypt email_enc back into email
    rows = bind.execute(sa.text("SELECT id, email_enc FROM `user`")).fetchall()
    for row_id, email_enc in rows:
        try:
            plaintext = f.decrypt((email_enc or '').encode('utf-8')).decode('utf-8')
        except Exception:
            plaintext = ''
        bind.execute(
            sa.text("UPDATE `user` SET email = :email WHERE id = :id"),
            {"email": plaintext, "id": row_id}
        )

    # 3. Restore constraints, drop new columns
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('email', existing_type=mysql.VARCHAR(length=120), nullable=False)
        batch_op.create_index('email', ['email'], unique=True)
        batch_op.drop_index('ix_user_email_hash')
        batch_op.drop_column('email_hash')
        batch_op.drop_column('email_enc')
