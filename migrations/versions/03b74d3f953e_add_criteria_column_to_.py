"""Add criteria column to AchievementDefinition

Revision ID: 03b74d3f953e
Revises: 4ec29611c9b5
Create Date: 2025-05-09 13:16:58.677340

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '03b74d3f953e'
down_revision = '4ec29611c9b5'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('achievement_definitions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('criteria', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('achievement_definitions', schema=None) as batch_op:
        batch_op.drop_column('criteria')

    # ### end Alembic commands ###
