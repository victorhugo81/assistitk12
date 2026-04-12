"""rename site_GU to site_acronyms

Revision ID: b2f9da811cd8
Revises: 8f7faa338f50
Create Date: 2026-03-31 18:07:47.058359

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b2f9da811cd8'
down_revision = '8f7faa338f50'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE site RENAME COLUMN site_GU TO site_acronyms')


def downgrade():
    op.execute('ALTER TABLE site RENAME COLUMN site_acronyms TO site_GU')
