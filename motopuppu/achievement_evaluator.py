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

    unlocked_achievement_codes = [ua.achievement_code for ua in UserAchievement.query.filter_by(user_id=user.id).all()]
    
    # 評価対象となる実績定義の候補を取得
    # 1. trigger_event_type が現在のイベントタイプに直接一致する実績
    # 2. または、イベントが走行距離更新に関連し、実績が走行距離系の場合 (特別扱い)
    definitions_to_evaluate = []
    
    # 直接トリガーされる実績
    directly_triggered_defs = AchievementDefinition.query.filter(
        AchievementDefinition.trigger_event_type == event_type,
        AchievementDefinition.code.notin_(unlocked_achievement_codes)
    ).all()
    definitions_to_evaluate.extend(directly_triggered_defs)
    current_app.logger.debug(f"Directly triggered definitions for event {event_type}: {[d.code for d in directly_triggered_defs]}")

    # 走行距離系実績の特別評価 (給油または整備イベントの場合)
    if event_type in [EVENT_ADD_FUEL_LOG, EVENT_ADD_MAINTENANCE_LOG]:
        mileage_achievement_defs = AchievementDefinition.query.filter(
            AchievementDefinition.criteria['type'].astext == 'mileage_vehicle', # criteriaのtypeキーで判定
            AchievementDefinition.code.notin_(unlocked_achievement_codes)
        ).all()
        # 重複を避けるために既に追加されていないものだけ追加
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
    個別の実績解除条件を評価する。
    この関数は、メイン処理がコミットされた後のデータベースの状態に基づいて評価を行う。
    """
    code = achievement_def.code
    user_id = user.id
    criteria = achievement_def.criteria if isinstance(achievement_def.criteria, dict) else {} # criteriaがNoneや非辞書の場合も考慮
    
    crit_type = criteria.get("type")
    # target_model は criteria に含めるようにマイグレーションで定義済み
    crit_target_model_name = criteria.get("target_model") # 例: "FuelEntry", "MaintenanceEntry", "GeneralNote"
    crit_value = criteria.get("value") # 回数系、台数系で使用
    crit_value_km = criteria.get("value_km") # 距離系で使用

    current_app.logger.debug(f"Evaluating condition for ach_code: {code}, user_id: {user_id}, event_type: {event_type}, criteria: {criteria}")

    try:
        # --- 「初めての○○」系 (既存ロジック) ---
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
        elif crit_type == "count" and crit_target_model_name and crit_value is not None:
            actual_count = 0
            if crit_target_model_name == "FuelEntry" and event_type == EVENT_ADD_FUEL_LOG:
                actual_count = db.session.query(FuelEntry.id).join(Motorcycle, Motorcycle.id == FuelEntry.motorcycle_id).filter(Motorcycle.user_id == user_id).count()
            elif crit_target_model_name == "MaintenanceEntry" and event_type == EVENT_ADD_MAINTENANCE_LOG:
                actual_count = db.session.query(MaintenanceEntry.id).join(Motorcycle, Motorcycle.id == MaintenanceEntry.motorcycle_id).filter(Motorcycle.user_id == user_id).count()
            elif crit_target_model_name == "GeneralNote" and event_type == EVENT_ADD_NOTE:
                actual_count = GeneralNote.query.filter_by(user_id=user_id).count()
            else: # target_model と event_type の組み合わせが不正な場合は評価しない
                current_app.logger.debug(f"Count achievement {code} skipped: Mismatch or missing target_model/event_type. target_model='{crit_target_model_name}', event_type='{event_type}'")
                return False
            
            current_app.logger.debug(f"Count check for {code}: actual_count={actual_count}, target_value={crit_value}")
            return actual_count == crit_value # ターゲット回数にちょうど達した時に解除

        # --- 車両登録台数系 ---
        elif crit_type == "vehicle_count" and crit_value is not None and event_type == EVENT_ADD_VEHICLE:
            actual_count = Motorcycle.query.filter_by(user_id=user_id).count()
            current_app.logger.debug(f"Vehicle count check for {code}: actual_count={actual_count}, target_value={crit_value}")
            return actual_count == crit_value # ターゲット台数にちょうど達した時に解除

        # --- 走行距離達成系 (特定の車両で) ---
        elif crit_type == "mileage_vehicle" and crit_value_km is not None and \
             (event_type == EVENT_ADD_FUEL_LOG or event_type == EVENT_ADD_MAINTENANCE_LOG): # 給油または整備記録追加時に評価
            if event_data and 'motorcycle_id' in event_data:
                motorcycle_id_updated = event_data['motorcycle_id']
                motorcycle = Motorcycle.query.filter_by(id=motorcycle_id_updated, user_id=user_id).first()
                if motorcycle:
                    current_total_mileage = motorcycle.get_display_total_mileage()
                    current_app.logger.debug(f"Mileage check for {code} (vehicle {motorcycle.id}): current_mileage={current_total_mileage}, target_km={crit_value_km}")
                    # 「以上」で判定し、一度解除されたら再評価されないようにする (notin_ で既に対応済み)
                    # 重要なのは、このイベントで初めて target_km を超えたかどうか。
                    # 簡単な実装としては、現在の走行距離が目標以上であればTrueとする。
                    # より厳密には、このイベント前の走行距離を保存しておき、イベント前 < target <= イベント後 を判定する。
                    # 今回は、現在の走行距離が目標以上であれば解除とし、重複解除はnotin_で防ぐ。
                    return current_total_mileage >= crit_value_km
                else:
                    current_app.logger.warning(f"Mileage achievement {code} evaluation failed: Motorcycle ID {motorcycle_id_updated} not found for user {user_id}.")
                    return False
            else:
                current_app.logger.warning(f"Mileage achievement {code} evaluation skipped: motorcycle_id missing in event_data for event {event_type}")
                return False
        
        # --- 特定カテゴリ整備系 (初回) のような、より複雑なcriteriaを持つものもここに追加可能 ---
        # elif crit_type == "specific_maintenance" and event_type == EVENT_ADD_MAINTENANCE_LOG:
        #     maintenance_category = criteria.get("category_keyword")
        #     target_count = criteria.get("value", 1) # デフォルトは初回
        #     if event_data and 'category' in event_data and maintenance_category:
        #         if maintenance_category.lower() in event_data['category'].lower():
        #             # このカテゴリでの整備回数をカウント
        #             count = MaintenanceEntry.query.join(Motorcycle).filter(
        #                 Motorcycle.user_id == user_id,
        #                 MaintenanceEntry.category.ilike(f'%{maintenance_category}%')
        #             ).count()
        #             return count == target_count
        #     return False

        else:
            current_app.logger.warning(f"No specific evaluation logic defined for achievement code: {code} with event_type: {event_type}, crit_type: {crit_type}. Defaulting to False.")
            return False
            
    except Exception as e:
        current_app.logger.error(f"Error during evaluating achievement condition for {code} (User ID: {user_id}): {e}", exc_info=True)
        return False