# motopuppu/views/main.py
from flask import (
    Blueprint, render_template, redirect, url_for, session, g, flash, current_app, jsonify, request # request をインポート
)
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
# ログイン必須デコレータと現在のユーザー取得関数
from .auth import login_required_custom, get_current_user
# モデルとdbオブジェクトをインポート
# <<< 修正: GeneralNote モデルを追加 >>>
from ..models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder, GeneralNote
# SQLAlchemyの集計関数などを使うために追加
from sqlalchemy import func
import math

main_bp = Blueprint('main', __name__)

# --- ヘルパー関数 (変更なし) ---
def get_latest_total_distance(motorcycle_id, offset):
    """指定された車両IDの最新の総走行距離を取得"""
    latest_fuel_dist = db.session.query(db.func.max(FuelEntry.total_distance))\
                                 .filter(FuelEntry.motorcycle_id == motorcycle_id)\
                                 .scalar() or 0
    latest_maint_dist = db.session.query(db.func.max(MaintenanceEntry.total_distance_at_maintenance))\
                                          .filter(MaintenanceEntry.motorcycle_id == motorcycle_id)\
                                          .scalar() or 0
    return max(latest_fuel_dist, latest_maint_dist, offset or 0)

def calculate_average_kpl(motorcycle_id):
     """指定された車両IDの平均燃費を計算"""
     full_tank_entries = FuelEntry.query.filter(
         FuelEntry.motorcycle_id == motorcycle_id,
         FuelEntry.is_full_tank == True
     ).order_by(FuelEntry.total_distance.asc()).all()
     if len(full_tank_entries) < 2: return None
     total_distance_traveled = full_tank_entries[-1].total_distance - full_tank_entries[0].total_distance
     total_fuel_consumed = sum(entry.fuel_volume for entry in full_tank_entries[1:])
     if total_fuel_consumed > 0 and total_distance_traveled > 0:
         return round(total_distance_traveled / total_fuel_consumed, 2)
     return None

def get_upcoming_reminders(user_motorcycles, user_id):
    """ユーザーの車両に関連する警告リマインダーを取得"""
    upcoming_reminders = []
    today = date.today()
    KM_THRESHOLD_WARNING = current_app.config.get('REMINDER_KM_WARNING', 500)
    DAYS_THRESHOLD_WARNING = current_app.config.get('REMINDER_DAYS_WARNING', 14)
    KM_THRESHOLD_DANGER = current_app.config.get('REMINDER_KM_DANGER', 0)
    DAYS_THRESHOLD_DANGER = current_app.config.get('REMINDER_DAYS_DANGER', 0)
    current_distances = { m.id: get_latest_total_distance(m.id, m.odometer_offset) for m in user_motorcycles }
    all_reminders = MaintenanceReminder.query.options(db.joinedload(MaintenanceReminder.motorcycle)).join(Motorcycle).filter(Motorcycle.user_id == user_id).all()
    for reminder in all_reminders:
        motorcycle = reminder.motorcycle; current_km = current_distances.get(motorcycle.id, motorcycle.odometer_offset or 0)
        status = 'ok'; messages = []; due_info_parts = []; is_due = False
        if reminder.interval_km and reminder.last_done_km is not None:
            next_km_due = reminder.last_done_km + reminder.interval_km; remaining_km = next_km_due - current_km
            due_info_parts.append(f"{next_km_due:,} km")
            if remaining_km <= KM_THRESHOLD_DANGER: messages.append(f"距離超過 (現在 {current_km:,} km)"); status = 'danger'; is_due = True
            elif remaining_km <= KM_THRESHOLD_WARNING: messages.append(f"あと {remaining_km:,} km");
            if status != 'danger': status = 'warning'; is_due = True
        if reminder.interval_months and reminder.last_done_date:
            try:
                next_date_due = reminder.last_done_date + relativedelta(months=reminder.interval_months); remaining_days = (next_date_due - today).days
                due_info_parts.append(f"{next_date_due.strftime('%Y-%m-%d')}")
                period_status = 'ok'; period_message = ''
                if remaining_days <= DAYS_THRESHOLD_DANGER: period_status = 'danger'; period_message = f"期限超過"
                elif remaining_days <= DAYS_THRESHOLD_WARNING: period_status = 'warning'; period_message = f"あと {remaining_days} 日"
                if period_status != 'ok':
                    is_due = True;
                    if period_message: messages.append(period_message)
                    if (period_status == 'danger') or (period_status == 'warning' and status != 'danger'): status = period_status
            except Exception as e: current_app.logger.error(f"Error calc date reminder {reminder.id}: {e}"); messages.append("日付計算エラー");
            if status == 'ok': status = 'warning'; is_due = True
        if is_due:
            last_done_str = "未実施"
            if reminder.last_done_date: last_done_str = reminder.last_done_date.strftime('%Y-%m-%d');
            if reminder.last_done_km is not None: last_done_str += f" ({reminder.last_done_km:,} km)" if reminder.last_done_date else f"{reminder.last_done_km:,} km"
            upcoming_reminders.append({ 'reminder_id': reminder.id, 'motorcycle_id': motorcycle.id, 'motorcycle_name': motorcycle.name, 'task': reminder.task_description, 'status': status, 'message': ", ".join(messages) if messages else "要確認", 'due_info': " / ".join(due_info_parts), 'last_done': last_done_str })
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
    """ログイン後のダッシュボードを表示 (フィルター付き直近記録、リマインダー通知、統計付き)"""
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles:
        flash('ようこそ！最初に利用する車両を登録してください。', 'info'); return redirect(url_for('vehicle.add_vehicle'))
    user_motorcycle_ids = [m.id for m in user_motorcycles]

    # --- フィルター用車両IDを取得 (変更なし) ---
    selected_fuel_vehicle_id_str = request.args.get('fuel_vehicle_id')
    selected_maint_vehicle_id_str = request.args.get('maint_vehicle_id')
    selected_fuel_vehicle_id = None
    if selected_fuel_vehicle_id_str:
        temp_id_fuel = None
        try:
            temp_id_fuel = int(selected_fuel_vehicle_id_str)
            if temp_id_fuel in user_motorcycle_ids:
                selected_fuel_vehicle_id = temp_id_fuel
        except ValueError: pass
    selected_maint_vehicle_id = None
    if selected_maint_vehicle_id_str:
        temp_id_maint = None
        try:
            temp_id_maint = int(selected_maint_vehicle_id_str)
            if temp_id_maint in user_motorcycle_ids:
                selected_maint_vehicle_id = temp_id_maint
        except ValueError: pass

    # --- 直近の記録 (フィルター適用) (変更なし) ---
    fuel_query = FuelEntry.query.filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids))
    if selected_fuel_vehicle_id:
        fuel_query = fuel_query.filter(FuelEntry.motorcycle_id == selected_fuel_vehicle_id)
    recent_fuel_entries = fuel_query.order_by(FuelEntry.entry_date.desc(), FuelEntry.total_distance.desc()).limit(5).all()
    maint_query = MaintenanceEntry.query.filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids))
    if selected_maint_vehicle_id:
        maint_query = maint_query.filter(MaintenanceEntry.motorcycle_id == selected_maint_vehicle_id)
    recent_maintenance_entries = maint_query.order_by(MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.total_distance_at_maintenance.desc()).limit(5).all()

    # --- リマインダー通知取得 (変更なし) ---
    upcoming_reminders = get_upcoming_reminders(user_motorcycles, g.user.id)

    # --- 平均燃費計算 (変更なし) ---
    for m in user_motorcycles: m._average_kpl = calculate_average_kpl(m.id)

    # --- 統計情報サマリー計算 (変更なし) ---
    dashboard_stats = { 'default_vehicle_name': None, 'total_distance': 0, 'average_kpl': None, 'total_fuel_cost': 0, 'total_maint_cost': 0, }
    default_vehicle = next((m for m in user_motorcycles if m.is_default), user_motorcycles[0] if user_motorcycles else None)
    if default_vehicle:
        dashboard_stats['default_vehicle_name'] = default_vehicle.name
        dashboard_stats['total_distance'] = get_latest_total_distance(default_vehicle.id, default_vehicle.odometer_offset)
        dashboard_stats['average_kpl'] = default_vehicle._average_kpl
    total_fuel_cost_query = db.session.query(func.sum(FuelEntry.total_cost)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids)).scalar()
    dashboard_stats['total_fuel_cost'] = total_fuel_cost_query or 0
    total_maint_cost_query = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids)).scalar()
    dashboard_stats['total_maint_cost'] = total_maint_cost_query or 0

    # --- テンプレートへのデータ渡し (変更なし) ---
    return render_template(
        'dashboard.html',
        motorcycles=user_motorcycles,
        recent_fuel_entries=recent_fuel_entries,
        recent_maintenance_entries=recent_maintenance_entries,
        upcoming_reminders=upcoming_reminders,
        selected_fuel_vehicle_id=selected_fuel_vehicle_id,
        selected_maint_vehicle_id=selected_maint_vehicle_id,
        dashboard_stats=dashboard_stats
    )

# --- APIエンドポイント ---
@main_bp.route('/api/dashboard/events')
@login_required_custom
def dashboard_events_api():
    """カレンダー表示用のイベントデータをJSONで返す"""
    events = []
    # ログイン中のユーザーIDを取得 (g.userはlogin_required_customで設定される想定)
    if not g.user:
        return jsonify({'error': 'User not logged in'}), 401 # 念のためチェック

    user_id = g.user.id
    user_motorcycle_ids = [m.id for m in Motorcycle.query.filter_by(user_id=user_id).all()]

    # 給油記録
    fuel_entries = FuelEntry.query.filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids)).all()
    for entry in fuel_entries:
        kpl = entry.km_per_liter
        kpl_display = f"{kpl:.2f} km/L" if kpl is not None else None
        events.append({
            'id': f'fuel-{entry.id}', # <<< 修正: イベントIDを追加 >>>
            'title': f"⛽ 給油: {entry.motorcycle.name}",
            'start': entry.entry_date.isoformat(),
            'allDay': True, # <<< 修正: 終日イベントとして指定 >>>
            'url': url_for('fuel.edit_fuel', entry_id=entry.id),
            'backgroundColor': '#198754',
            'borderColor': '#198754',
            'textColor': 'white',
            'extendedProps': {
                'type': 'fuel',
                'motorcycleName': entry.motorcycle.name,
                'odometer': entry.odometer_reading,
                'fuelVolume': entry.fuel_volume,
                'kmPerLiter': kpl_display,
                'totalCost': math.ceil(entry.total_cost) if entry.total_cost is not None else None,
                'stationName': entry.station_name,
                'notes': entry.notes
            }
        })

    # 整備記録
    maintenance_entries = MaintenanceEntry.query.filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids)).all()
    for entry in maintenance_entries:
        event_title_base = entry.category if entry.category else entry.description
        event_title = f"🔧 整備: {event_title_base[:15]}" + ("..." if len(event_title_base) > 15 else "")
        total_cost = entry.total_cost
        events.append({
            'id': f'maint-{entry.id}', # <<< 修正: イベントIDを追加 >>>
            'title': event_title,
            'start': entry.maintenance_date.isoformat(),
            'allDay': True, # <<< 修正: 終日イベントとして指定 >>>
            'url': url_for('maintenance.edit_maintenance', entry_id=entry.id),
            'backgroundColor': '#ffc107',
            'borderColor': '#ffc107',
            'textColor': 'black',
            'extendedProps': {
                'type': 'maintenance',
                'motorcycleName': entry.motorcycle.name,
                'odometer': entry.total_distance_at_maintenance,
                'description': entry.description,
                'category': entry.category,
                'totalCost': math.ceil(total_cost) if total_cost is not None else None,
                'location': entry.location,
                'notes': entry.notes
            }
        })

    # --- ▼▼▼ 一般ノート追加 ▼▼▼ ---
    # GeneralNote モデルからデータを取得 (optionsで関連Motorcycleを事前ロード)
    general_notes = GeneralNote.query.options(db.joinedload(GeneralNote.motorcycle)).filter_by(user_id=user_id).all()
    for note in general_notes:
        motorcycle_name = note.motorcycle.name if note.motorcycle else None # 関連車両名を取得
        note_title_display = note.title or '無題' # タイトルがない場合は「無題」
        events.append({
            'id': f'note-{note.id}', # ノート用の一意なID
            'title': f"📝 メモ: {note_title_display[:15]}" + ("..." if len(note_title_display) > 15 else ""), # タイトル設定 (長すぎる場合は省略)
            'start': note.note_date.isoformat(), # note_date を使用
            'allDay': True, # 終日イベントとして扱う
            'url': url_for('notes.edit_note', note_id=note.id), # 編集画面へのURL (Blueprint/route名は要確認)
            # ノート用の色を設定 (例: Bootstrap secondary)
            'backgroundColor': '#6c757d',
            'borderColor': '#6c757d',
            'textColor': 'white',
            'extendedProps': {
                'type': 'note', # イベントタイプを 'note' に設定
                'title': note.title, # フルタイトル
                'content': note.content, # 本文
                'motorcycleName': motorcycle_name, # 関連車両名 (ない場合は None)
                'noteDate': note.note_date.strftime('%Y-%m-%d'), # 表示用の日付文字列
                'createdAt': note.created_at.strftime('%Y-%m-%d %H:%M'), # 作成日時 (表示用)
                # 'url'はトップレベルにあるのでここでは不要かもだが、一応残す
                'url': url_for('notes.edit_note', note_id=note.id)
            }
        })
    # --- ▲▲▲ 一般ノート追加ここまで ▲▲▲ ---

    return jsonify(events)