"""add ticket_alerts_seen_at to user

Revision ID: a1c4e8f2b7d3
Revises: 63cb377b163b
Create Date: 2026-09-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c4e8f2b7d3'
down_revision = '63cb377b163b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ticket_alerts_seen_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('ticket_alerts_seen_at')
