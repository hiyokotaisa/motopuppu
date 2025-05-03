# motopuppu/views/main.py

from flask import (
    Blueprint, render_template, redirect, url_for, session, g, flash, current_app, jsonify, request # request をインポート
)
# ▼▼▼ datetime と dateutil をインポート ▼▼▼
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
# ログイン必須デコレータと現在のユーザー取得関数
from .auth import login_required_custom, get_current_user
# ▼▼▼ MaintenanceReminder と db をインポート ▼▼▼
from ..models import db, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder
# ▼▼▼ SQLAlchemyの集計関数などを使うために追加 ▼▼▼
from sqlalchemy import func
import math

main_bp = Blueprint('main', __name__)

# --- ヘルパー関数 (任意): 最新走行距離を取得 ---
def get_latest_total_distance(motorcycle_id, offset):
    """指定された車両IDの最新の総走行距離を取得"""
    # SQLAlchemyの機能を使って最大値を取得
    latest_fuel_dist = db.session.query(db.func.max(FuelEntry.total_distance))\
                                 .filter(FuelEntry.motorcycle_id == motorcycle_id)\
                                 .scalar() or 0 # 結果がNoneなら0を返す
    latest_maint_dist = db.session.query(db.func.max(MaintenanceEntry.total_distance_at_maintenance))\
                                          .filter(MaintenanceEntry.motorcycle_id == motorcycle_id)\
                                          .scalar() or 0 # 結果がNoneなら0を返す

    # オフセットも考慮 (記録がない場合はオフセットのみが基準になる)
    return max(latest_fuel_dist, latest_maint_dist, offset or 0) # offsetがNoneの場合も考慮

# --- ヘルパー関数 (任意): 平均燃費計算 ---
def calculate_average_kpl(motorcycle_id):
     """指定された車両IDの平均燃費を計算"""
     full_tank_entries = FuelEntry.query.filter(
         FuelEntry.motorcycle_id == motorcycle_id,
         FuelEntry.is_full_tank == True
     ).order_by(FuelEntry.total_distance.asc()).all()

     if len(full_tank_entries) < 2:
         return None
     else:
         total_distance_traveled = full_tank_entries[-1].total_distance - full_tank_entries[0].total_distance
         total_fuel_consumed = sum(entry.fuel_volume for entry in full_tank_entries[1:])
         if total_fuel_consumed > 0 and total_distance_traveled > 0:
             avg_kpl = total_distance_traveled / total_fuel_consumed
             return round(avg_kpl, 2)
         else:
             return None

# --- ヘルパー関数 (任意): リマインダー通知取得 ---
def get_upcoming_reminders(user_motorcycles, user_id):
    """ユーザーの車両に関連する警告リマインダーを取得"""
    upcoming_reminders = []
    today = date.today()
    KM_THRESHOLD_WARNING = current_app.config.get('REMINDER_KM_WARNING', 500)
    DAYS_THRESHOLD_WARNING = current_app.config.get('REMINDER_DAYS_WARNING', 14)
    KM_THRESHOLD_DANGER = current_app.config.get('REMINDER_KM_DANGER', 0)
    DAYS_THRESHOLD_DANGER = current_app.config.get('REMINDER_DAYS_DANGER', 0)

    current_distances = {
        m.id: get_latest_total_distance(m.id, m.odometer_offset) for m in user_motorcycles
    }
    all_reminders = MaintenanceReminder.query.options(db.joinedload(MaintenanceReminder.motorcycle))\
                                             .join(Motorcycle)\
                                             .filter(Motorcycle.user_id == user_id)\
                                             .all()

    for reminder in all_reminders:
        motorcycle = reminder.motorcycle
        current_km = current_distances.get(motorcycle.id, motorcycle.odometer_offset or 0)
        status = 'ok'; messages = []; due_info_parts = []; is_due = False

        # 距離チェック
        if reminder.interval_km and reminder.last_done_km is not None:
            next_km_due = reminder.last_done_km + reminder.interval_km
            remaining_km = next_km_due - current_km
            due_info_parts.append(f"{next_km_due:,} km")
            if remaining_km <= KM_THRESHOLD_DANGER:
                messages.append(f"距離超過 (現在 {current_km:,} km)"); status = 'danger'; is_due = True
            elif remaining_km <= KM_THRESHOLD_WARNING:
                messages.append(f"あと {remaining_km:,} km");
                if status != 'danger': status = 'warning'
                is_due = True
        # 期間チェック
        if reminder.interval_months and reminder.last_done_date:
            try:
                next_date_due = reminder.last_done_date + relativedelta(months=reminder.interval_months)
                remaining_days = (next_date_due - today).days
                due_info_parts.append(f"{next_date_due.strftime('%Y-%m-%d')}")
                period_status = 'ok'; period_message = ''
                if remaining_days <= DAYS_THRESHOLD_DANGER: period_status = 'danger'; period_message = f"期限超過"
                elif remaining_days <= DAYS_THRESHOLD_WARNING: period_status = 'warning'; period_message = f"あと {remaining_days} 日"
                if period_status != 'ok':
                    is_due = True;
                    if period_message: messages.append(period_message)
                    if (period_status == 'danger') or (period_status == 'warning' and status != 'danger'): status = period_status
            except Exception as e:
                 current_app.logger.error(f"Error calculating next date for reminder {reminder.id}: {e}")
                 messages.append("日付計算エラー");
                 if status == 'ok': status = 'warning'
                 is_due = True

        if is_due:
            last_done_str = "未実施"
            if reminder.last_done_date:
                last_done_str = reminder.last_done_date.strftime('%Y-%m-%d')
                if reminder.last_done_km is not None: last_done_str += f" ({reminder.last_done_km:,} km)"
            elif reminder.last_done_km is not None: last_done_str = f"{reminder.last_done_km:,} km"
            upcoming_reminders.append({
                'reminder_id': reminder.id, 'motorcycle_id': motorcycle.id, 'motorcycle_name': motorcycle.name,
                'task': reminder.task_description, 'status': status, 'message': ", ".join(messages) if messages else "要確認",
                'due_info': " / ".join(due_info_parts), 'last_done': last_done_str
            })

    upcoming_reminders.sort(key=lambda x: (x['status'] != 'danger', x['status'] != 'warning'))
    return upcoming_reminders


# --- ルート定義 ---

@main_bp.route('/')
def index():
    """トップページまたはダッシュボードを表示"""
    g.user = get_current_user()
    if g.user:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')

@main_bp.route('/dashboard')
@login_required_custom
def dashboard():
    """ログイン後のダッシュボードを表示 (フィルター付き直近記録、リマインダー通知、統計付き)"""
    # ユーザーの車両リスト取得
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles:
        flash('ようこそ！最初に利用する車両を登録してください。', 'info'); return redirect(url_for('vehicle.add_vehicle'))
    user_motorcycle_ids = [m.id for m in user_motorcycles]

    # --- フィルター用車両IDを取得 ---
    selected_fuel_vehicle_id_str = request.args.get('fuel_vehicle_id'); selected_maint_vehicle_id_str = request.args.get('maint_vehicle_id')
    selected_fuel_vehicle_id = None; selected_maint_vehicle_id = None
    if selected_fuel_vehicle_id_str:
        try: selected_fuel_vehicle_id = int(selected_fuel_vehicle_id_str);
        if selected_fuel_vehicle_id not in user_motorcycle_ids: selected_fuel_vehicle_id = None
        except ValueError: selected_fuel_vehicle_id = None
    if selected_maint_vehicle_id_str:
        try: selected_maint_vehicle_id = int(selected_maint_vehicle_id_str);
        if selected_maint_vehicle_id not in user_motorcycle_ids: selected_maint_vehicle_id = None
        except ValueError: selected_maint_vehicle_id = None

    # --- 直近の給油記録 (フィルター適用) ---
    fuel_query = FuelEntry.query.filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids))
    if selected_fuel_vehicle_id: fuel_query = fuel_query.filter(FuelEntry.motorcycle_id == selected_fuel_vehicle_id)
    recent_fuel_entries = fuel_query.order_by(FuelEntry.entry_date.desc(), FuelEntry.total_distance.desc()).limit(5).all()

    # --- 直近の整備記録 (フィルター適用) ---
    maint_query = MaintenanceEntry.query.filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids))
    if selected_maint_vehicle_id: maint_query = maint_query.filter(MaintenanceEntry.motorcycle_id == selected_maint_vehicle_id)
    recent_maintenance_entries = maint_query.order_by(MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.total_distance_at_maintenance.desc()).limit(5).all()

    # --- リマインダー通知取得 ---
    upcoming_reminders = get_upcoming_reminders(user_motorcycles, g.user.id)

    # --- 平均燃費計算 (各車両用) ---
    for m in user_motorcycles: m._average_kpl = calculate_average_kpl(m.id)


    # --- ▼▼▼ 統計情報サマリー計算 ▼▼▼ ---
    dashboard_stats = {
        'default_vehicle_name': None,
        'total_distance': 0,
        'average_kpl': None,
        'total_fuel_cost': 0,
        'total_maint_cost': 0,
    }
    # デフォルト車両または最初の車両を取得
    default_vehicle = next((m for m in user_motorcycles if m.is_default), user_motorcycles[0] if user_motorcycles else None)

    if default_vehicle:
        dashboard_stats['default_vehicle_name'] = default_vehicle.name
        # デフォルト車両の総走行距離
        dashboard_stats['total_distance'] = get_latest_total_distance(default_vehicle.id, default_vehicle.odometer_offset)
        # デフォルト車両の平均燃費 (計算済み)
        dashboard_stats['average_kpl'] = default_vehicle._average_kpl # 上のループで計算済み

    # 全車両の累計給油費用
    total_fuel_cost_query = db.session.query(func.sum(FuelEntry.total_cost))\
                                      .filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids))\
                                      .scalar()
    dashboard_stats['total_fuel_cost'] = total_fuel_cost_query or 0

    # 全車両の累計整備費用 (部品代 + 工賃、NULLは0として扱う)
    total_maint_cost_query = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0)))\
                                        .filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids))\
                                        .scalar()
    dashboard_stats['total_maint_cost'] = total_maint_cost_query or 0

    # --- ▲▲▲ 統計情報サマリー計算ここまで ▲▲▲ ---


    # --- テンプレートへのデータ渡し ---
    return render_template(
        'dashboard.html',
        motorcycles=user_motorcycles,
        recent_fuel_entries=recent_fuel_entries,
        recent_maintenance_entries=recent_maintenance_entries,
        upcoming_reminders=upcoming_reminders,
        selected_fuel_vehicle_id=selected_fuel_vehicle_id,
        selected_maint_vehicle_id=selected_maint_vehicle_id,
        # ▼▼▼ 計算した統計情報を渡す ▼▼▼
        dashboard_stats=dashboard_stats
    )


# --- APIエンドポイント (変更なし) ---
@main_bp.route('/api/dashboard/events')
@login_required_custom
def dashboard_events_api():
    """ダッシュボードのFullCalendarに表示するイベントデータを返すAPI (詳細情報付き)"""
    # (変更なし)
    events = []
    user_motorcycle_ids = [m.id for m in Motorcycle.query.filter_by(user_id=g.user.id).all()]
    fuel_entries = FuelEntry.query.filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids)).all()
    for entry in fuel_entries:
        kpl = entry.km_per_liter; kpl_display = f"{kpl:.2f} km/L" if kpl is not None else None
        events.append({ 'title': f"給油: {entry.motorcycle.name}", 'start': entry.entry_date.isoformat(), 'url': url_for('fuel.edit_fuel', entry_id=entry.id), 'backgroundColor': '#198754', 'borderColor': '#198754', 'textColor': 'white',
            'extendedProps': { 'type': 'fuel', 'motorcycleName': entry.motorcycle.name, 'odometer': entry.odometer_reading, 'fuelVolume': entry.fuel_volume, 'kmPerLiter': kpl_display, 'totalCost': math.ceil(entry.total_cost) if entry.total_cost is not None else None, 'stationName': entry.station_name, 'notes': entry.notes } })
    maintenance_entries = MaintenanceEntry.query.filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids)).all()
    for entry in maintenance_entries:
        event_title_base = entry.category if entry.category else entry.description; event_title = f"整備: {event_title_base[:15]}" + ("..." if len(event_title_base) > 15 else "")
        total_cost = entry.total_cost
        events.append({ 'title': event_title, 'start': entry.maintenance_date.isoformat(), 'url': url_for('maintenance.edit_maintenance', entry_id=entry.id), 'backgroundColor': '#ffc107', 'borderColor': '#ffc107', 'textColor': 'black',
            'extendedProps': { 'type': 'maintenance', 'motorcycleName': entry.motorcycle.name, 'odometer': entry.total_distance_at_maintenance, 'description': entry.description, 'category': entry.category, 'totalCost': math.ceil(total_cost) if total_cost is not None else None, 'location': entry.location, 'notes': entry.notes } })
    return jsonify(events)