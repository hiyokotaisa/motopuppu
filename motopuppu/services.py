# motopuppu/services.py
from flask import current_app, url_for
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from sqlalchemy import func, union_all
from sqlalchemy.orm import joinedload
import jpholiday
import json
import math
from zoneinfo import ZoneInfo
# ▼▼▼ cryptographyのインポートを追記 ▼▼▼
from cryptography.fernet import Fernet
# ▲▲▲ 追記ここまで ▲▲▲

# ▼▼▼ モデルのインポートを追加 ▼▼▼
from .models import db, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder, ActivityLog, GeneralNote, UserAchievement, AchievementDefinition
# ▲▲▲ ここまで追加 ▲▲▲


# --- データ取得・計算ヘルパー ---

def get_latest_total_distance(motorcycle_id, offset_val):
    """指定された車両の最新の総走行距離を取得する"""
    latest_fuel_dist = db.session.query(db.func.max(FuelEntry.total_distance)).filter(
        FuelEntry.motorcycle_id == motorcycle_id).scalar() or 0
    latest_maint_dist = db.session.query(db.func.max(MaintenanceEntry.total_distance_at_maintenance)).filter(
        MaintenanceEntry.motorcycle_id == motorcycle_id).scalar() or 0
    return max(latest_fuel_dist, latest_maint_dist, offset_val if offset_val is not None else 0)


# ▼▼▼【ここから変更】関数が期間を受け取れるようにし、クエリを修正 ▼▼▼
def calculate_average_kpl(motorcycle: Motorcycle, start_date=None, end_date=None):
    """車両の平均燃費を計算する。期間が指定されていれば、その期間で計算する。"""
    if motorcycle.is_racer:
        return None

    all_full_tank_entries = []
    
    # 期間指定がある場合のロジック
    if start_date and end_date:
        # 計算の起点とするため、期間の開始日より前の最後の満タン記録を取得
        first_entry = FuelEntry.query.filter(
            FuelEntry.motorcycle_id == motorcycle.id,
            FuelEntry.is_full_tank == True,
            FuelEntry.entry_date < start_date
        ).order_by(FuelEntry.entry_date.desc()).first()
        
        # 期間内の満タン記録をすべて取得
        period_entries = FuelEntry.query.filter(
            FuelEntry.motorcycle_id == motorcycle.id,
            FuelEntry.is_full_tank == True,
            FuelEntry.entry_date.between(start_date, end_date)
        ).order_by(FuelEntry.entry_date.asc()).all()
        
        if first_entry:
            all_full_tank_entries.append(first_entry)
        all_full_tank_entries.extend(period_entries)
    
    # 期間指定がない場合は、これまで通り全期間を対象とする
    else:
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

        # 期間指定がある場合、計算区間の終了日が期間内でなければスキップ
        if end_date and end_entry.entry_date > end_date:
            continue
            
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
# ▲▲▲【変更はここまで】▲▲▲

# --- ダッシュボード用サービス関数 ---

# (get_timeline_events, get_upcoming_reminders, get_recent_logs は変更なし)
def get_timeline_events(motorcycle_ids, start_date=None, end_date=None):
    """指定された車両IDリストの給油・整備記録を時系列で取得する"""
    if not motorcycle_ids:
        return []

    timeline_events = []
    is_multiple_vehicles = len(motorcycle_ids) > 1

    # 1. 給油記録を取得
    fuel_query = FuelEntry.query.options(db.joinedload(FuelEntry.motorcycle)).filter(FuelEntry.motorcycle_id.in_(motorcycle_ids))
    if start_date and end_date:
        fuel_query = fuel_query.filter(FuelEntry.entry_date.between(start_date, end_date))
    
    for entry in fuel_query.all():
        title = f"給油 ({entry.fuel_volume:.2f}L)"
        if is_multiple_vehicles:
            title = f"[{entry.motorcycle.name}] {title}"

        timeline_events.append({
            'type': 'fuel',
            'date': entry.entry_date,
            'id': entry.id,
            'odo': entry.odometer_reading,
            'total_dist': entry.total_distance,
            'title': title,
            'description': f"燃費: {entry.km_per_liter if entry.km_per_liter is not None else '---'} km/L",
            'cost': entry.total_cost,
            'details': {
                '車両名': entry.motorcycle.name,
                '給油量': f"{entry.fuel_volume:.2f} L",
                '単価': f"{entry.price_per_liter} 円/L" if entry.price_per_liter else '---',
                '合計金額': f"{entry.total_cost:,.0f} 円" if entry.total_cost is not None else '---',
                'スタンド': entry.station_name or '未記録',
                'メモ': entry.notes or 'なし'
            },
            'edit_url': url_for('fuel.edit_fuel', entry_id=entry.id)
        })

    # 2. 整備記録を取得
    maint_query = MaintenanceEntry.query.options(db.joinedload(MaintenanceEntry.motorcycle)).filter(MaintenanceEntry.motorcycle_id.in_(motorcycle_ids)).filter(MaintenanceEntry.category != '初期設定')
    if start_date and end_date:
        maint_query = maint_query.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

    for entry in maint_query.all():
        title = entry.category or entry.description
        if is_multiple_vehicles:
            title = f"[{entry.motorcycle.name}] {title}"

        timeline_events.append({
            'type': 'maintenance',
            'date': entry.maintenance_date,
            'id': entry.id,
            'odo': entry.odometer_reading_at_maintenance,
            'total_dist': entry.total_distance_at_maintenance,
            'title': title,
            'description': entry.description,
            'cost': entry.total_cost,
            'details': {
                '車両名': entry.motorcycle.name,
                'カテゴリ': entry.category or '未分類',
                '内容': entry.description,
                '部品代': f"{entry.parts_cost:,.0f} 円" if entry.parts_cost is not None else '---',
                '工賃': f"{entry.labor_cost:,.0f} 円" if entry.labor_cost is not None else '---',
                '合計費用': f"{entry.total_cost:,.0f} 円" if entry.total_cost is not None else '---',
                '場所': entry.location or '未記録',
                'メモ': entry.notes or 'なし'
            },
            'edit_url': url_for('maintenance.edit_maintenance', entry_id=entry.id)
        })

    # 3. 日付(降順)、次にID(降順)でソート
    # ▼▼▼▼▼ ここからが修正箇所です ▼▼▼▼▼
    timeline_events.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    # ▲▲▲▲▲ ここまでが修正箇所です ▲▲▲▲▲

    return timeline_events


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

    all_reminders = MaintenanceReminder.query.options(
        db.joinedload(MaintenanceReminder.motorcycle),
        db.joinedload(MaintenanceReminder.last_maintenance_entry) # N+1問題対策で追加
    ).join(Motorcycle).filter(Motorcycle.user_id == user_id).all()


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
            last_done_odo_val = None
            
            # 表示するODO値を決定（連携記録を優先）
            if reminder.last_maintenance_entry:
                last_done_odo_val = reminder.last_maintenance_entry.odometer_reading_at_maintenance
            elif reminder.last_done_odo is not None:
                last_done_odo_val = reminder.last_done_odo

            # 表示用の文字列を生成
            if reminder.last_done_date:
                last_done_str = reminder.last_done_date.strftime('%Y-%m-%d')
                if not motorcycle.is_racer and last_done_odo_val is not None:
                    last_done_str += f" ({last_done_odo_val:,} km)"
            elif not motorcycle.is_racer and last_done_odo_val is not None:
                last_done_str = f"{last_done_odo_val:,} km"

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


# ▼▼▼【ここから変更】get_dashboard_stats内の燃費計算を期間指定で行うように修正 ▼▼▼
def get_dashboard_stats(user_motorcycles_all, user_motorcycle_ids_public, target_vehicle_for_stats=None, start_date=None, end_date=None, show_cost=True):
    """ダッシュボードの統計カード情報を計算して返す"""
    stats = {
        'primary_metric_val': 0, 'primary_metric_unit': '', 'primary_metric_label': '-',
        'is_racer_stats': False, 'average_kpl_val': None, 'average_kpl_label': '-',
        'show_cost': show_cost, # 表示モードを格納
    }
    # 表示モードに応じて初期化するキーを変更
    if show_cost:
        stats.update({'total_fuel_cost': 0, 'total_maint_cost': 0, 'cost_label': '-'})
    else:
        stats.update({'total_fuel_volume': 0, 'total_maint_count': 0, 'non_cost_label': '-'})

    if target_vehicle_for_stats:
        stats['is_racer_stats'] = target_vehicle_for_stats.is_racer
        if target_vehicle_for_stats.is_racer:
            stats['primary_metric_val'] = target_vehicle_for_stats.total_operating_hours if target_vehicle_for_stats.total_operating_hours is not None else 0
            stats['primary_metric_unit'] = '時間'
            stats['primary_metric_label'] = target_vehicle_for_stats.name
            stats['average_kpl_label'] = f"{target_vehicle_for_stats.name} (レーサー)"
            # ラベルを更新
            if show_cost:
                stats['cost_label'] = target_vehicle_for_stats.name
            else:
                stats['non_cost_label'] = target_vehicle_for_stats.name
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
            
            # _average_kpl を使うのではなく、期間を指定して再計算する
            stats['average_kpl_val'] = calculate_average_kpl(target_vehicle_for_stats, start_date, end_date)
            stats['average_kpl_label'] = target_vehicle_for_stats.name

            # コスト表示/非表示に応じてクエリを分岐
            if show_cost:
                fuel_cost_q = db.session.query(func.sum(FuelEntry.total_cost)).filter(FuelEntry.motorcycle_id == vehicle_id)
                maint_cost_q = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))).filter(MaintenanceEntry.motorcycle_id == vehicle_id)
                if start_date:
                    fuel_cost_q = fuel_cost_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                    maint_cost_q = maint_cost_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

                stats['total_fuel_cost'] = fuel_cost_q.scalar() or 0
                stats['total_maint_cost'] = maint_cost_q.scalar() or 0
                stats['cost_label'] = target_vehicle_for_stats.name
            else:
                fuel_volume_q = db.session.query(func.sum(FuelEntry.fuel_volume)).filter(FuelEntry.motorcycle_id == vehicle_id)
                maint_count_q = db.session.query(func.count(MaintenanceEntry.id)).filter(MaintenanceEntry.motorcycle_id == vehicle_id)
                if start_date:
                    fuel_volume_q = fuel_volume_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                    maint_count_q = maint_count_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

                stats['total_fuel_volume'] = fuel_volume_q.scalar() or 0
                stats['total_maint_count'] = maint_count_q.scalar() or 0
                stats['non_cost_label'] = target_vehicle_for_stats.name
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
            # _average_kpl を使うのではなく、期間を指定して再計算する
            stats['average_kpl_val'] = calculate_average_kpl(default_vehicle, start_date, end_date)
            stats['average_kpl_label'] = f"デフォルト ({default_vehicle.name})"
        else:
            stats['average_kpl_label'] = "計算対象外"

        # 費用または代替情報
        if user_motorcycle_ids_public:
            if show_cost:
                fuel_cost_q = db.session.query(func.sum(FuelEntry.total_cost)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public))
                maint_cost_q = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public))
                if start_date:
                    fuel_cost_q = fuel_cost_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                    maint_cost_q = maint_cost_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

                stats['total_fuel_cost'] = fuel_cost_q.scalar() or 0
                stats['total_maint_cost'] = maint_cost_q.scalar() or 0
                stats['cost_label'] = "すべての公道車"
            else:
                fuel_volume_q = db.session.query(func.sum(FuelEntry.fuel_volume)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public))
                maint_count_q = db.session.query(func.count(MaintenanceEntry.id)).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public))
                if start_date:
                    fuel_volume_q = fuel_volume_q.filter(FuelEntry.entry_date.between(start_date, end_date))
                    maint_count_q = maint_count_q.filter(MaintenanceEntry.maintenance_date.between(start_date, end_date))

                stats['total_fuel_volume'] = fuel_volume_q.scalar() or 0
                stats['total_maint_count'] = maint_count_q.scalar() or 0
                stats['non_cost_label'] = "すべての公道車"
        
    return stats
# ▲▲▲【変更はここまで】▲▲▲


def get_holidays_json():
    """祝日情報を取得し、JSON文字列として返す"""
    try:
        today_for_holiday = date.today()
        # カレンダー表示のパフォーマンスのため、前後1年分の祝日を取得
        years_to_fetch = [today_for_holiday.year - 1, today_for_holiday.year, today_for_holiday.year + 1]
        holidays_dict = {}
        for year in years_to_fetch:
            try:
                holidays_raw = jpholiday.year_holidays(year)
                for holiday_date_obj, holiday_name in holidays_raw:
                    holidays_dict[holiday_date_obj.strftime('%Y-%m-%d')] = holiday_name
            except Exception as e:
                current_app.logger.error(f"Error fetching holidays for year {year}: {e}")
        return json.dumps(holidays_dict)
    except Exception as e:
        current_app.logger.error(f"Error processing holidays data: {e}")
        return '{}' # エラーが発生した場合は空のJSONを返す

def get_calendar_events_for_user(user):
    """指定されたユーザーのカレンダーイベントをすべて取得・整形して返す"""
    events = []
    user_id = user.id
    
    # 全車両IDを取得
    user_motorcycles_all = Motorcycle.query.filter_by(user_id=user_id).all()
    user_motorcycle_ids_all = [m.id for m in user_motorcycles_all]
    
    # 公道車のみのIDリスト
    user_motorcycle_ids_public = [m.id for m in user_motorcycles_all if not m.is_racer]

    # 給油記録 (公道車のみ)
    if user_motorcycle_ids_public:
        fuel_entries = FuelEntry.query.options(db.joinedload(FuelEntry.motorcycle)).filter(
            FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public)).all()
        for entry in fuel_entries:
            kpl = entry.km_per_liter
            kpl_display = f"{kpl:.2f} km/L" if kpl is not None else None
            edit_url = url_for('fuel.edit_fuel', entry_id=entry.id)
            events.append({
                'id': f'fuel-{entry.id}', 'title': f"⛽ 給油: {entry.motorcycle.name}",
                'start': entry.entry_date.isoformat(), 'allDay': True, 'url': edit_url,
                'backgroundColor': '#198754', 'borderColor': '#198754', 'textColor': 'white',
                'extendedProps': {
                    'type': 'fuel', 'motorcycleName': entry.motorcycle.name,
                    'odometer': entry.odometer_reading, 'fuelVolume': entry.fuel_volume, 'kmPerLiter': kpl_display,
                    'totalCost': math.ceil(entry.total_cost) if entry.total_cost is not None else None,
                    'stationName': entry.station_name, 'notes': entry.notes, 'editUrl': edit_url
                }
            })

    # 整備記録 (公道車のみ)
    if user_motorcycle_ids_public:
        maintenance_entries = MaintenanceEntry.query.options(db.joinedload(MaintenanceEntry.motorcycle)).filter(
            MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public),
            MaintenanceEntry.category != '初期設定'
        ).all()
        for entry in maintenance_entries:
            event_title_base = entry.category if entry.category else entry.description
            event_title = f"🔧 整備: {event_title_base[:15]}" + ("..." if len(event_title_base) > 15 else "")
            total_cost = entry.total_cost
            edit_url = url_for('maintenance.edit_maintenance', entry_id=entry.id)
            events.append({
                'id': f'maint-{entry.id}', 'title': event_title,
                'start': entry.maintenance_date.isoformat(), 'allDay': True, 'url': edit_url,
                'backgroundColor': '#ffc107', 'borderColor': '#ffc107', 'textColor': 'black',
                'extendedProps': {
                    'type': 'maintenance', 'motorcycleName': entry.motorcycle.name,
                    'odometer': entry.total_distance_at_maintenance, 'description': entry.description, 'category': entry.category,
                    'totalCost': math.ceil(total_cost) if total_cost is not None else None,
                    'location': entry.location, 'notes': entry.notes, 'editUrl': edit_url
                }
            })

    # 活動ログ (全車両対象)
    if user_motorcycle_ids_all:
        activity_logs = ActivityLog.query.options(db.joinedload(ActivityLog.motorcycle)).filter(
            ActivityLog.motorcycle_id.in_(user_motorcycle_ids_all)).all()
        for entry in activity_logs:
            location_display = entry.activity_title or entry.location_name or '活動'
            event_title = f"🏁 {location_display[:15]}" + ("..." if len(location_display) > 15 else "")
            edit_url = url_for('activity.detail_activity', activity_id=entry.id)
            
            location_details = []
            if entry.circuit_name:
                location_details.append(entry.circuit_name)
            if entry.custom_location:
                location_details.append(entry.custom_location)
            location_full_display = ", ".join(location_details) or entry.location_name or '未設定'

            events.append({
                'id': f'activity-{entry.id}', 'title': event_title,
                'start': entry.activity_date.isoformat(), 'allDay': True, 'url': edit_url,
                'backgroundColor': '#0dcaf0', 'borderColor': '#0dcaf0', 'textColor': 'black',
                'extendedProps': {
                    'type': 'activity',
                    'motorcycleName': entry.motorcycle.name,
                    'isRacer': entry.motorcycle.is_racer,
                    'activityTitle': entry.activity_title or '活動ログ',
                    'location': location_full_display,
                    'weather': entry.weather,
                    'temperature': f"{entry.temperature}°C" if entry.temperature is not None else None,
                    'notes': entry.notes,
                    'editUrl': edit_url
                }
            })

    # 一般ノート・タスク (全車両対象)
    general_notes = GeneralNote.query.options(
        db.joinedload(GeneralNote.motorcycle)).filter_by(user_id=user_id).all()
    for note in general_notes:
        motorcycle_name = note.motorcycle.name if note.motorcycle else None
        note_title_display = note.title or ('タスク' if note.category == 'task' else 'メモ')
        icon = "✅" if note.category == 'task' else "📝"
        title_prefix = f"{icon} {'タスク' if note.category == 'task' else 'メモ'}: "
        event_type = note.category
        event_title = title_prefix + note_title_display[:15] + ("..." if len(note_title_display) > 15 else "")
        edit_url = url_for('notes.edit_note', note_id=note.id)
        extended_props = {
            'type': event_type, 'category': note.category, 'title': note.title, 'motorcycleName': motorcycle_name,
            'noteDate': note.note_date.strftime('%Y-%m-%d'),
            'createdAt': note.created_at.strftime('%Y-%m-%d %H:%M'),
            'updatedAt': note.updated_at.strftime('%Y-%m-%d %H:%M'), 'editUrl': edit_url,
            'isRacer': note.motorcycle.is_racer if note.motorcycle else False
        }
        if event_type == 'task':
            extended_props['todos'] = note.todos if note.todos is not None else []
        else:
            extended_props['content'] = note.content
        events.append({
            'id': f'note-{note.id}', 'title': event_title,
            'start': note.note_date.isoformat(), 'allDay': True, 'url': edit_url,
            'backgroundColor': '#6c757d', 'borderColor': '#6c757d', 'textColor': 'white',
            'extendedProps': extended_props
        })

    return events

# --- 暗号化サービス ---

class CryptoService:
    """
    データ暗号化・復号を行うサービスクラス。
    Fernet (AES128-CBC) を使用します。
    """
    def __init__(self):
        """
        コンストラクタ。
        環境変数から暗号化キーを読み込み、Fernetインスタンスを初期化します。
        """
        key_str = current_app.config.get('SECRET_CRYPTO_KEY')
        if not key_str:
            raise ValueError("SECRET_CRYPTO_KEY is not set in the application configuration.")
        
        # ▼▼▼ キーをバイト列に変換する処理を修正 ▼▼▼
        # Fernetキーはbase64でエンコードされているため、そのままバイト列として扱う
        key_bytes = key_str.encode()
        # ▲▲▲ 修正ここまで ▲▲▲
            
        self.fernet = Fernet(key_bytes)

    def encrypt(self, data: str) -> str | None:
        """
        与えられた文字列を暗号化します。

        Args:
            data: 暗号化する文字列。

        Returns:
            暗号化された文字列。データが空の場合はNone。
        """
        if not data:
            return None
        return self.fernet.encrypt(data.encode()).decode()

    def decrypt(self, encrypted_data: str) -> str | None:
        """
        与えられた暗号化文字列を復号します。

        Args:
            encrypted_data: 復号する文字列。

        Returns:
            復号された文字列。データが空の場合はNone。
            復号に失敗した場合は例外が発生します。
        """
        if not encrypted_data:
            return None
        return self.fernet.decrypt(encrypted_data.encode()).decode()

def get_user_garage_data(user) -> dict:
    """ユーザーの公開ガレージ表示に必要なデータをまとめて取得する"""
    if not user:
        return None

    # ガレージに掲載する設定の車両を取得
    vehicles_in_garage = Motorcycle.query.filter(
        Motorcycle.user_id == user.id,
        Motorcycle.show_in_garage == True
    ).order_by(Motorcycle.is_default.desc(), Motorcycle.id.asc()).all()

    # ▼▼▼【ここから変更】ヒーロー車両の決定ロジック ▼▼▼
    hero_vehicle = None
    # 1. ユーザーがヒーロー車両を明示的に指定している場合
    if user.garage_hero_vehicle_id:
        hero_vehicle = next((v for v in vehicles_in_garage if v.id == user.garage_hero_vehicle_id), None)
    
    # 2. 明示的な指定がない場合、従来のデフォルト車両をヒーローにする
    if not hero_vehicle:
        hero_vehicle = next((v for v in vehicles_in_garage if v.is_default), None)

    # 3. それでも決まらない場合、リストの最初の車両をヒーローにする
    if not hero_vehicle and vehicles_in_garage:
        hero_vehicle = vehicles_in_garage[0]
    # ▲▲▲【変更はここまで】▲▲▲
    
    other_vehicles = [v for v in vehicles_in_garage if v != hero_vehicle]
    
    # ヒーロー車両の統計情報
    hero_stats = {}
    if hero_vehicle:
        if hero_vehicle.is_racer:
            hero_stats['primary_metric_label'] = '総稼働時間'
            hero_stats['primary_metric_value'] = f"{hero_vehicle.total_operating_hours or 0:.2f}"
            hero_stats['primary_metric_unit'] = '時間'
        else:
            total_mileage = get_latest_total_distance(hero_vehicle.id, hero_vehicle.odometer_offset)
            avg_kpl = calculate_average_kpl(hero_vehicle)
            hero_stats['primary_metric_label'] = '総走行距離'
            hero_stats['primary_metric_value'] = f"{total_mileage:,}"
            hero_stats['primary_metric_unit'] = 'km'
            hero_stats['avg_kpl'] = f"{avg_kpl:.2f} km/L" if avg_kpl else "---"

        # ▼▼▼【ここから追記】追加の統計情報を計算 ▼▼▼
        # 総メンテナンス費用
        total_maint_cost = db.session.query(
            func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))
        ).filter(
            MaintenanceEntry.motorcycle_id == hero_vehicle.id
        ).scalar() or 0
        hero_stats['total_maint_cost'] = f"{total_maint_cost:,.0f} 円"

        # 活動ログ回数
        total_activities = db.session.query(
            func.count(ActivityLog.id)
        ).filter(
            ActivityLog.motorcycle_id == hero_vehicle.id
        ).scalar() or 0
        hero_stats['total_activities'] = f"{total_activities} 回"
        # ▲▲▲【追記はここまで】▲▲▲

    # ユーザーの実績
    unlocked_achievements = db.session.query(
        AchievementDefinition.name,
        AchievementDefinition.icon_class
    ).join(
        UserAchievement, UserAchievement.achievement_code == AchievementDefinition.code
    ).filter(
        UserAchievement.user_id == user.id
    ).order_by(
        UserAchievement.unlocked_at.desc()
    ).limit(5).all()

    return {
        'owner': user,
        'hero_vehicle': hero_vehicle,
        'other_vehicles': other_vehicles,
        'hero_stats': hero_stats,
        'achievements': unlocked_achievements,
    }