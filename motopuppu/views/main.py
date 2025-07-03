# motopuppu/views/main.py
from flask import (
    Blueprint, render_template, redirect, url_for, session, g, flash, current_app, jsonify, request
)
from datetime import date, timedelta, datetime # datetime をインポートリストに追加
from dateutil.relativedelta import relativedelta
from .auth import login_required_custom, get_current_user # get_current_user はここでインポート
from ..models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder, GeneralNote
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload # ⭐️ joinedload から selectinload に変更
import math
import jpholiday # 祝日ライブラリ
import json      # JSONライブラリ
import os        # os をインポート (お知らせファイルパス用)

main_bp = Blueprint('main', __name__)

# --- ヘルパー関数 ---
def get_latest_total_distance(motorcycle_id, offset_val):
    latest_fuel_dist = db.session.query(db.func.max(FuelEntry.total_distance)).filter(FuelEntry.motorcycle_id == motorcycle_id).scalar() or 0
    latest_maint_dist = db.session.query(db.func.max(MaintenanceEntry.total_distance_at_maintenance)).filter(MaintenanceEntry.motorcycle_id == motorcycle_id).scalar() or 0
    return max(latest_fuel_dist, latest_maint_dist, offset_val if offset_val is not None else 0)

def calculate_average_kpl(motorcycle: Motorcycle):
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

def get_upcoming_reminders(user_motorcycles_all, user_id):
    upcoming_reminders = []
    today = date.today()
    KM_THRESHOLD_WARNING = current_app.config.get('REMINDER_KM_WARNING', 500); DAYS_THRESHOLD_WARNING = current_app.config.get('REMINDER_DAYS_WARNING', 14)
    KM_THRESHOLD_DANGER = current_app.config.get('REMINDER_KM_DANGER', 0); DAYS_THRESHOLD_DANGER = current_app.config.get('REMINDER_DAYS_DANGER', 0)
    current_public_distances = {}
    for m in user_motorcycles_all:
        if not m.is_racer:
            current_public_distances[m.id] = get_latest_total_distance(m.id, m.odometer_offset)
    all_reminders = MaintenanceReminder.query.options(db.joinedload(MaintenanceReminder.motorcycle)).join(Motorcycle).filter(Motorcycle.user_id == user_id).all()
    for reminder in all_reminders:
        motorcycle = reminder.motorcycle
        status = 'ok'; messages = []; due_info_parts = []; is_due = False
        if not motorcycle.is_racer and reminder.interval_km and reminder.last_done_km is not None:
            current_km = current_public_distances.get(motorcycle.id, 0)
            next_km_due = reminder.last_done_km + reminder.interval_km
            remaining_km = next_km_due - current_km
            due_info_parts.append(f"{next_km_due:,} km")
            if remaining_km <= KM_THRESHOLD_DANGER: messages.append(f"距離超過 (現在 {current_km:,} km)"); status = 'danger'; is_due = True
            elif remaining_km <= KM_THRESHOLD_WARNING: messages.append(f"あと {remaining_km:,} km"); status = 'warning'; is_due = True
        if reminder.interval_months and reminder.last_done_date:
            try:
                next_date_due = reminder.last_done_date + relativedelta(months=reminder.interval_months); remaining_days = (next_date_due - today).days
                due_info_parts.append(f"{next_date_due.strftime('%Y-%m-%d')}")
                period_status = 'ok'; period_message = ''
                if remaining_days <= DAYS_THRESHOLD_DANGER: period_status = 'danger'; period_message = f"期限超過"
                elif remaining_days <= DAYS_THRESHOLD_WARNING: period_status = 'warning'; period_message = f"あと {remaining_days} 日"
                if period_status != 'ok':
                    is_due = True; messages.append(period_message)
                    if (period_status == 'danger') or (period_status == 'warning' and status != 'danger'): status = period_status
            except Exception as e: current_app.logger.error(f"Error calculating date reminder {reminder.id}: {e}"); messages.append("日付計算エラー"); status = 'warning'; is_due = True
        if is_due:
            last_done_str = "未実施"
            if reminder.last_done_date: last_done_str = reminder.last_done_date.strftime('%Y-%m-%d');
            if not motorcycle.is_racer and reminder.last_done_km is not None:
                last_done_str += f" ({reminder.last_done_km:,} km)" if reminder.last_done_date else f"{reminder.last_done_km:,} km"
            upcoming_reminders.append({
                'reminder_id': reminder.id, 'motorcycle_id': motorcycle.id, 'motorcycle_name': motorcycle.name,
                'task': reminder.task_description, 'status': status, 'message': ", ".join(messages) if messages else "要確認",
                'due_info': " / ".join(due_info_parts) if due_info_parts else '未設定', 'last_done': last_done_str,
                'is_racer': motorcycle.is_racer
            })
    upcoming_reminders.sort(key=lambda x: (x['status'] != 'danger', x['status'] != 'warning'))
    return upcoming_reminders

# --- ルート定義 ---

@main_bp.route('/')
def index():
    if hasattr(g, 'user') and g.user:
        return redirect(url_for('main.dashboard'))

    announcements_for_modal = []
    important_notice_content = None
    try:
        announcement_file = os.path.join(current_app.root_path, '..', 'announcements.json')
        if os.path.exists(announcement_file):
            with open(announcement_file, 'r', encoding='utf-8') as f:
                all_announcements_data = json.load(f)
                temp_modal_announcements = []
                for item in all_announcements_data:
                    if item.get('active', False):
                        if item.get('id') == 1:
                            important_notice_content = item
                        else:
                            temp_modal_announcements.append(item)
                temp_modal_announcements.sort(key=lambda x: x.get('id', 0), reverse=True)
                announcements_for_modal = temp_modal_announcements
        else:
            current_app.logger.warning(f"announcements.json not found at {announcement_file}")
    except Exception as e:
        current_app.logger.error(f"An unexpected error occurred loading announcements: {e}", exc_info=True)

    return render_template('index.html',
                           announcements=announcements_for_modal,
                           important_notice=important_notice_content)

@main_bp.route('/dashboard')
@login_required_custom
def dashboard():
    user_motorcycles_all = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles_all:
        flash('ようこそ！最初に利用する車両を登録してください。', 'info'); return redirect(url_for('vehicle.add_vehicle'))
    
    user_motorcycle_ids_all = [m.id for m in user_motorcycles_all]
    user_motorcycles_public = [m for m in user_motorcycles_all if not m.is_racer]
    user_motorcycle_ids_public = [m.id for m in user_motorcycles_public]

    selected_fuel_vehicle_id_str = request.args.get('fuel_vehicle_id')
    selected_maint_vehicle_id_str = request.args.get('maint_vehicle_id')
    selected_stats_vehicle_id_str = request.args.get('stats_vehicle_id')

    selected_fuel_vehicle_id = None
    if selected_fuel_vehicle_id_str:
        try:
            temp_id = int(selected_fuel_vehicle_id_str)
            if temp_id in user_motorcycle_ids_public: selected_fuel_vehicle_id = temp_id
        except ValueError: pass

    selected_maint_vehicle_id = None
    if selected_maint_vehicle_id_str:
        try:
            temp_id = int(selected_maint_vehicle_id_str)
            if temp_id in user_motorcycle_ids_public: selected_maint_vehicle_id = temp_id
        except ValueError: pass

    selected_stats_vehicle_id = None
    target_vehicle_for_stats = None
    if selected_stats_vehicle_id_str:
        try:
            temp_id = int(selected_stats_vehicle_id_str)
            if temp_id in user_motorcycle_ids_all:
                selected_stats_vehicle_id = temp_id
                target_vehicle_for_stats = next((m for m in user_motorcycles_all if m.id == selected_stats_vehicle_id), None)
        except ValueError: pass

    fuel_query = FuelEntry.query.options(db.joinedload(FuelEntry.motorcycle)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public))
    if selected_fuel_vehicle_id:
        fuel_query = fuel_query.filter(FuelEntry.motorcycle_id == selected_fuel_vehicle_id)
    recent_fuel_entries = fuel_query.order_by(FuelEntry.entry_date.desc(), FuelEntry.total_distance.desc()).limit(5).all()

    maint_query = MaintenanceEntry.query.options(db.joinedload(MaintenanceEntry.motorcycle)).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public))
    if selected_maint_vehicle_id:
        maint_query = maint_query.filter(MaintenanceEntry.motorcycle_id == selected_maint_vehicle_id)
    recent_maintenance_entries = maint_query.order_by(MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.total_distance_at_maintenance.desc()).limit(5).all()

    upcoming_reminders = get_upcoming_reminders(user_motorcycles_all, g.user.id)

    for m in user_motorcycles_all:
        m._average_kpl = calculate_average_kpl(m)

    dashboard_stats = {
        'primary_metric_val': 0, 'primary_metric_unit': '', 'primary_metric_label': '-', 'is_racer_stats': False,
        'average_kpl_val': None, 'average_kpl_label': '-',
        'total_fuel_cost': 0, 'total_maint_cost': 0, 'cost_label': '-',
    }

    if target_vehicle_for_stats:
        dashboard_stats['is_racer_stats'] = target_vehicle_for_stats.is_racer
        if target_vehicle_for_stats.is_racer:
            dashboard_stats['primary_metric_val'] = target_vehicle_for_stats.total_operating_hours if target_vehicle_for_stats.total_operating_hours is not None else 0
            dashboard_stats['primary_metric_unit'] = '時間'
            dashboard_stats['primary_metric_label'] = target_vehicle_for_stats.name
            dashboard_stats['average_kpl_val'] = None
            dashboard_stats['average_kpl_label'] = f"{target_vehicle_for_stats.name} (レーサー)"
        else:
            dashboard_stats['primary_metric_val'] = get_latest_total_distance(target_vehicle_for_stats.id, target_vehicle_for_stats.odometer_offset)
            dashboard_stats['primary_metric_unit'] = 'km'
            dashboard_stats['primary_metric_label'] = target_vehicle_for_stats.name
            dashboard_stats['average_kpl_val'] = target_vehicle_for_stats._average_kpl
            dashboard_stats['average_kpl_label'] = target_vehicle_for_stats.name

        fuel_cost_q = db.session.query(func.sum(FuelEntry.total_cost)).filter(FuelEntry.motorcycle_id == target_vehicle_for_stats.id).scalar()
        dashboard_stats['total_fuel_cost'] = fuel_cost_q or 0
        maint_cost_q = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))).filter(MaintenanceEntry.motorcycle_id == target_vehicle_for_stats.id).scalar()
        dashboard_stats['total_maint_cost'] = maint_cost_q or 0
        dashboard_stats['cost_label'] = target_vehicle_for_stats.name

    else:
        # 1. ユーザーの公道車両に関連記録をEager Loadingして取得
        user_street_vehicles_with_entries = Motorcycle.query.filter(
            Motorcycle.id.in_(user_motorcycle_ids_public)
        ).options(
            selectinload(Motorcycle.fuel_entries),
            selectinload(Motorcycle.maintenance_entries)
        ).all()
        
        total_running_distance = 0
        # 2. 車両ごとに走行距離を計算して合算
        for vehicle in user_street_vehicles_with_entries:
            all_distances = []
            
            # 給油記録から実走行距離リストを作成
            fuel_distances = [
                entry.total_distance for entry in vehicle.fuel_entries
                if entry.total_distance is not None
            ]
            # 整備記録から実走行距離リストを作成
            maintenance_distances = [
                entry.total_distance_at_maintenance for entry in vehicle.maintenance_entries
                if entry.total_distance_at_maintenance is not None
            ]
            
            all_distances.extend(fuel_distances)
            all_distances.extend(maintenance_distances)
            
            # 3. 記録が2つ以上ある場合のみ、(最大 - 最小)を計算
            if len(all_distances) > 1:
                vehicle_distance = max(all_distances) - min(all_distances)
                total_running_distance += vehicle_distance

        # 4. 計算結果を dashboard_stats に設定
        dashboard_stats['primary_metric_val'] = total_running_distance

        dashboard_stats['primary_metric_unit'] = 'km'
        dashboard_stats['primary_metric_label'] = "すべての公道車"
        dashboard_stats['is_racer_stats'] = False

        default_vehicle = next((m for m in user_motorcycles_all if m.is_default), user_motorcycles_all[0] if user_motorcycles_all else None)
        if default_vehicle and not default_vehicle.is_racer:
            dashboard_stats['average_kpl_val'] = default_vehicle._average_kpl
            dashboard_stats['average_kpl_label'] = f"デフォルト ({default_vehicle.name})"
        else:
            dashboard_stats['average_kpl_val'] = None
            dashboard_stats['average_kpl_label'] = "計算対象外"

        total_fuel_cost_query = db.session.query(func.sum(FuelEntry.total_cost)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public)).scalar()
        dashboard_stats['total_fuel_cost'] = total_fuel_cost_query or 0
        total_maint_cost_query = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public)).scalar()
        dashboard_stats['total_maint_cost'] = total_maint_cost_query or 0
        dashboard_stats['cost_label'] = "すべての公道車"

    holidays_json = '{}'
    try:
        today_for_holiday = date.today()
        years_to_fetch = [today_for_holiday.year - 1, today_for_holiday.year, today_for_holiday.year + 1]
        holidays_dict = {}
        for year in years_to_fetch:
            try:
                holidays_raw = jpholiday.year_holidays(year)
                for holiday_date_obj, holiday_name in holidays_raw:
                    holidays_dict[holiday_date_obj.strftime('%Y-%m-%d')] = holiday_name
            except Exception as e:
                current_app.logger.error(f"Error fetching holidays for year {year}: {e}")
        holidays_json = json.dumps(holidays_dict)
    except Exception as e:
        current_app.logger.error(f"Error processing holidays data: {e}")
        flash('祝日情報の取得または処理中にエラーが発生しました。', 'warning')

    return render_template(
        'dashboard.html',
        motorcycles=user_motorcycles_all,
        motorcycles_public=user_motorcycles_public,
        recent_fuel_entries=recent_fuel_entries,
        recent_maintenance_entries=recent_maintenance_entries,
        upcoming_reminders=upcoming_reminders,
        selected_fuel_vehicle_id=selected_fuel_vehicle_id,
        selected_maint_vehicle_id=selected_maint_vehicle_id,
        selected_stats_vehicle_id=selected_stats_vehicle_id,
        dashboard_stats=dashboard_stats,
        holidays_json=holidays_json
    )

@main_bp.route('/api/dashboard/events')
@login_required_custom
def dashboard_events_api():
    events = []
    if not g.user: return jsonify({'error': 'User not logged in'}), 401
    user_id = g.user.id
    user_motorcycle_ids_public = [m.id for m in Motorcycle.query.filter_by(user_id=user_id, is_racer=False).all()]
    if user_motorcycle_ids_public:
        fuel_entries = FuelEntry.query.options(db.joinedload(FuelEntry.motorcycle)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public)).all()
        for entry in fuel_entries:
            kpl = entry.km_per_liter
            kpl_display = f"{kpl:.2f} km/L" if kpl is not None else None
            edit_url = url_for('fuel.edit_fuel', entry_id=entry.id)
            events.append({
                'id': f'fuel-{entry.id}', 'title': f"⛽ 給油: {entry.motorcycle.name}",
                'start': entry.entry_date.isoformat(), 'allDay': True, 'url': edit_url,
                'backgroundColor': '#198754', 'borderColor': '#198754', 'textColor': 'white',
                'extendedProps': {
                    'type': 'fuel', 'motorcycleName': entry.motorcycle.name, 'odometer': entry.odometer_reading,
                    'fuelVolume': entry.fuel_volume, 'kmPerLiter': kpl_display,
                    'totalCost': math.ceil(entry.total_cost) if entry.total_cost is not None else None,
                    'stationName': entry.station_name, 'notes': entry.notes, 'editUrl': edit_url
                }
            })
    if user_motorcycle_ids_public:
        maintenance_entries = MaintenanceEntry.query.options(db.joinedload(MaintenanceEntry.motorcycle)).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public)).all()
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
                    'type': 'maintenance', 'motorcycleName': entry.motorcycle.name, 'odometer': entry.total_distance_at_maintenance,
                    'description': entry.description, 'category': entry.category,
                    'totalCost': math.ceil(total_cost) if total_cost is not None else None,
                    'location': entry.location, 'notes': entry.notes, 'editUrl': edit_url
                }
            })
    general_notes = GeneralNote.query.options(db.joinedload(GeneralNote.motorcycle)).filter_by(user_id=user_id).all()
    for note in general_notes:
        motorcycle_name = note.motorcycle.name if note.motorcycle else None
        note_title_display = note.title or ('タスク' if note.category == 'task' else 'メモ')
        icon = "✅" if note.category == 'task' else "📝"
        title_prefix = f"{icon} {'タスク' if note.category == 'task' else 'メモ'}: "
        event_type = note.category
        event_title = title_prefix + note_title_display[:15] + ("..." if len(note_title_display) > 15 else "")
        edit_url = url_for('notes.edit_note', note_id=note.id)
        extended_props = {
            'type': event_type, 'category': note.category, 'title': note.title,
            'motorcycleName': motorcycle_name, 'noteDate': note.note_date.strftime('%Y-%m-%d'),
            'createdAt': note.created_at.strftime('%Y-%m-%d %H:%M'),
            'updatedAt': note.updated_at.strftime('%Y-%m-%d %H:%M'), 'editUrl': edit_url
        }
        if event_type == 'task': extended_props['todos'] = note.todos if note.todos is not None else []
        else: extended_props['content'] = note.content
        events.append({
            'id': f'note-{note.id}', 'title': event_title, 'start': note.note_date.isoformat(),
            'allDay': True, 'url': edit_url,
            'backgroundColor': '#6c757d', 'borderColor': '#6c757d', 'textColor': 'white',
            'extendedProps': extended_props
        })
    return jsonify(events)

@main_bp.route('/terms_of_service')
def terms_of_service():
    return render_template('legal/terms_of_service.html', title="利用規約")

@main_bp.route('/privacy_policy')
def privacy_policy():
    return render_template('legal/privacy_policy.html', title="プライバシーポリシー")

@main_bp.before_app_request
def load_logged_in_user():
    g.user = get_current_user()

@main_bp.app_context_processor
def inject_user():
    return dict(g=g if hasattr(g, 'user') else None)