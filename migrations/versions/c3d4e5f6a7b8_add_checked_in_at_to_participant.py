"""add checked_in_at to event_participants

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-23 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('event_participants', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'checked_in_at', sa.DateTime(),
            nullable=True,
            comment='当日チェックインを記録した日時 (UTC)'
        ))


def downgrade():
    with op.batch_alter_table('event_participants', schema=None) as batch_op:
        batch_op.drop_column('checked_in_at')
