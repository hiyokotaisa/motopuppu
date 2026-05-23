"""add collection fields to event and event_participant

Revision ID: a1b2c3d4e5f6
Revises: 0529862eafb8
Create Date: 2026-05-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '0529862eafb8'
branch_labels = None
depends_on = None


def upgrade():
    # Event: 集金関連カラム
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'collection_enabled', sa.Boolean(),
            nullable=False, server_default=sa.text('false'),
            comment='当日集金を行うか'
        ))
        batch_op.add_column(sa.Column(
            'collection_amount', sa.Integer(),
            nullable=True,
            comment='当日集金額 (円・参加者一律)'
        ))
        batch_op.add_column(sa.Column(
            'collection_note', sa.String(length=100),
            nullable=True,
            comment='集金目的のメモ (例: 駐車場代+食事代)'
        ))

    # PaymentStatus Enum を作成
    payment_status_enum = sa.Enum('unpaid', 'paid', 'exempt', name='paymentstatus')
    payment_status_enum.create(op.get_bind(), checkfirst=True)

    # EventParticipant: 支払いステータス・支払日時
    with op.batch_alter_table('event_participants', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'payment_status', payment_status_enum,
            nullable=False, server_default='unpaid',
            comment='支払いステータス (unpaid/paid/exempt)'
        ))
        batch_op.add_column(sa.Column(
            'paid_at', sa.DateTime(),
            nullable=True,
            comment='支払いを記録した日時 (UTC)'
        ))


def downgrade():
    with op.batch_alter_table('event_participants', schema=None) as batch_op:
        batch_op.drop_column('paid_at')
        batch_op.drop_column('payment_status')

    payment_status_enum = sa.Enum('unpaid', 'paid', 'exempt', name='paymentstatus')
    payment_status_enum.drop(op.get_bind(), checkfirst=True)

    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_column('collection_note')
        batch_op.drop_column('collection_amount')
        batch_op.drop_column('collection_enabled')
