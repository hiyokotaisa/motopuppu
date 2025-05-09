# motopuppu/achievement_evaluator.py
from flask import current_app
from .models import (
    db, User, AchievementDefinition, UserAchievement,
    Motorcycle, FuelEntry, MaintenanceEntry, GeneralNote, OdoResetLog
)
from .achievements_utils import unlock_achievement

# --- イベントタイプの定数 ---
EVENT_ADD_VEHICLE = "add_vehicle"
EVENT_ADD_FUEL_LOG = "add_fuel_log"
EVENT_ADD_MAINTENANCE_LOG = "add_maintenance_log"
EVENT_ADD_NOTE = "add_note"
EVENT_ADD_ODO_RESET = "add_odo_reset"

def check_achievements_for_event(user: User, event_type: str, event_data: dict = None):
    """
    指定されたイベントタイプに基づき、関連する実績の解除条件を評価する。(リアルタイム用)
    """
    if not user or not event_type:
        current_app.logger.warning(f"check_achievements_for_event called with invalid user or event_type. User: {user}, Event Type: {event_type}")
        return

    current_app.logger.info(f"Checking achievements for user_id: {user.id}, event_type: {event_type}")
    if event_data:
        current_app.logger.debug(f"Event data: {event_data}")

    unlocked_achievement_codes = [ua.achievement_code for ua in UserAchievement.query.filter_by(user_id=user.id).all()]
    
    definitions_to_evaluate = []
    
    directly_triggered_defs = AchievementDefinition.query.filter(
        AchievementDefinition.trigger_event_type == event_type,
        AchievementDefinition.code.notin_(unlocked_achievement_codes)
    ).all()
    definitions_to_evaluate.extend(directly_triggered_defs)
    current_app.logger.debug(f"Directly triggered definitions for event {event_type}: {[d.code for d in directly_triggered_defs]}")

    if event_type in [EVENT_ADD_FUEL_LOG, EVENT_ADD_MAINTENANCE_LOG]:
        mileage_achievement_defs = AchievementDefinition.query.filter(
            AchievementDefinition.criteria['type'].astext == 'mileage_vehicle',
            AchievementDefinition.code.notin_(unlocked_achievement_codes)
        ).all()
        for m_def in mileage_achievement_defs:
            if m_def not in definitions_to_evaluate:
                definitions_to_evaluate.append(m_def)
        current_app.logger.debug(f"Additionally evaluating mileage definitions: {[d.code for d in mileage_achievement_defs]}")

    if not definitions_to_evaluate:
        current_app.logger.debug(f"No relevant, unachieved definitions found to evaluate for user_id: {user.id}, event_type: {event_type}")
        return

    for ach_def in definitions_to_evaluate:
        current_app.logger.debug(f"Evaluating achievement: {ach_def.code} for user_id: {user.id}")
        if evaluate_achievement_condition(user, ach_def, event_type, event_data): # 既存の評価関数を呼び出し
            current_app.logger.info(f"Condition met for achievement {ach_def.code} for user_id: {user.id}. Attempting to unlock.")
            unlock_achievement(user, ach_def.code)
        else:
            current_app.logger.debug(f"Condition NOT met for achievement {ach_def.code} for user_id: {user.id}")


def evaluate_achievement_condition(user: User, achievement_def: AchievementDefinition, event_type: str, event_data: dict = None) -> bool:
    """
    個別の実績解除条件を評価する。(リアルタイム用)
    イベント発生時のデータ(event_data)や、そのイベントで「初めてN件目に達したか」を判定。
    """
    code = achievement_def.code
    user_id = user.id
    criteria = achievement_def.criteria if isinstance(achievement_def.criteria, dict) else {} 
    
    crit_type = criteria.get("type")
    crit_target_model_name = criteria.get("target_model") 
    crit_value = criteria.get("value") 
    crit_value_km = criteria.get("value_km")

    current_app.logger.debug(f"[REALTIME_EVAL] Evaluating for ach_code: {code}, user_id: {user_id}, event: {event_type}, criteria: {criteria}")

    try:
        # --- 「初めての○○」系 ---
        if code == "FIRST_VEHICLE" and event_type == EVENT_ADD_VEHICLE:
            return Motorcycle.query.filter_by(user_id=user_id).count() == 1
        elif code == "FIRST_FUEL_LOG" and event_type == EVENT_ADD_FUEL_LOG:
            return db.session.query(FuelEntry.id).join(Motorcycle, Motorcycle.id == FuelEntry.motorcycle_id).filter(Motorcycle.user_id == user_id).count() == 1
        elif code == "FIRST_MAINT_LOG" and event_type == EVENT_ADD_MAINTENANCE_LOG:
            return db.session.query(MaintenanceEntry.id).join(Motorcycle, Motorcycle.id == MaintenanceEntry.motorcycle_id).filter(Motorcycle.user_id == user_id).count() == 1
        elif code == "FIRST_NOTE" and event_type == EVENT_ADD_NOTE:
            return GeneralNote.query.filter_by(user_id=user_id).count() == 1
        elif code == "FIRST_ODO_RESET" and event_type == EVENT_ADD_ODO_RESET:
            return db.session.query(OdoResetLog.id).join(Motorcycle, Motorcycle.id == OdoResetLog.motorcycle_id).filter(Motorcycle.user_id == user_id).count() == 1

        # --- N回記録系 ---
        elif crit_type == "count" and crit_target_model_name and isinstance(crit_value, int):
            actual_count = 0
            if crit_target_model_name == "FuelEntry" and event_type == EVENT_ADD_FUEL_LOG:
                actual_count = db.session.query(FuelEntry.id).join(Motorcycle, Motorcycle.id == FuelEntry.motorcycle_id).filter(Motorcycle.user_id == user_id).count()
            elif crit_target_model_name == "MaintenanceEntry" and event_type == EVENT_ADD_MAINTENANCE_LOG:
                actual_count = db.session.query(MaintenanceEntry.id).join(Motorcycle, Motorcycle.id == MaintenanceEntry.motorcycle_id).filter(Motorcycle.user_id == user_id).count()
            elif crit_target_model_name == "GeneralNote" and event_type == EVENT_ADD_NOTE:
                actual_count = GeneralNote.query.filter_by(user_id=user_id).count()
            else: return False
            return actual_count == crit_value 

        # --- 車両登録台数系 ---
        elif crit_type == "vehicle_count" and isinstance(crit_value, int) and event_type == EVENT_ADD_VEHICLE:
            actual_count = Motorcycle.query.filter_by(user_id=user_id).count()
            return actual_count == crit_value

        # --- 走行距離達成系 (特定の車両で) ---
        elif crit_type == "mileage_vehicle" and isinstance(crit_value_km, int) and \
             (event_type == EVENT_ADD_FUEL_LOG or event_type == EVENT_ADD_MAINTENANCE_LOG):
            if event_data and 'motorcycle_id' in event_data:
                motorcycle = Motorcycle.query.filter_by(id=event_data['motorcycle_id'], user_id=user_id).first()
                if motorcycle:
                    return motorcycle.get_display_total_mileage() >= crit_value_km
            return False
        
        else: return False
    except Exception as e:
        current_app.logger.error(f"Error during [REALTIME_EVAL] for {code} (User ID: {user_id}): {e}", exc_info=True)
        return False

# ▼▼▼ 遡及評価用の新しい関数 ▼▼▼
def evaluate_achievement_condition_for_backfill(user: User, achievement_def: AchievementDefinition) -> bool:
    """
    個別の実績解除条件を遡及的に評価する。(現在のDB状態のみで判定)
    """
    code = achievement_def.code
    user_id = user.id
    criteria = achievement_def.criteria if isinstance(achievement_def.criteria, dict) else {}
    
    crit_type = criteria.get("type")
    crit_target_model_name = criteria.get("target_model")
    crit_value = criteria.get("value")
    crit_value_km = criteria.get("value_km")

    current_app.logger.debug(f"[BACKFILL_EVAL] Evaluating for ach_code: {code}, user_id: {user_id}, criteria: {criteria}")

    try:
        # --- 「初めての○○」系 ---
        if code == "FIRST_VEHICLE":
            return Motorcycle.query.filter_by(user_id=user_id).count() > 0
        elif code == "FIRST_FUEL_LOG":
            return db.session.query(FuelEntry.id).join(Motorcycle, Motorcycle.id == FuelEntry.motorcycle_id).filter(Motorcycle.user_id == user_id).count() > 0
        elif code == "FIRST_MAINT_LOG":
            return db.session.query(MaintenanceEntry.id).join(Motorcycle, Motorcycle.id == MaintenanceEntry.motorcycle_id).filter(Motorcycle.user_id == user_id).count() > 0
        elif code == "FIRST_NOTE":
            return GeneralNote.query.filter_by(user_id=user_id).count() > 0
        elif code == "FIRST_ODO_RESET":
            return db.session.query(OdoResetLog.id).join(Motorcycle, Motorcycle.id == OdoResetLog.motorcycle_id).filter(Motorcycle.user_id == user_id).count() > 0

        # --- N回記録系 ---
        elif crit_type == "count" and crit_target_model_name and isinstance(crit_value, int):
            actual_count = 0
            if crit_target_model_name == "FuelEntry":
                actual_count = db.session.query(FuelEntry.id).join(Motorcycle, Motorcycle.id == FuelEntry.motorcycle_id).filter(Motorcycle.user_id == user_id).count()
            elif crit_target_model_name == "MaintenanceEntry":
                actual_count = db.session.query(MaintenanceEntry.id).join(Motorcycle, Motorcycle.id == MaintenanceEntry.motorcycle_id).filter(Motorcycle.user_id == user_id).count()
            elif crit_target_model_name == "GeneralNote":
                actual_count = GeneralNote.query.filter_by(user_id=user_id).count()
            else: return False
            return actual_count >= crit_value # 遡及なので「以上」で判定

        # --- 車両登録台数系 ---
        elif crit_type == "vehicle_count" and isinstance(crit_value, int):
            actual_count = Motorcycle.query.filter_by(user_id=user_id).count()
            return actual_count >= crit_value # 遡及なので「以上」

        # --- 走行距離達成系 (特定の車両で) ---
        elif crit_type == "mileage_vehicle" and isinstance(crit_value_km, int):
            # ユーザーの全車両をチェックし、いずれか1台でも達成していればOK
            user_motorcycles = Motorcycle.query.filter_by(user_id=user_id).all()
            for motorcycle in user_motorcycles:
                if motorcycle.get_display_total_mileage() >= crit_value_km:
                    # 本来は「この車両でこの距離実績を解除したか」をUserAchievementに記録・参照したいが、
                    # 現状のUserAchievementは(user, achievement_code)でユニークなので、
                    # 「ユーザーがこの距離実績を解除したか」しか判定できない。
                    # なので、いずれかの車両で達成していれば、その実績コードは解除とする。
                    return True
            return False
        
        else: return False
    except Exception as e:
        current_app.logger.error(f"Error during [BACKFILL_EVAL] for {code} (User ID: {user_id}): {e}", exc_info=True)
        return False