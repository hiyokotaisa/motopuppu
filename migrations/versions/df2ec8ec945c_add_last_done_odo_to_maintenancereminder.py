"""Add last_done_odo to MaintenanceReminder

Revision ID: df2ec8ec945c
Revises: f0c7fc2c92ad
Create Date: 2025-07-15 05:27:45.872324

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'df2ec8ec945c'
down_revision = 'f0c7fc2c92ad'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('maintenance_reminders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_done_odo', sa.Integer(), nullable=True, comment='最終実施時の『メーターODO値』(手動入力用)'))
        batch_op.alter_column('last_done_km',
               existing_type=sa.INTEGER(),
               comment='最終実施時の『総走行距離』(計算済み)',
               existing_comment='手動入力または連携された最終実施距離',
               existing_nullable=True)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('maintenance_reminders', schema=None) as batch_op:
        batch_op.alter_column('last_done_km',
               existing_type=sa.INTEGER(),
               comment='手動入力または連携された最終実施距離',
               existing_comment='最終実施時の『総走行距離』(計算済み)',
               existing_nullable=True)
        batch_op.drop_column('last_done_odo')

    # ### end Alembic commands ###
