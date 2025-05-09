# motopuppu/achievement_evaluator.py
from flask import current_app
from .models import (
    db, User, AchievementDefinition, UserAchievement,
    Motorcycle, FuelEntry, MaintenanceEntry, GeneralNote, OdoResetLog
)
from .achievements_utils import unlock_achievement # achievements_utils.py からインポート

# --- イベントタイプの定数 ---
EVENT_ADD_VEHICLE = "add_vehicle"
EVENT_ADD_FUEL_LOG = "add_fuel_log"
EVENT_ADD_MAINTENANCE_LOG = "add_maintenance_log"
EVENT_ADD_NOTE = "add_note"
EVENT_ADD_ODO_RESET = "add_odo_reset"
# 必要に応じて他のイベントタイプを追加

def check_achievements_for_event(user: User, event_type: str, event_data: dict = None):
    """
    指定されたイベントタイプに基づき、関連する実績の解除条件を評価する。
    この関数は、メイン処理のコミットが成功した後に呼び出されることを想定。
    """
    if not user or not event_type:
        current_app.logger.warning(f"check_achievements_for_event called with invalid user or event_type. User: {user}, Event Type: {event_type}")
        return

    current_app.logger.info(f"Checking achievements for user_id: {user.id}, event_type: {event_type}")
    if event_data:
        current_app.logger.debug(f"Event data: {event_data}")

    # このイベントタイプをトリガーとする未解除の実績定義を取得
    # まずユーザーが既に解除した実績のコードリストを取得
    unlocked_achievement_codes = [ua.achievement_code for ua in UserAchievement.query.filter_by(user_id=user.id).all()]
    
    relevant_definitions = AchievementDefinition.query.filter(
        AchievementDefinition.trigger_event_type == event_type,
        AchievementDefinition.code.notin_(unlocked_achievement_codes) # まだ解除していないもののみ対象
    ).all()

    if not relevant_definitions:
        current_app.logger.debug(f"No relevant, unachieved definitions found for user_id: {user.id}, event_type: {event_type}")
        return

    for ach_def in relevant_definitions:
        current_app.logger.debug(f"Evaluating achievement: {ach_def.code} for user_id: {user.id}")
        # evaluate_achievement_condition はメインの処理がコミットされた後のDB状態に基づいて評価
        if evaluate_achievement_condition(user, ach_def, event_type, event_data):
            current_app.logger.info(f"Condition met for achievement {ach_def.code} for user_id: {user.id}. Attempting to unlock.")
            # unlock_achievement内で UserAchievement の作成、コミット、フラッシュ通知まで行う
            unlock_achievement(user, ach_def.code)
        else:
            current_app.logger.debug(f"Condition NOT met for achievement {ach_def.code} for user_id: {user.id}")


def evaluate_achievement_condition(user: User, achievement_def: AchievementDefinition, event_type: str, event_data: dict = None) -> bool:
    """
    個別の実績解除条件を評価する。
    この関数は、メイン処理がコミットされた後のデータベースの状態に基づいて評価を行う。
    """
    code = achievement_def.code
    user_id = user.id
    current_app.logger.debug(f"Evaluating condition for achievement_code: {code}, user_id: {user_id}, event_type: {event_type}")

    try:
        if code == "FIRST_VEHICLE" and event_type == EVENT_ADD_VEHICLE:
            # 車両追加イベントの場合、そのユーザーの車両総数を確認
            vehicle_count = Motorcycle.query.filter_by(user_id=user_id).count()
            current_app.logger.debug(f"FIRST_VEHICLE check: vehicle_count = {vehicle_count}")
            return vehicle_count == 1 # このイベントで1台目になった

        elif code == "FIRST_FUEL_LOG" and event_type == EVENT_ADD_FUEL_LOG:
            fuel_log_count = db.session.query(FuelEntry.id)\
                .join(Motorcycle, Motorcycle.id == FuelEntry.motorcycle_id)\
                .filter(Motorcycle.user_id == user_id).count()
            current_app.logger.debug(f"FIRST_FUEL_LOG check: fuel_log_count = {fuel_log_count}")
            return fuel_log_count == 1

        elif code == "FIRST_MAINT_LOG" and event_type == EVENT_ADD_MAINTENANCE_LOG:
            maint_log_count = db.session.query(MaintenanceEntry.id)\
                .join(Motorcycle, Motorcycle.id == MaintenanceEntry.motorcycle_id)\
                .filter(Motorcycle.user_id == user_id).count()
            current_app.logger.debug(f"FIRST_MAINT_LOG check: maint_log_count = {maint_log_count}")
            return maint_log_count == 1
            
        elif code == "FIRST_NOTE" and event_type == EVENT_ADD_NOTE:
            note_count = GeneralNote.query.filter_by(user_id=user_id).count()
            current_app.logger.debug(f"FIRST_NOTE check: note_count = {note_count}")
            return note_count == 1

        elif code == "FIRST_ODO_RESET" and event_type == EVENT_ADD_ODO_RESET:
            odo_reset_count = db.session.query(OdoResetLog.id)\
                .join(Motorcycle, Motorcycle.id == OdoResetLog.motorcycle_id)\
                .filter(Motorcycle.user_id == user_id).count()
            current_app.logger.debug(f"FIRST_ODO_RESET check: odo_reset_count = {odo_reset_count}")
            return odo_reset_count == 1
        
        # 他の実績の評価ロジックをここに追加
        # elif code == "SOME_OTHER_ACHIEVEMENT" and event_type == SOME_EVENT_TYPE:
        #     # ... 評価ロジック ...
        #     return True or False

        else:
            current_app.logger.warning(f"No specific evaluation logic defined for achievement code: {code} with event_type: {event_type}. Defaulting to False.")
            return False # 未定義または該当しない場合は解除しない
            
    except Exception as e:
        current_app.logger.error(f"Error during evaluating achievement condition for {code} (User ID: {user_id}): {e}", exc_info=True)
        return False # エラー発生時は解除しない