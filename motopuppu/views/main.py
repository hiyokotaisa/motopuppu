# motopuppu/views/main.py
from flask import (
    Blueprint, render_template, redirect, url_for, session, g, flash, current_app, jsonify, request
)
from datetime import date, timedelta, datetime # datetime をインポートリストに追加
from dateutil.relativedelta import relativedelta
from .auth import login_required_custom, get_current_user
from ..models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder, GeneralNote
from sqlalchemy import func, select
import math
import jpholiday # 祝日ライブラリ
import json     # JSONライブラリ
# from datetime import date # dateは既にdatetimeからインポートされているので不要

main_bp = Blueprint('main', __name__)

# --- ヘルパー関数 ---
def get_latest_total_distance(motorcycle_id, offset_val): # offset_val を引数で受け取るように変更
    """指定された公道車両IDの最新の総走行距離を取得"""
    # この関数は公道車両のODOメーターベースの距離を計算する前提
    latest_fuel_dist = db.session.query(db.func.max(FuelEntry.total_distance)).filter(FuelEntry.motorcycle_id == motorcycle_id).scalar() or 0
    latest_maint_dist = db.session.query(db.func.max(MaintenanceEntry.total_distance_at_maintenance)).filter(MaintenanceEntry.motorcycle_id == motorcycle_id).scalar() or 0
    return max(latest_fuel_dist, latest_maint_dist, offset_val if offset_val is not None else 0)

def calculate_average_kpl(motorcycle: Motorcycle): # Motorcycleオブジェクトを引数に取る
    """指定された公道車両の平均燃費を計算"""
    # --- ▼▼▼ フェーズ1変更点 (レーサー車両は燃費計算対象外) ▼▼▼ ---
    if motorcycle.is_racer:
        return None
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲ ---
    full_tank_entries = FuelEntry.query.filter(FuelEntry.motorcycle_id == motorcycle.id, FuelEntry.is_full_tank == True).order_by(FuelEntry.total_distance.asc()).all()
    if len(full_tank_entries) < 2: return None
    total_distance_traveled = full_tank_entries[-1].total_distance - full_tank_entries[0].total_distance
    first_entry_dist = full_tank_entries[0].total_distance
    last_entry_dist = full_tank_entries[-1].total_distance
    entries_in_period = FuelEntry.query.filter(
           FuelEntry.motorcycle_id == motorcycle.id,
           FuelEntry.total_distance > first_entry_dist,
           FuelEntry.total_distance <= last_entry_dist
    ).all()
    total_fuel_consumed = sum(entry.fuel_volume for entry in entries_in_period if entry.fuel_volume is not None)

    if total_fuel_consumed > 0 and total_distance_traveled > 0:
        return round(total_distance_traveled / total_fuel_consumed, 2)
    return None

def get_upcoming_reminders(user_motorcycles_all, user_id): # 全車両リストを受け取る
    """ユーザーの車両に関連する警告リマインダーを取得"""
    upcoming_reminders = []
    today = date.today()
    KM_THRESHOLD_WARNING = current_app.config.get('REMINDER_KM_WARNING', 500); DAYS_THRESHOLD_WARNING = current_app.config.get('REMINDER_DAYS_WARNING', 14)
    KM_THRESHOLD_DANGER = current_app.config.get('REMINDER_KM_DANGER', 0); DAYS_THRESHOLD_DANGER = current_app.config.get('REMINDER_DAYS_DANGER', 0)

    # --- ▼▼▼ フェーズ1変更点 (リマインダーの距離計算は公道車のみ対象) ▼▼▼
    current_public_distances = {}
    for m in user_motorcycles_all:
        if not m.is_racer: # 公道車のみ距離を取得
            current_public_distances[m.id] = get_latest_total_distance(m.id, m.odometer_offset)
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲

    all_reminders = MaintenanceReminder.query.options(db.joinedload(MaintenanceReminder.motorcycle)).join(Motorcycle).filter(Motorcycle.user_id == user_id).all()
    for reminder in all_reminders:
        motorcycle = reminder.motorcycle
        status = 'ok'; messages = []; due_info_parts = []; is_due = False

        # --- ▼▼▼ フェーズ1変更点 (距離ベースのリマインダーは公道車のみ評価) ▼▼▼
        if not motorcycle.is_racer and reminder.interval_km and reminder.last_done_km is not None:
            current_km = current_public_distances.get(motorcycle.id, 0) # 公道車の距離を取得
            next_km_due = reminder.last_done_km + reminder.interval_km
            remaining_km = next_km_due - current_km
            due_info_parts.append(f"{next_km_due:,} km")
            if remaining_km <= KM_THRESHOLD_DANGER: messages.append(f"距離超過 (現在 {current_km:,} km)"); status = 'danger'; is_due = True
            elif remaining_km <= KM_THRESHOLD_WARNING: messages.append(f"あと {remaining_km:,} km"); status = 'warning'; is_due = True
        # --- ▲▲▲ フェーズ1変更点 ▲▲▲

        # 期間ベースのリマインダーチェック (これは車両タイプに依存しない)
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
            # --- ▼▼▼ フェーズ1変更点 (公道車のみlast_done_kmを表示) ▼▼▼
            if not motorcycle.is_racer and reminder.last_done_km is not None:
                 last_done_str += f" ({reminder.last_done_km:,} km)" if reminder.last_done_date else f"{reminder.last_done_km:,} km"
            # --- ▲▲▲ フェーズ1変更点 ▲▲▲
            upcoming_reminders.append({
                'reminder_id': reminder.id,
                'motorcycle_id': motorcycle.id,
                'motorcycle_name': motorcycle.name,
                'task': reminder.task_description,
                'status': status,
                'message': ", ".join(messages) if messages else "要確認",
                'due_info': " / ".join(due_info_parts) if due_info_parts else '未設定',
                'last_done': last_done_str,
                'is_racer': motorcycle.is_racer # テンプレートで表示を分けるために追加
            })
    upcoming_reminders.sort(key=lambda x: (x['status'] != 'danger', x['status'] != 'warning'))
    return upcoming_reminders


# --- ルート定義 ---

@main_bp.route('/')
def index():
    g.user = get_current_user()
    if g.user: return redirect(url_for('main.dashboard'))
    return render_template('index.html')

@main_bp.route('/dashboard')
@login_required_custom
def dashboard():
    """ログイン後のダッシュボードを表示"""
    user_motorcycles_all = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles_all:
        flash('ようこそ！最初に利用する車両を登録してください。', 'info'); return redirect(url_for('vehicle.add_vehicle'))
    user_motorcycle_ids_all = [m.id for m in user_motorcycles_all]
    # --- ▼▼▼ フェーズ1変更点 (公道車のみのリストも用意) ▼▼▼
    user_motorcycles_public = [m for m in user_motorcycles_all if not m.is_racer]
    user_motorcycle_ids_public = [m.id for m in user_motorcycles_public]
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲

    selected_fuel_vehicle_id_str = request.args.get('fuel_vehicle_id')
    selected_maint_vehicle_id_str = request.args.get('maint_vehicle_id')
    selected_stats_vehicle_id_str = request.args.get('stats_vehicle_id')

    selected_fuel_vehicle_id = None
    if selected_fuel_vehicle_id_str:
        try:
            temp_id = int(selected_fuel_vehicle_id_str)
            if temp_id in user_motorcycle_ids_public: selected_fuel_vehicle_id = temp_id # 公道車のみ
        except ValueError: pass

    selected_maint_vehicle_id = None
    if selected_maint_vehicle_id_str:
        try:
            temp_id = int(selected_maint_vehicle_id_str)
            if temp_id in user_motorcycle_ids_public: selected_maint_vehicle_id = temp_id # 公道車のみ
        except ValueError: pass

    selected_stats_vehicle_id = None
    target_vehicle_for_stats = None
    if selected_stats_vehicle_id_str:
        try:
            temp_id = int(selected_stats_vehicle_id_str)
            if temp_id in user_motorcycle_ids_all: # 統計は全車両対象で選択可能
                selected_stats_vehicle_id = temp_id
                target_vehicle_for_stats = next((m for m in user_motorcycles_all if m.id == selected_stats_vehicle_id), None)
        except ValueError: pass

    # --- ▼▼▼ フェーズ1変更点 (直近の記録は公道車のみ対象) ▼▼▼
    fuel_query = FuelEntry.query.options(db.joinedload(FuelEntry.motorcycle)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public))
    if selected_fuel_vehicle_id: # selected_fuel_vehicle_id は公道車IDのはず
        fuel_query = fuel_query.filter(FuelEntry.motorcycle_id == selected_fuel_vehicle_id)
    recent_fuel_entries = fuel_query.order_by(FuelEntry.entry_date.desc(), FuelEntry.total_distance.desc()).limit(5).all()

    maint_query = MaintenanceEntry.query.options(db.joinedload(MaintenanceEntry.motorcycle)).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public))
    if selected_maint_vehicle_id: # selected_maint_vehicle_id は公道車IDのはず
        maint_query = maint_query.filter(MaintenanceEntry.motorcycle_id == selected_maint_vehicle_id)
    recent_maintenance_entries = maint_query.order_by(MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.total_distance_at_maintenance.desc()).limit(5).all()
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲

    upcoming_reminders = get_upcoming_reminders(user_motorcycles_all, g.user.id) # 全車両リストを渡す

    for m in user_motorcycles_all: # 全車両に対して平均燃費を計算（レーサーならNoneが返る）
        m._average_kpl = calculate_average_kpl(m)

    dashboard_stats = {
        'vehicle_name': None,
        'total_primary_metric': 0, # 距離または時間
        'total_primary_metric_unit': '', # km または 時間
        'average_kpl': None,
        'total_fuel_cost': 0,
        'total_maint_cost': 0,
        'is_specific_vehicle': False,
        'vehicle_name_for_cost': None,
        'is_racer_for_stats': False # 統計対象がレーサーか
    }
    if target_vehicle_for_stats:
        dashboard_stats['vehicle_name'] = target_vehicle_for_stats.name
        dashboard_stats['is_racer_for_stats'] = target_vehicle_for_stats.is_racer
        if target_vehicle_for_stats.is_racer:
            dashboard_stats['total_primary_metric'] = target_vehicle_for_stats.total_operating_hours if target_vehicle_for_stats.total_operating_hours is not None else 0
            dashboard_stats['total_primary_metric_unit'] = '時間'
            dashboard_stats['average_kpl'] = None # レーサーは燃費なし
        else:
            dashboard_stats['total_primary_metric'] = get_latest_total_distance(target_vehicle_for_stats.id, target_vehicle_for_stats.odometer_offset)
            dashboard_stats['total_primary_metric_unit'] = 'km'
            dashboard_stats['average_kpl'] = target_vehicle_for_stats._average_kpl

        # コストは車両タイプ問わず集計
        fuel_cost_q = db.session.query(func.sum(FuelEntry.total_cost)).filter(FuelEntry.motorcycle_id == target_vehicle_for_stats.id).scalar()
        dashboard_stats['total_fuel_cost'] = fuel_cost_q or 0
        maint_cost_q = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))).filter(MaintenanceEntry.motorcycle_id == target_vehicle_for_stats.id).scalar()
        dashboard_stats['total_maint_cost'] = maint_cost_q or 0
        dashboard_stats['is_specific_vehicle'] = True
        dashboard_stats['vehicle_name_for_cost'] = target_vehicle_for_stats.name
    else: # デフォルト車両または全車両の統計
        default_vehicle = next((m for m in user_motorcycles_all if m.is_default), user_motorcycles_all[0] if user_motorcycles_all else None)
        if default_vehicle:
            dashboard_stats['vehicle_name'] = f"デフォルト ({default_vehicle.name})"
            dashboard_stats['is_racer_for_stats'] = default_vehicle.is_racer
            if default_vehicle.is_racer:
                dashboard_stats['total_primary_metric'] = default_vehicle.total_operating_hours if default_vehicle.total_operating_hours is not None else 0
                dashboard_stats['total_primary_metric_unit'] = '時間'
                dashboard_stats['average_kpl'] = None
            else:
                dashboard_stats['total_primary_metric'] = get_latest_total_distance(default_vehicle.id, default_vehicle.odometer_offset)
                dashboard_stats['total_primary_metric_unit'] = 'km'
                dashboard_stats['average_kpl'] = default_vehicle._average_kpl
        else:
             dashboard_stats['vehicle_name'] = "車両未登録" # このケースは最初のガードでリダイレクトされるはず

        # 全車両のコスト合計 (公道車のみ対象)
        total_fuel_cost_query = db.session.query(func.sum(FuelEntry.total_cost)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public)).scalar()
        dashboard_stats['total_fuel_cost'] = total_fuel_cost_query or 0
        total_maint_cost_query = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public)).scalar()
        dashboard_stats['total_maint_cost'] = total_maint_cost_query or 0
        dashboard_stats['is_specific_vehicle'] = False
        dashboard_stats['vehicle_name_for_cost'] = "すべての公道車" # コストは公道車のみ対象

    holidays_json = '{}'
    try:
        today_for_holiday = date.today() # 変数名を変更
        years_to_fetch = [today_for_holiday.year - 1, today_for_holiday.year, today_for_holiday.year + 1]
        holidays_dict = {}
        for year in years_to_fetch:
            try:
                holidays_raw = jpholiday.year_holidays(year)
                for holiday_date_obj, holiday_name in holidays_raw: # 変数名を変更
                    holidays_dict[holiday_date_obj.strftime('%Y-%m-%d')] = holiday_name
            except Exception as e:
                 current_app.logger.error(f"Error fetching holidays for year {year}: {e}")
        holidays_json = json.dumps(holidays_dict)
    except Exception as e:
        current_app.logger.error(f"Error processing holidays data: {e}")
        flash('祝日情報の取得または処理中にエラーが発生しました。', 'warning')

    return render_template(
        'dashboard.html',
        motorcycles=user_motorcycles_all, # テンプレートには全車両渡す（表示側で制御）
        motorcycles_public=user_motorcycles_public, # フィルター用 (公道車のみ)
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
    # --- ▼▼▼ フェーズ1変更点 (カレンダーイベントの対象は公道車のみ) ▼▼▼
    user_motorcycle_ids_public = [m.id for m in Motorcycle.query.filter_by(user_id=user_id, is_racer=False).all()]
    # --- ▲▲▲ フェーズ1変更点 ▲▲▲

    if not user_motorcycle_ids_public: # 公道車がなければ給油・整備記録は表示しない
        # 一般ノートは表示する可能性があるため、ここでは早期リターンしない
        pass

    # 給油記録 (公道車のみ)
    if user_motorcycle_ids_public:
        fuel_entries = FuelEntry.query.options(db.joinedload(FuelEntry.motorcycle)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids_public)).all()
        for entry in fuel_entries:
            kpl = entry.km_per_liter
            kpl_display = f"{kpl:.2f} km/L" if kpl is not None else None
            edit_url = url_for('fuel.edit_fuel', entry_id=entry.id)
            events.append({
                'id': f'fuel-{entry.id}',
                'title': f"⛽ 給油: {entry.motorcycle.name}",
                'start': entry.entry_date.isoformat(),
                'allDay': True, 'url': edit_url, 'backgroundColor': '#198754', 'borderColor': '#198754', 'textColor': 'white',
                'extendedProps': {
                    'type': 'fuel', 'motorcycleName': entry.motorcycle.name, 'odometer': entry.odometer_reading,
                    'fuelVolume': entry.fuel_volume, 'kmPerLiter': kpl_display,
                    'totalCost': math.ceil(entry.total_cost) if entry.total_cost is not None else None,
                    'stationName': entry.station_name, 'notes': entry.notes, 'editUrl': edit_url
                }
            })

    # 整備記録 (公道車のみ、フェーズ1ではレーサーの整備記録はない)
    if user_motorcycle_ids_public:
        maintenance_entries = MaintenanceEntry.query.options(db.joinedload(MaintenanceEntry.motorcycle)).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids_public)).all()
        for entry in maintenance_entries:
            event_title_base = entry.category if entry.category else entry.description
            event_title = f"🔧 整備: {event_title_base[:15]}" + ("..." if len(event_title_base) > 15 else "")
            total_cost = entry.total_cost
            edit_url = url_for('maintenance.edit_maintenance', entry_id=entry.id)
            events.append({
                'id': f'maint-{entry.id}',
                'title': event_title,
                'start': entry.maintenance_date.isoformat(),
                'allDay': True, 'url': edit_url, 'backgroundColor': '#ffc107', 'borderColor': '#ffc107', 'textColor': 'black',
                'extendedProps': {
                    'type': 'maintenance', 'motorcycleName': entry.motorcycle.name, 'odometer': entry.total_distance_at_maintenance,
                    'description': entry.description, 'category': entry.category,
                    'totalCost': math.ceil(total_cost) if total_cost is not None else None,
                    'location': entry.location, 'notes': entry.notes, 'editUrl': edit_url
                }
            })

    # 一般ノート (これは全車両対象でOK)
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
            'allDay': True, 'url': edit_url, 'backgroundColor': '#6c757d', 'borderColor': '#6c757d', 'textColor': 'white',
            'extendedProps': extended_props
        })
    return jsonify(events)

@main_bp.route('/privacy')
def privacy_policy():
    return render_template('privacy_policy.html')

@main_bp.route('/terms')
def terms_of_service():
    return render_template('terms_of_service.html')