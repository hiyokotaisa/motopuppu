"""Populate new achievement definitions data

Revision ID: 760969e7b61d
Revises: 03b74d3f953e
Create Date: 2025-05-09 13:35:00.190678

"""
from alembic import op
import sqlalchemy as sa
# from sqlalchemy.dialects.postgresql import JSONB # PostgreSQL固有の型を使いたい場合
# sqlalchemy.JSON を使用する方がポータブルな場合があります

# イベントタイプの定数 (motopuppu/achievement_evaluator.py と合わせる)
EVENT_ADD_VEHICLE = "add_vehicle"
EVENT_ADD_FUEL_LOG = "add_fuel_log"
EVENT_ADD_MAINTENANCE_LOG = "add_maintenance_log"
EVENT_ADD_NOTE = "add_note"
# EVENT_ADD_ODO_RESET は既存の初回実績で使用

# revision identifiers, used by Alembic.
revision = '760969e7b61d'
down_revision = '03b74d3f953e'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - START ###
    # with op.batch_alter_table('users', schema=None) as batch_op:
    #     batch_op.alter_column('misskey_user_id',
    #            existing_type=sa.VARCHAR(length=100),
    #            comment='username for miskey', # このダミー変更は実績データ投入とは無関係なので削除またはコメントアウト
    #            existing_nullable=False)
    # ### commands auto generated by Alembic - END ###

    # ▼▼▼ 実績定義データの投入処理をここから記述 ▼▼▼
    achievement_definitions_table = sa.table(
        'achievement_definitions',
        sa.column('code', sa.String),
        sa.column('name', sa.String),
        sa.column('description', sa.Text),
        sa.column('icon_class', sa.String),
        sa.column('category_code', sa.String),
        sa.column('category_name', sa.String),
        sa.column('share_text_template', sa.Text),
        sa.column('trigger_event_type', sa.String),
        sa.column('criteria', sa.JSON) 
    )

    new_achievements_data = [
        # --- 回数系実績: 給油 ---
        {'code': 'FUEL_LOG_COUNT_10', 'name': '給油10回達成！', 'description': '給油記録を10回追加する', 'icon_class': 'fas fa-tint', 'category_code': 'fuel', 'category_name': '給油記録', 'share_text_template': '実績「{achievement_name}」解除！給油10回達成！⛽ #もとぷっぷー', 'trigger_event_type': EVENT_ADD_FUEL_LOG, 'criteria': {"type": "count", "target_model": "FuelEntry", "value": 10}},
        {'code': 'FUEL_LOG_COUNT_50', 'name': '給油50回達成！', 'description': '給油記録を50回追加する', 'icon_class': 'fas fa-gas-pump', 'category_code': 'fuel', 'category_name': '給油記録', 'share_text_template': '実績「{achievement_name}」解除！給油50回！すごい！⛽ #もとぷっぷー', 'trigger_event_type': EVENT_ADD_FUEL_LOG, 'criteria': {"type": "count", "target_model": "FuelEntry", "value": 50}},
        {'code': 'FUEL_LOG_COUNT_100', 'name': '給油100回達成！', 'description': '給油記録を100回追加する', 'icon_class': 'fas fa-fire-alt', 'category_code': 'fuel', 'category_name': '給油記録', 'share_text_template': '実績「{achievement_name}」解除！給油100回、もはやレジェンド！⛽ #もとぷっぷー', 'trigger_event_type': EVENT_ADD_FUEL_LOG, 'criteria': {"type": "count", "target_model": "FuelEntry", "value": 100}},
        # --- 回数系実績: 整備 ---
        {'code': 'MAINT_LOG_COUNT_10', 'name': '整備10回達成！', 'description': '整備記録を10回追加する', 'icon_class': 'fas fa-tools', 'category_code': 'maintenance', 'category_name': '整備記録', 'share_text_template': '実績「{achievement_name}」解除！整備10回！バイクもピカピカ！🔧 #もとぷっぷー', 'trigger_event_type': EVENT_ADD_MAINTENANCE_LOG, 'criteria': {"type": "count", "target_model": "MaintenanceEntry", "value": 10}},
        {'code': 'MAINT_LOG_COUNT_50', 'name': '整備50回達成！', 'description': '整備記録を50回追加する', 'icon_class': 'fas fa-cogs', 'category_code': 'maintenance', 'category_name': '整備記録', 'share_text_template': '実績「{achievement_name}」解除！整備50回！整備のプロフェッショナル！🔧 #もとぷっぷー', 'trigger_event_type': EVENT_ADD_MAINTENANCE_LOG, 'criteria': {"type": "count", "target_model": "MaintenanceEntry", "value": 50}},
        {'code': 'MAINT_LOG_COUNT_100', 'name': '整備100回達成！', 'description': '整備記録を100回追加する', 'icon_class': 'fas fa-user-cog', 'category_code': 'maintenance', 'category_name': '整備記録', 'share_text_template': '実績「{achievement_name}」解除！整備100回！神の手を持つ者！🔧 #もとぷっぷー', 'trigger_event_type': EVENT_ADD_MAINTENANCE_LOG, 'criteria': {"type": "count", "target_model": "MaintenanceEntry", "value": 100}},
        # --- 回数系実績: ノート ---
        {'code': 'NOTE_COUNT_10', 'name': 'ノート10件作成！', 'description': 'ノート/タスクを10件記録する', 'icon_class': 'fas fa-book-open', 'category_code': 'general', 'category_name': 'その他', 'share_text_template': '実績「{achievement_name}」解除！ノート10件！記録が軌跡を創る！📝 #もとぷっぷー', 'trigger_event_type': EVENT_ADD_NOTE, 'criteria': {"type": "count", "target_model": "GeneralNote", "value": 10}},
        {'code': 'NOTE_COUNT_50', 'name': 'ノート50件作成！', 'description': 'ノート/タスクを50件記録する', 'icon_class': 'fas fa-archive', 'category_code': 'general', 'category_name': 'その他', 'share_text_template': '実績「{achievement_name}」解除！ノート50件！あなたのバイク物語！📝 #もとぷっぷー', 'trigger_event_type': EVENT_ADD_NOTE, 'criteria': {"type": "count", "target_model": "GeneralNote", "value": 50}},
        {'code': 'NOTE_COUNT_100', 'name': 'ノート100件作成！', 'description': 'ノート/タスクを100件記録する', 'icon_class': 'fas fa-landmark', 'category_code': 'general', 'category_name': 'その他', 'share_text_template': '実績「{achievement_name}」解除！ノート100件！歴史の編纂者！📝 #もとぷっぷー', 'trigger_event_type': EVENT_ADD_NOTE, 'criteria': {"type": "count", "target_model": "GeneralNote", "value": 100}},

        # --- 走行距離達成系 (特定の車両で) ---
        {'code': 'MILEAGE_VEHICLE_1000KM', 'name': '愛車と1,000km！', 'description': '1台の車両で実走行距離1,000kmを達成', 'icon_class': 'fas fa-road', 'category_code': 'vehicle', 'category_name': '車両関連', 'share_text_template': '実績「{achievement_name}」解除！愛車との旅路が1,000kmに！🛣️ #もとぷっぷー', 'trigger_event_type': EVENT_ADD_FUEL_LOG, 'criteria': {"type": "mileage_vehicle", "value_km": 1000}},
        {'code': 'MILEAGE_VEHICLE_10000KM', 'name': '愛車と10,000km！', 'description': '1台の車両で実走行距離10,000kmを達成', 'icon_class': 'fas fa-globe-asia', 'category_code': 'vehicle', 'category_name': '車両関連', 'share_text_template': '実績「{achievement_name}」解除！10,000km走破！共に刻んだ歴史！🌏 #もとぷっぷー', 'trigger_event_type': EVENT_ADD_FUEL_LOG, 'criteria': {"type": "mileage_vehicle", "value_km": 10000}},
        {'code': 'MILEAGE_VEHICLE_100000KM', 'name': '愛車と100,000km！', 'description': '1台の車両で実走行距離100,000kmを達成', 'icon_class': 'fas fa-rocket', 'category_code': 'vehicle', 'category_name': '車両関連', 'share_text_template': '実績「{achievement_name}」解除！100,000km走破！伝説の相棒と共に！🚀 #もとぷっぷー', 'trigger_event_type': EVENT_ADD_FUEL_LOG, 'criteria': {"type": "mileage_vehicle", "value_km": 100000}},

        # --- 車両登録台数系 ---
        {'code': 'VEHICLE_COUNT_3', 'name': 'バイクコレクター (3台)', 'description': '車両を3台登録する', 'icon_class': 'fas fa-warehouse', 'category_code': 'vehicle', 'category_name': '車両関連', 'share_text_template': '実績「{achievement_name}」解除！3台の愛車！コレクションの始まり！ガレージが華やかに！ #もとぷっぷー', 'trigger_event_type': EVENT_ADD_VEHICLE, 'criteria': {"type": "vehicle_count", "value": 3}},
        {'code': 'VEHICLE_COUNT_5', 'name': 'モーターヘッド (5台)', 'description': '車両を5台登録する', 'icon_class': 'fas fa-industry', 'category_code': 'vehicle', 'category_name': '車両関連', 'share_text_template': '実績「{achievement_name}」解除！5台の相棒！気分はもうオーナーズクラブ代表！ #もとぷっぷー', 'trigger_event_type': EVENT_ADD_VEHICLE, 'criteria': {"type": "vehicle_count", "value": 5}},
        {'code': 'VEHICLE_COUNT_10', 'name': 'バイク王 (10台)', 'description': '車両を10台登録する', 'icon_class': 'fas fa-crown', 'category_code': 'vehicle', 'category_name': '車両関連', 'share_text_template': '実績「{achievement_name}」解除！10台のバイクに囲まれる、夢のバイク王！👑 #もとぷっぷー', 'trigger_event_type': EVENT_ADD_VEHICLE, 'criteria': {"type": "vehicle_count", "value": 10}},
    ]
    op.bulk_insert(achievement_definitions_table, new_achievements_data)
    # ▲▲▲ 実績定義データの投入処理ここまで ▲▲▲


def downgrade():
    # ### commands auto generated by Alembic - START ###
    # with op.batch_alter_table('users', schema=None) as batch_op:
    #     batch_op.alter_column('misskey_user_id',
    #            existing_type=sa.VARCHAR(length=100),
    #            comment=None, # ダミー変更を戻す処理は削除またはコメントアウト
    #            existing_comment='username for miskey',
    #            existing_nullable=False)
    # ### commands auto generated by Alembic - END ###

    # ▼▼▼ 追加した実績定義データを削除する処理 ▼▼▼
    achievement_codes_to_delete = [
        'FUEL_LOG_COUNT_10', 'FUEL_LOG_COUNT_50', 'FUEL_LOG_COUNT_100',
        'MAINT_LOG_COUNT_10', 'MAINT_LOG_COUNT_50', 'MAINT_LOG_COUNT_100',
        'NOTE_COUNT_10', 'NOTE_COUNT_50', 'NOTE_COUNT_100',
        'MILEAGE_VEHICLE_1000KM', 'MILEAGE_VEHICLE_10000KM', 'MILEAGE_VEHICLE_100000KM',
        'VEHICLE_COUNT_3', 'VEHICLE_COUNT_5', 'VEHICLE_COUNT_10'
    ]
    # テーブルオブジェクトを再度定義 (downgradeスコープのため)
    achievement_definitions_table = sa.table(
        'achievement_definitions',
        sa.column('code', sa.String) 
    )
    # IN句を使ってまとめて削除
    # 既存のレコードに影響を与えないように、追加したコードのみを対象とする
    bind = op.get_bind()
    stmt = achievement_definitions_table.delete().where(
        achievement_definitions_table.c.code.in_(achievement_codes_to_delete)
    )
    bind.execute(stmt)
    # ▲▲▲ 追加した実績定義データを削除する処理 ▲▲▲