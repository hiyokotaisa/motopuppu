"""add event_collection_plans table and FK on event_participants

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'event_collection_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False, comment='プラン名 (例: 走行料、見学費)'),
        sa.Column('amount', sa.Integer(), nullable=False, comment='金額 (円)'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0', comment='表示順'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_event_collection_plans_event_id'),
        'event_collection_plans',
        ['event_id'],
        unique=False,
    )

    with op.batch_alter_table('event_participants', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'collection_plan_id', sa.Integer(),
            nullable=True,
            comment='割り当てられた料金プランID (NULLならデフォルト金額)'
        ))
        batch_op.create_index(
            batch_op.f('ix_event_participants_collection_plan_id'),
            ['collection_plan_id'],
            unique=False,
        )
        batch_op.create_foreign_key(
            'fk_event_participants_collection_plan_id',
            'event_collection_plans',
            ['collection_plan_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('event_participants', schema=None) as batch_op:
        batch_op.drop_constraint('fk_event_participants_collection_plan_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_event_participants_collection_plan_id'))
        batch_op.drop_column('collection_plan_id')

    op.drop_index(
        op.f('ix_event_collection_plans_event_id'),
        table_name='event_collection_plans',
    )
    op.drop_table('event_collection_plans')
