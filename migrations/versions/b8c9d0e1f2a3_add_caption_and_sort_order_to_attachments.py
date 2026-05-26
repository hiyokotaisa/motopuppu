"""add caption and sort_order to attachments

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-26 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('caption', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column(
            'sort_order',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ))


def downgrade():
    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.drop_column('sort_order')
        batch_op.drop_column('caption')
