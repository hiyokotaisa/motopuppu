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

    # --- ▼▼▼ フェーズ1変更点 (走行距離実績は公道車のみ対象とする前提。is_racerで分岐は不要かも) ▼▼▼
    # 走行距離実績の評価は、Motorcycle.get_display_total_mileage() が公道車専用の値を返すため、
    # レーサー車両のイベント(EVENT_ADD_FUEL_LOG や EVENT_ADD_MAINTENANCE_LOG はレーサーには発生しない)では
    # 適切に評価されないか、または意図しない評価になる可能性がある。
    # ただし、EVENT_ADD_FUEL_LOG や EVENT_ADD_MAINTENANCE_LOG は公道車に対してのみ発生するため、
    # mileage_achievement_defs の評価対象は実質的に公道車に限られる。
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲
    if event_type in [EVENT_ADD_FUEL_LOG, EVENT_ADD_MAINTENANCE_LOG]: # これらは公道車のみのイベント
        mileage_achievement_defs = AchievementDefinition.query.filter(
            AchievementDefinition.criteria['type'].astext == 'mileage_vehicle', # mileage_vehicle は公道車の走行距離を指す
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
        if evaluate_achievement_condition(user, ach_def, event_type, event_data):
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
    # --- ▼▼▼ フェーズ1変更点 (新しい criteria type 用) ▼▼▼
    # (crit_value_hours のような稼働時間用のキーも将来的に追加される可能性がある)
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲

    current_app.logger.debug(f"[REALTIME_EVAL] Evaluating for ach_code: {code}, user_id: {user_id}, event: {event_type}, criteria: {criteria}, event_data: {event_data}")

    try:
        # --- 「初めての○○」系 (変更なし、これらは車種を問わない実績) ---
        if code == "FIRST_VEHICLE" and event_type == EVENT_ADD_VEHICLE:
            # vehicle_count_after_add は全車種のカウント
            return event_data and event_data.get('vehicle_count_after_add') == 1
        elif code == "FIRST_FUEL_LOG" and event_type == EVENT_ADD_FUEL_LOG:
            # FuelLog は公道車のみなので、カウントが1ならOK
            return db.session.query(FuelEntry.id).join(Motorcycle, Motorcycle.id == FuelEntry.motorcycle_id).filter(Motorcycle.user_id == user_id).count() == 1
        elif code == "FIRST_MAINT_LOG" and event_type == EVENT_ADD_MAINTENANCE_LOG:
            # --- ▼▼▼ 変更点 ▼▼▼ ---
            # 「システム登録」カテゴリは除外する
            return db.session.query(MaintenanceEntry.id).join(Motorcycle, Motorcycle.id == MaintenanceEntry.motorcycle_id).filter(
                Motorcycle.user_id == user_id,
                MaintenanceEntry.category != 'システム登録'
            ).count() == 1
            # --- ▲▲▲ 変更点 ▲▲▲ ---
        elif code == "FIRST_NOTE" and event_type == EVENT_ADD_NOTE:
            return GeneralNote.query.filter_by(user_id=user_id).count() == 1
        elif code == "FIRST_ODO_RESET" and event_type == EVENT_ADD_ODO_RESET:
            # OdoReset は公道車のみなので、カウントが1ならOK
            return db.session.query(OdoResetLog.id).join(Motorcycle, Motorcycle.id == OdoResetLog.motorcycle_id).filter(Motorcycle.user_id == user_id).count() == 1

        # --- N回記録系 (変更なし、これらは公道車対象の記録が主) ---
        elif crit_type == "count" and crit_target_model_name and isinstance(crit_value, int):
            actual_count = 0
            if crit_target_model_name == "FuelEntry" and event_type == EVENT_ADD_FUEL_LOG:
                actual_count = db.session.query(FuelEntry.id).join(Motorcycle, Motorcycle.id == FuelEntry.motorcycle_id).filter(Motorcycle.user_id == user_id).count()
            elif crit_target_model_name == "MaintenanceEntry" and event_type == EVENT_ADD_MAINTENANCE_LOG:
                # --- ▼▼▼ 変更点 ▼▼▼ ---
                actual_count = db.session.query(MaintenanceEntry.id).join(Motorcycle, Motorcycle.id == MaintenanceEntry.motorcycle_id).filter(
                    Motorcycle.user_id == user_id,
                    MaintenanceEntry.category != 'システム登録'
                ).count()
                # --- ▲▲▲ 変更点 ▲▲▲ ---
            elif crit_target_model_name == "GeneralNote" and event_type == EVENT_ADD_NOTE:
                actual_count = GeneralNote.query.filter_by(user_id=user_id).count()
            else: return False
            return actual_count == crit_value

        # --- 車両登録台数系 (全車種対象) ---
        elif crit_type == "vehicle_count" and isinstance(crit_value, int) and event_type == EVENT_ADD_VEHICLE:
            # event_data から追加後の全車種カウントを取得
            return event_data and event_data.get('vehicle_count_after_add') == crit_value

        # --- 走行距離達成系 (特定の公道車両で) ---
        elif crit_type == "mileage_vehicle" and isinstance(crit_value_km, int) and \
             (event_type == EVENT_ADD_FUEL_LOG or event_type == EVENT_ADD_MAINTENANCE_LOG): # これらは公道車のイベント
            if event_data and 'motorcycle_id' in event_data:
                # 対象車両は公道車のはず
                motorcycle = Motorcycle.query.filter_by(id=event_data['motorcycle_id'], user_id=user_id, is_racer=False).first()
                if motorcycle:
                    return motorcycle.get_display_total_mileage() >= crit_value_km
            return False

        # --- ▼▼▼ フェーズ1変更点 (新しい実績タイプの評価ロジック) ▼▼▼ ---
        elif crit_type == "first_racer_vehicle" and event_type == EVENT_ADD_VEHICLE:
            # event_data に is_racer と racer_vehicle_count_after_add が含まれる前提
            if event_data and event_data.get('is_racer'):
                return event_data.get('racer_vehicle_count_after_add') == 1
            return False
        elif crit_type == "racer_vehicle_count" and isinstance(crit_value, int) and event_type == EVENT_ADD_VEHICLE:
            # event_data に is_racer と racer_vehicle_count_after_add が含まれる前提
            # 追加されたのがレーサー車両の場合のみ評価
            if event_data and event_data.get('is_racer'):
                return event_data.get('racer_vehicle_count_after_add') == crit_value
            return False
        # --- ▲▲▲ フェーズ1変更点 ▲▲▲

        else: return False
    except Exception as e:
        current_app.logger.error(f"Error during [REALTIME_EVAL] for {code} (User ID: {user_id}): {e}", exc_info=True)
        return False

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
    # --- ▼▼▼ フェーズ1変更点 (新しい criteria type 用) ▼▼▼
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲

    current_app.logger.debug(f"[BACKFILL_EVAL] Evaluating for ach_code: {code}, user_id: {user_id}, criteria: {criteria}")

    try:
        # --- 「初めての○○」系 (変更なし) ---
        if code == "FIRST_VEHICLE": # 全車種対象
            return Motorcycle.query.filter_by(user_id=user_id).count() > 0
        elif code == "FIRST_FUEL_LOG": # 公道車のみ
            return db.session.query(FuelEntry.id).join(Motorcycle, Motorcycle.id == FuelEntry.motorcycle_id).filter(Motorcycle.user_id == user_id, Motorcycle.is_racer==False).count() > 0
        elif code == "FIRST_MAINT_LOG":
            # --- ▼▼▼ 変更点 ▼▼▼ ---
            # 「システム登録」を除外
            return db.session.query(MaintenanceEntry.id).join(Motorcycle, Motorcycle.id == MaintenanceEntry.motorcycle_id).filter(
                Motorcycle.user_id == user_id,
                Motorcycle.is_racer==False,
                MaintenanceEntry.category != 'システム登録'
            ).count() > 0
            # --- ▲▲▲ 変更点 ▲▲▲ ---
        elif code == "FIRST_NOTE": # 車種問わず
            return GeneralNote.query.filter_by(user_id=user_id).count() > 0
        elif code == "FIRST_ODO_RESET": # 公道車のみ
            return db.session.query(OdoResetLog.id).join(Motorcycle, Motorcycle.id == OdoResetLog.motorcycle_id).filter(Motorcycle.user_id == user_id, Motorcycle.is_racer==False).count() > 0

        # --- N回記録系 (公道車対象の記録が主) ---
        elif crit_type == "count" and crit_target_model_name and isinstance(crit_value, int):
            actual_count = 0
            if crit_target_model_name == "FuelEntry":
                actual_count = db.session.query(FuelEntry.id).join(Motorcycle, Motorcycle.id == FuelEntry.motorcycle_id).filter(Motorcycle.user_id == user_id, Motorcycle.is_racer==False).count()
            elif crit_target_model_name == "MaintenanceEntry":
                # --- ▼▼▼ 変更点 ▼▼▼ ---
                actual_count = db.session.query(MaintenanceEntry.id).join(Motorcycle, Motorcycle.id == MaintenanceEntry.motorcycle_id).filter(
                    Motorcycle.user_id == user_id,
                    Motorcycle.is_racer==False,
                    MaintenanceEntry.category != 'システム登録'
                ).count()
                # --- ▲▲▲ 変更点 ▲▲▲ ---
            elif crit_target_model_name == "GeneralNote": # 車種問わず
                actual_count = GeneralNote.query.filter_by(user_id=user_id).count()
            else: return False
            return actual_count >= crit_value

        # --- 車両登録台数系 (全車種対象) ---
        elif crit_type == "vehicle_count" and isinstance(crit_value, int):
            actual_count = Motorcycle.query.filter_by(user_id=user_id).count()
            return actual_count >= crit_value

        # --- 走行距離達成系 (特定の公道車両で) ---
        elif crit_type == "mileage_vehicle" and isinstance(crit_value_km, int):
            user_public_motorcycles = Motorcycle.query.filter_by(user_id=user_id, is_racer=False).all() # 公道車のみ
            for motorcycle in user_public_motorcycles:
                if motorcycle.get_display_total_mileage() >= crit_value_km:
                    return True
            return False

        # --- ▼▼▼ フェーズ1変更点 (新しい実績タイプの遡及評価ロジック) ▼▼▼ ---
        elif crit_type == "first_racer_vehicle":
            return Motorcycle.query.filter_by(user_id=user_id, is_racer=True).count() > 0
        elif crit_type == "racer_vehicle_count" and isinstance(crit_value, int):
            return Motorcycle.query.filter_by(user_id=user_id, is_racer=True).count() >= crit_value
        # --- ▲▲▲ フェーズ1変更点 ▲▲▲

        else: return False
    except Exception as e:
        current_app.logger.error(f"Error during [BACKFILL_EVAL] for {code} (User ID: {user_id}): {e}", exc_info=True)
        return False