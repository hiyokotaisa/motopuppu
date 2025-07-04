# motopuppu/services.py

from flask import current_app
from datetime import date
from dateutil.relativedelta import relativedelta
from sqlalchemy import func, union_all
from sqlalchemy.orm import joinedload

from .models import db, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder

# --- データ取得・計算ヘルパー ---

def get_latest_total_distance(motorcycle_id, offset_val):
    """指定された車両の最新の総走行距離を取得する"""
    latest_fuel_dist = db.session.query(db.func.max(FuelEntry.total_distance)).filter(
        FuelEntry.motorcycle_id == motorcycle_id).scalar() or 0
    latest_maint_dist = db.session.query(db.func.max(MaintenanceEntry.total_distance_at_maintenance)).filter(
        MaintenanceEntry.motorcycle_id == motorcycle_id).scalar() or 0
    return max(latest_fuel_dist, latest_maint_dist, offset_val if offset_val is not None else 0)


def calculate_average_kpl(motorcycle: Motorcycle):
    """車両全体の平均燃費を計算する"""
    if motorcycle.is_racer:
        return None

    all_full_tank_entries = FuelEntry.query.filter(
        FuelEntry.motorcycle_id == motorcycle.id,
        FuelEntry.is_full_tank == True
    ).order_by(FuelEntry.total_distance.asc()).all()

    if len(all_full_tank_entries) < 2:
        return None

    total_distance = 0.0
    total_fuel = 0.0

    for i in range(len(all_full_tank_entries) - 1):
        start_entry = all_full_tank_entries[i]
        end_entry = all_full_tank_entries[i+1]

        if start_entry.exclude_from_average or end_entry.exclude_from_average:
            continue

        distance_diff = end_entry.total_distance - start_entry.total_distance

        fuel_in_interval = db.session.query(func.sum(FuelEntry.fuel_volume)).filter(
            FuelEntry.motorcycle_id == motorcycle.id,
            FuelEntry.total_distance > start_entry.total_distance,
            FuelEntry.total_distance <= end_entry.total_distance,
            FuelEntry.exclude_from_average == False
        ).scalar() or 0.0

        if distance_diff > 0 and fuel_in_interval > 0:
            total_distance += distance_diff
            total_fuel += fuel_in_interval

    if total_fuel > 0 and total_distance > 0:
        try:
            return round(total_distance / total_fuel, 2)
        except ZeroDivisionError:
            return None
    return None

# --- ダッシュボード用サービス関数 ---

def get_upcoming_reminders(user_motorcycles_all, user_id):
    """メンテナンスリマインダーを取得・計算する"""
    upcoming_reminders = []
    today = date.today()

    KM_THRESHOLD_WARNING = current_app.config.get('REMINDER_KM_WARNING', 500)
    DAYS_THRESHOLD_WARNING = current_app.config.get('REMINDER_DAYS_WARNING', 14)
    KM_THRESHOLD_DANGER = current_app.config.get('REMINDER_KM_DANGER', 0)
    DAYS_THRESHOLD_DANGER = current_app.config.get('REMINDER_DAYS_DANGER', 0)

    current_public_distances = {}
    for m in user_motorcycles_all:
        if not m.is_racer:
            current_public_distances[m.id] = get_latest_total_distance(
                m.id, m.odometer_offset)

    all_reminders = MaintenanceReminder.query.options(db.joinedload(MaintenanceReminder.motorcycle)).join(Motorcycle).filter(
        Motorcycle.user_id == user_id).all()

    for reminder in all_reminders:
        motorcycle = reminder.motorcycle
        status = 'ok'
        messages = []
        due_info_parts = []
        is_due = False

        if not motorcycle.is_racer and reminder.interval_km and reminder.last_done_km is not None:
            current_km = current_public_distances.get(motorcycle.id, 0)
            next_km_due = reminder.last_done_km + reminder.interval_km
            remaining_km = next_km_due - current_km
            due_info_parts.append(f"{next_km_due:,} km")

            if remaining_km <= KM_THRESHOLD_DANGER:
                messages.append(f"距離超過 (現在 {current_km:,} km)")
                status = 'danger'
                is_due = True
            elif remaining_km <= KM_THRESHOLD_WARNING:
                messages.append(f"あと {remaining_km:,} km")
                status = 'warning'
                is_due = True

        if reminder.interval_months and reminder.last_done_date:
            try:
                next_date_due = reminder.last_done_date + \
                    relativedelta(months=reminder.interval_months)
                remaining_days = (next_date_due - today).days
                due_info_parts.append(f"{next_date_due.strftime('%Y-%m-%d')}")
                period_status = 'ok'
                period_message = ''
                if remaining_days <= DAYS_THRESHOLD_DANGER:
                    period_status = 'danger'
                    period_message = f"期限超過"
                elif remaining_days <= DAYS_THRESHOLD_WARNING:
                    period_status = 'warning'
                    period_message = f"あと {remaining_days} 日"

                if period_status != 'ok':
                    is_due = True
                    messages.append(period_message)
                    if (period_status == 'danger') or (period_status == 'warning' and status != 'danger'):
                        status = period_status
            except Exception as e:
                current_app.logger.error(
                    f"Error calculating date reminder {reminder.id}: {e}")
                messages.append("日付計算エラー")
                status = 'warning'
                is_due = True

        if is_due:
            last_done_str = "未実施"
            if reminder.last_done_date:
                last_done_str = reminder.last_done_date.strftime(
                    '%Y-%m-%d')
                if not motorcycle.is_racer and reminder.last_done_km is not None:
                    last_done_str += f" ({reminder.last_done_km:,} km)"
            elif not motorcycle.is_racer and reminder.last_done_km is not None:
                last_done_str = f"{reminder.last_done_km:,} km"

            upcoming_reminders.append({
                'reminder_id': reminder.id,
                'motorcycle_id': motorcycle.id,
                'motorcycle_name': motorcycle.name,
                'task': reminder.task_description,
                'status': status,
                'message': ", ".join(messages) if messages else "要確認",
                'due_info': " / ".join(due_info_parts) if due_info_parts else '未設定',
                'last_done': last_done_str,
                'is_racer': motorcycle.is_racer
            })

    upcoming_reminders.sort(
        key=lambda x: (x['status'] != 'danger', x['status'] != 'warning'))
    return upcoming_reminders


def get_recent_logs(model, vehicle_ids, order_by_cols, selected_vehicle_id=None, start_date=None, end_date=None, extra_filters=None, limit=5):
    """指定されたモデルの直近ログを取得する共通関数"""
    query = model.query.options(db.joinedload(model.motorcycle)).filter(
        model.motorcycle_id.in_(vehicle_ids)
    )

    if selected_vehicle_id:
        query = query.filter(model.motorcycle_id == selected_vehicle_id)
    
    if start_date:
        # モデルに応じて日付カラムを特定
        date_column = getattr(model, 'entry_date', getattr(model, 'maintenance_date', None))
        if date_column:
            query = query.filter(date_column.between(start_date, end_date))
    
    if extra_filters:
        for f in extra_filters:
            query = query.filter(f)
            
    return query.order_by(*order_by_cols).limit(limit).all()


def get_dashboard_stats(user_motorcycles_all, user_motorcycle_ids_public, target_vehicle_for_stats=None, start_date=None, end_date=None):
    """ダッシュボードの統計カード情報を計算して返す"""
    stats = {
        'primary_metric_val': 0, 'primary_metric_unit': '', 'primary_metric_label': '-',
        'is_racer_stats': False, 'average_kpl_val': None, 'average_kpl_label': '-',
        'total_fuel_cost': 0, 'total_maint_cost': 0, 'cost_label': '-',
    }

    if target_vehicle_for_stats:
        stats['is_racer_stats'] = target_vehicle_for_stats.is_racer
        if target_vehicle_for_stats.is_racer:
            stats['primary_metric_val'] = target_vehicle_for_stats.total_operating_hours if target_vehicle_for_stats.total_operating_hours is not None else 0
            stats['primary_metric_unit'] = '時間'
            stats['primary_metric_label'] = target_vehicle_for_stats.name
            stats['average_kpl_label'] = f"{target_vehicle_for_stats.name} (レーサー)"
        else: # 公道車（個別）
            vehicle_id = target_vehicle_for_stats.id
            fuel_q = db.session.query(FuelEntry.total_distance.label('distance')).filter(FuelEntry.motorcycle_id == vehicle_id)
            maint_q = db.session.query(MaintenanceEntry.total_distance_at_maintenance.label('distance')).filter(MaintenanceEntry.motorcycle_id == vehicle_id)
            if start_date:
                fuel_q = fuel_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                maint_q = maint_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))
            
            all_distances_q = fuel_q.union_all(maint_q).subquery()
            result = db.session.query(func.max(all_distances_q.c.distance), func.min(all_distances_q.c.distance)).one_or_none()
            running_dist = 0
            if result and result[0] is not None and result[1] is not None:
                if result[0] != result[1]:
                    running_dist = float(result[0]) - float(result[1])

            stats['primary_metric_val'] = running_dist
            stats['primary_metric_unit'] = 'km'
            stats['primary_metric_label'] = target_vehicle_for_stats.name
            stats['average_kpl_val'] = target_vehicle_for_stats._average_kpl
            stats['average_kpl_label'] = target_vehicle_for_stats.name

            fuel_cost_q = db.session.query(func.sum(FuelEntry.total_cost)).filter(FuelEntry.motorcycle_id == vehicle_id)
            maint_cost_q = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))).filter(MaintenanceEntry.motorcycle_id == vehicle_id)
            if start_date:
                fuel_cost_q = fuel_cost_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                maint_cost_q = maint_cost_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

            stats['total_fuel_cost'] = fuel_cost_q.scalar() or 0
            stats['total_maint_cost'] = maint_cost_q.scalar() or 0
            stats['cost_label'] = target_vehicle_for_stats.name
    else: # 全車両
        # 走行距離
        total_running_distance = 0
        if user_motorcycle_ids_public:
            fuel_dist_q = db.session.query(FuelEntry.motorcycle_id.label('mc_id'), FuelEntry.total_distance.label('distance')).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public))
            maint_dist_q = db.session.query(MaintenanceEntry.motorcycle_id.label('mc_id'), MaintenanceEntry.total_distance_at_maintenance.label('distance')).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public))
            if start_date:
                fuel_dist_q = fuel_dist_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                maint_dist_q = maint_dist_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

            combined_q = union_all(fuel_dist_q, maint_dist_q).subquery()
            vehicle_dists = db.session.query((func.max(combined_q.c.distance) - func.min(combined_q.c.distance)).label('travelled')).group_by(combined_q.c.mc_id).having(func.count(combined_q.c.distance) > 1).subquery()
            total_running_distance = db.session.query(func.sum(vehicle_dists.c.travelled)).scalar() or 0
        
        stats['primary_metric_val'] = total_running_distance
        stats['primary_metric_unit'] = 'km'
        stats['primary_metric_label'] = "すべての公道車"
        
        # 平均燃費
        default_vehicle = next((m for m in user_motorcycles_all if m.is_default), user_motorcycles_all[0] if user_motorcycles_all else None)
        if default_vehicle and not default_vehicle.is_racer:
            stats['average_kpl_val'] = default_vehicle._average_kpl
            stats['average_kpl_label'] = f"デフォルト ({default_vehicle.name})"
        else:
            stats['average_kpl_label'] = "計算対象外"

        # 費用
        if user_motorcycle_ids_public:
            fuel_cost_q = db.session.query(func.sum(FuelEntry.total_cost)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public))
            maint_cost_q = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public))
            if start_date:
                fuel_cost_q = fuel_cost_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                maint_cost_q = maint_cost_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

            stats['total_fuel_cost'] = fuel_cost_q.scalar() or 0
            stats['total_maint_cost'] = maint_cost_q.scalar() or 0
        stats['cost_label'] = "すべての公道車"
        
    return stats