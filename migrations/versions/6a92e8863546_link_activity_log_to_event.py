"""Link activity log to event

Revision ID: 6a92e8863546
Revises: 9516bc768302
Create Date: 2025-07-15 07:47:56.543829

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6a92e8863546'
down_revision = '9516bc768302'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('activity_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('event_id', sa.Integer(), nullable=True, comment='この活動ログが紐づくイベントのID'))
        batch_op.create_index(batch_op.f('ix_activity_logs_event_id'), ['event_id'], unique=False)
        batch_op.create_foreign_key(None, 'events', ['event_id'], ['id'], ondelete='SET NULL')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('activity_logs', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_activity_logs_event_id'))
        batch_op.drop_column('event_id')

    # ### end Alembic commands ###
