"""add location and principal fields to site

Revision ID: d3e7a9c1f452
Revises: a1c4e8f2b7d3
Create Date: 2026-09-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3e7a9c1f452'
down_revision = 'a1c4e8f2b7d3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site', schema=None) as batch_op:
        batch_op.add_column(sa.Column('site_city', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('site_state', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('site_zip', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('principal_first_name', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('principal_last_name', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('principal_email', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('principal_phone', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('site', schema=None) as batch_op:
        batch_op.drop_column('principal_phone')
        batch_op.drop_column('principal_email')
        batch_op.drop_column('principal_last_name')
        batch_op.drop_column('principal_first_name')
        batch_op.drop_column('site_zip')
        batch_op.drop_column('site_state')
        batch_op.drop_column('site_city')
