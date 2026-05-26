"""extend attachment filepath for gcs

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-26 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.alter_column(
            'filepath',
            existing_type=sa.String(length=512),
            type_=sa.String(length=2048),
            existing_nullable=False,
        )


def downgrade():
    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.alter_column(
            'filepath',
            existing_type=sa.String(length=2048),
            type_=sa.String(length=512),
            existing_nullable=False,
        )
