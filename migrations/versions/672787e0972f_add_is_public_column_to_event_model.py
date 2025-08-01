"""Add is_public column to Event model

Revision ID: 672787e0972f
Revises: f2a7668dac26
Create Date: 2025-07-18 23:27:20.754940

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '672787e0972f'
down_revision = 'f2a7668dac26'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_public', sa.Boolean(), server_default='true', nullable=False, comment='イベント一覧に公開するか'))
        batch_op.create_index(batch_op.f('ix_events_is_public'), ['is_public'], unique=False)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_events_is_public'))
        batch_op.drop_column('is_public')

    # ### end Alembic commands ###
