"""add misskey post opt-out flags

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-24 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('session_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'allow_misskey_post',
            sa.Boolean(),
            nullable=False,
            server_default='true',
            comment='このセッションのベストラップをMisskey botが自動投稿してよいか',
        ))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'disallow_misskey_post_by_default',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='新規セッション記録のMisskey自動投稿を既定で許可しないか',
        ))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('disallow_misskey_post_by_default')

    with op.batch_alter_table('session_logs', schema=None) as batch_op:
        batch_op.drop_column('allow_misskey_post')
