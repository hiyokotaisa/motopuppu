"""add_maintenance_spec_sheet_table

Revision ID: f2a7668dac26
Revises: aa6d3aff4f5c
Create Date: 2025-07-18 12:11:59.026732

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f2a7668dac26'
down_revision = 'aa6d3aff4f5c'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('maintenance_spec_sheets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('motorcycle_id', sa.Integer(), nullable=False),
    sa.Column('sheet_name', sa.String(length=100), nullable=False),
    sa.Column('spec_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['motorcycle_id'], ['motorcycles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('maintenance_spec_sheets', schema=None) as batch_op:
        batch_op.create_index('ix_maintenance_spec_sheets_motorcycle_id', ['motorcycle_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_maintenance_spec_sheets_sheet_name'), ['sheet_name'], unique=False)
        batch_op.create_index('ix_maintenance_spec_sheets_user_id', ['user_id'], unique=False)

    with op.batch_alter_table('touring_spots', schema=None) as batch_op:
        batch_op.add_column(sa.Column('latitude', sa.Float(), nullable=True, comment='緯度'))
        batch_op.add_column(sa.Column('longitude', sa.Float(), nullable=True, comment='経度'))
        batch_op.add_column(sa.Column('google_place_id', sa.String(length=255), nullable=True, comment='Google Place ID'))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('touring_spots', schema=None) as batch_op:
        batch_op.drop_column('google_place_id')
        batch_op.drop_column('longitude')
        batch_op.drop_column('latitude')

    with op.batch_alter_table('maintenance_spec_sheets', schema=None) as batch_op:
        batch_op.drop_index('ix_maintenance_spec_sheets_user_id')
        batch_op.drop_index(batch_op.f('ix_maintenance_spec_sheets_sheet_name'))
        batch_op.drop_index('ix_maintenance_spec_sheets_motorcycle_id')

    op.drop_table('maintenance_spec_sheets')
    # ### end Alembic commands ###
