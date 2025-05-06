"""Add missing general_notes and odo_reset_logs tables

Revision ID: cb61b6485ca8
Revises: cd7db2474a21
Create Date: 2025-05-06 01:18:21.241602

"""
from alembic import op
import sqlalchemy as sa
# from sqlalchemy.dialects import postgresql # 使われていないようなのでコメントアウトしてもOK

# revision identifiers, used by Alembic.
revision = 'cb61b6485ca8'
down_revision = 'cd7db2474a21'
branch_labels = None
depends_on = None


def upgrade():
    # ### 全てのスキーマ変更操作をコメントアウト ###
    # 本番DBには既に適用済みと判断されるため、このマイグレーションでは何もしない
    
    # general_notes テーブル関連 (コメントアウト済み)
    #op.create_table('general_notes', ...)
    # with op.batch_alter_table('general_notes', ...) ...

    # odo_reset_logs テーブル関連 (コメントアウト済み)
    # op.create_table('odo_reset_logs', ...)
    # with op.batch_alter_table('odo_reset_logs', ...) ...

    # attachments テーブル関連 (コメントアウト)
    # with op.batch_alter_table('attachments', schema=None) as batch_op:
    #     batch_op.drop_constraint('attachments_maintenance_entry_id_fkey', type_='foreignkey')
    #     batch_op.create_foreign_key(None, 'maintenance_entries', ['maintenance_entry_id'], ['id'], ondelete='CASCADE')

    # consumable_logs テーブル関連 (コメントアウト)
    # with op.batch_alter_table('consumable_logs', schema=None) as batch_op:
    #     batch_op.add_column(sa.Column('odometer_reading_at_change', sa.Integer(), nullable=True))
    #     batch_op.drop_constraint('consumable_logs_motorcycle_id_fkey', type_='foreignkey')
    #     batch_op.create_foreign_key(None, 'motorcycles', ['motorcycle_id'], ['id'], ondelete='CASCADE')
    #     batch_op.drop_column('total_distance_at_change')

    # fuel_entries テーブル関連 (コメントアウト)
    # with op.batch_alter_table('fuel_entries', schema=None) as batch_op:
    #     batch_op.create_index('ix_fuel_entries_entry_date', ['entry_date'], unique=False)
    #     batch_op.drop_constraint('fuel_entries_motorcycle_id_fkey', type_='foreignkey')
    #     batch_op.create_foreign_key(None, 'motorcycles', ['motorcycle_id'], ['id'], ondelete='CASCADE')

    # maintenance_entries テーブル関連 (コメントアウト)
    # with op.batch_alter_table('maintenance_entries', schema=None) as batch_op:
    #     batch_op.create_index('ix_maintenance_entries_category', ['category'], unique=False)
    #     batch_op.create_index('ix_maintenance_entries_maintenance_date', ['maintenance_date'], unique=False)
    #     batch_op.drop_constraint('maintenance_entries_motorcycle_id_fkey', type_='foreignkey')
    #     batch_op.create_foreign_key(None, 'motorcycles', ['motorcycle_id'], ['id'], ondelete='CASCADE')

    # maintenance_reminders テーブル関連 (コメントアウト)
    # with op.batch_alter_table('maintenance_reminders', schema=None) as batch_op:
    #     batch_op.drop_constraint('maintenance_reminders_motorcycle_id_fkey', type_='foreignkey')
    #     batch_op.create_foreign_key(None, 'motorcycles', ['motorcycle_id'], ['id'], ondelete='CASCADE')

    pass # 何も実行しない
    # ### end Alembic commands ###


def downgrade():
    # ### 全てのスキーマ変更操作をコメントアウト ###
    # このリビジョンへのダウングレードは、対応するスキーマ変更が実際には
    # 既に適用されてしまっているため、ここでも何もしないのが安全
    
    # maintenance_reminders テーブル関連 (コメントアウト)
    # with op.batch_alter_table('maintenance_reminders', ...) ...

    # maintenance_entries テーブル関連 (コメントアウト)
    # with op.batch_alter_table('maintenance_entries', ...) ...

    # fuel_entries テーブル関連 (コメントアウト)
    # with op.batch_alter_table('fuel_entries', ...) ...

    # consumable_logs テーブル関連 (コメントアウト)
    # with op.batch_alter_table('consumable_logs', ...) ...

    # attachments テーブル関連 (コメントアウト)
    # with op.batch_alter_table('attachments', ...) ...

    # odo_reset_logs テーブル関連 (コメントアウト済み)
    # with op.batch_alter_table('odo_reset_logs', ...) ...
    # op.drop_table('odo_reset_logs')
    
    # general_notes テーブル関連 (コメントアウト済み)
    # with op.batch_alter_table('general_notes', ...) ...
    # op.drop_table('general_notes')

    pass # 何も実行しない
    # ### end Alembic commands ###