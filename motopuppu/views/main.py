# motopuppu/views/main.py

from flask import (
    Blueprint, render_template, redirect, url_for, session, g, flash, current_app, jsonify
)
# ▼▼▼ datetime と dateutil をインポート ▼▼▼
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
# ログイン必須デコレータと現在のユーザー取得関数
from .auth import login_required_custom, get_current_user
# ▼▼▼ MaintenanceReminder と db をインポート ▼▼▼
from ..models import db, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder
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

# --- ルート定義 ---

@main_bp.route('/')
def index():
    """トップページを表示"""
    g.user = get_current_user()
    return render_template('index.html')

@main_bp.route('/dashboard')
@login_required_custom
def dashboard():
    """ログイン後のダッシュボードを表示 (リマインダー通知付き)"""
    vehicle_count = Motorcycle.query.filter_by(user_id=g.user.id).count()
    if vehicle_count == 0:
        flash('ようこそ！最初に利用する車両を登録してください。', 'info')
        return redirect(url_for('vehicle.add_vehicle'))

    current_app.logger.debug(f"User {g.user.id} has {vehicle_count} vehicles. Showing dashboard.")

    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.id).all()
    user_motorcycle_ids = [m.id for m in user_motorcycles]

    # --- 平均燃費計算 ---
    # (既存のロジック - 変更なし)
    for m in user_motorcycles:
        full_tank_entries = FuelEntry.query.filter(FuelEntry.motorcycle_id == m.id, FuelEntry.is_full_tank == True).order_by(FuelEntry.total_distance.asc()).all()
        if len(full_tank_entries) < 2: m._average_kpl = None
        else:
            total_distance_traveled = full_tank_entries[-1].total_distance - full_tank_entries[0].total_distance
            total_fuel_consumed = sum(entry.fuel_volume for entry in full_tank_entries[1:])
            if total_fuel_consumed > 0 and total_distance_traveled > 0:
                 m._average_kpl = round(total_distance_traveled / total_fuel_consumed, 2)
            else: m._average_kpl = None

    # --- 直近の記録取得 ---
    # (既存のロジック - 変更なし)
    recent_fuel_entries = FuelEntry.query.filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids)).order_by(FuelEntry.entry_date.desc(), FuelEntry.total_distance.desc()).limit(5).all()
    recent_maintenance_entries = MaintenanceEntry.query.filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids)).order_by(MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.total_distance_at_maintenance.desc()).limit(5).all()


    # --- ▼▼▼ メンテナンスリマインダー通知処理 ▼▼▼ ---
    upcoming_reminders = [] # 通知リストを初期化
    today = date.today()    # 今日の日付を取得

    # 警告と注意の閾値設定 (configファイルや定数で管理するのが望ましい)
    KM_THRESHOLD_WARNING = current_app.config.get('REMINDER_KM_WARNING', 500)  # 例: 500km以内
    DAYS_THRESHOLD_WARNING = current_app.config.get('REMINDER_DAYS_WARNING', 14) # 例: 14日以内
    KM_THRESHOLD_DANGER = current_app.config.get('REMINDER_KM_DANGER', 0)     # 例: 0km以下 (超過)
    DAYS_THRESHOLD_DANGER = current_app.config.get('REMINDER_DAYS_DANGER', 0)   # 例: 0日以下 (超過)

    # 各車両の最新走行距離を事前に計算 (ループ内のDBアクセスを減らすため)
    current_distances = {
        m.id: get_latest_total_distance(m.id, m.odometer_offset) for m in user_motorcycles
    }

    # ユーザーの全車両のリマインダーを取得 (N+1問題を避けるため車両情報も一緒に読み込む)
    all_reminders = MaintenanceReminder.query.options(db.joinedload(MaintenanceReminder.motorcycle))\
                                             .join(Motorcycle)\
                                             .filter(Motorcycle.user_id == g.user.id)\
                                             .all()

    # 各リマインダーについてチェック
    for reminder in all_reminders:
        motorcycle = reminder.motorcycle # 事前ロードした車両情報
        current_km = current_distances.get(motorcycle.id, motorcycle.odometer_offset or 0) # 最新走行距離

        status = 'ok'         # 状態: ok, warning, danger
        messages = []         # 表示メッセージのリスト
        due_info_parts = []   # 目安情報 ["5000 km", "2025-06-01"]
        is_due = False        # 警告対象フラグ

        # --- 距離ベースのチェック ---
        if reminder.interval_km and reminder.last_done_km is not None:
            next_km_due = reminder.last_done_km + reminder.interval_km
            remaining_km = next_km_due - current_km
            due_info_parts.append(f"{next_km_due:,} km") # 目安距離

            if remaining_km <= KM_THRESHOLD_DANGER:
                messages.append(f"距離超過 (現在 {current_km:,} km)")
                status = 'danger'
                is_due = True
            elif remaining_km <= KM_THRESHOLD_WARNING:
                messages.append(f"あと {remaining_km:,} km")
                # 既に danger でなければ warning に更新
                if status != 'danger': status = 'warning'
                is_due = True

        # --- 期間ベースのチェック ---
        if reminder.interval_months and reminder.last_done_date:
            try:
                next_date_due = reminder.last_done_date + relativedelta(months=reminder.interval_months)
                remaining_days = (next_date_due - today).days
                due_info_parts.append(f"{next_date_due.strftime('%Y-%m-%d')}") # 目安日付

                period_status = 'ok'
                period_message = ''
                if remaining_days <= DAYS_THRESHOLD_DANGER:
                    period_status = 'danger'
                    period_message = f"期限超過"
                elif remaining_days <= DAYS_THRESHOLD_WARNING:
                    period_status = 'warning'
                    period_message = f"あと {remaining_days} 日"

                # 期間ベースで警告対象の場合
                if period_status != 'ok':
                    is_due = True
                    if period_message: messages.append(period_message) # メッセージを追加
                    # ステータスを更新 (より厳しい方を優先)
                    if (period_status == 'danger') or \
                       (period_status == 'warning' and status != 'danger'):
                        status = period_status

            except Exception as e:
                 # relativedelta でエラーが発生した場合 (日付計算など)
                 current_app.logger.error(f"Error calculating next date for reminder {reminder.id}: {e}")
                 messages.append("日付計算エラー")
                 if status == 'ok': status = 'warning' # エラーも警告扱いにする
                 is_due = True # 計算エラーも通知対象とする

        # --- 警告対象のリマインダー情報をリストに追加 ---
        if is_due:
            # 最終実施記録の表示用文字列を作成
            last_done_str = "未実施"
            if reminder.last_done_date:
                last_done_str = reminder.last_done_date.strftime('%Y-%m-%d')
                if reminder.last_done_km is not None:
                    last_done_str += f" ({reminder.last_done_km:,} km)"
            elif reminder.last_done_km is not None:
                 last_done_str = f"{reminder.last_done_km:,} km"

            upcoming_reminders.append({
                'reminder_id': reminder.id,
                'motorcycle_id': motorcycle.id,
                'motorcycle_name': motorcycle.name,
                'task': reminder.task_description,
                'status': status, # 'danger' or 'warning'
                'message': ", ".join(messages) if messages else "要確認", # 状況メッセージ
                'due_info': " / ".join(due_info_parts), # 目安情報
                'last_done': last_done_str # 最終実施情報
            })

    # リマインダーリストをステータス(danger > warning)でソート (任意)
    upcoming_reminders.sort(key=lambda x: (x['status'] != 'danger', x['status'] != 'warning'))

    # --- ▲▲▲ メンテナンスリマインダー通知処理ここまで ▲▲▲ ---


    # --- テンプレートへのデータ渡し ---
    return render_template('dashboard.html',
                           motorcycles=user_motorcycles,
                           recent_fuel_entries=recent_fuel_entries,
                           recent_maintenance_entries=recent_maintenance_entries,
                           # ▼▼▼ 計算結果のリストを渡す ▼▼▼
                           upcoming_reminders=upcoming_reminders)


# --- APIエンドポイント ---
# (変更なし)
@main_bp.route('/api/dashboard/events')
@login_required_custom
def dashboard_events_api():
    """ダッシュボードのFullCalendarに表示するイベントデータを返すAPI (詳細情報付き)"""
    events = []
    user_motorcycle_ids = [m.id for m in Motorcycle.query.filter_by(user_id=g.user.id).all()]
    # (給油記録の処理 - 変更なし)
    fuel_entries = FuelEntry.query.filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids)).all()
    for entry in fuel_entries:
        kpl = entry.km_per_liter
        kpl_display = f"{kpl:.2f} km/L" if kpl is not None else None
        events.append({
            'title': f"給油: {entry.motorcycle.name}", 'start': entry.entry_date.isoformat(),
            'url': url_for('fuel.edit_fuel', entry_id=entry.id),
            'backgroundColor': '#198754', 'borderColor': '#198754', 'textColor': 'white',
            'extendedProps': { 'type': 'fuel', 'motorcycleName': entry.motorcycle.name, 'odometer': entry.odometer_reading,
                'fuelVolume': entry.fuel_volume, 'kmPerLiter': kpl_display,
                'totalCost': math.ceil(entry.total_cost) if entry.total_cost is not None else None,
                'stationName': entry.station_name, 'notes': entry.notes }
        })
    # (整備記録の処理 - 変更なし)
    maintenance_entries = MaintenanceEntry.query.filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids)).all()
    for entry in maintenance_entries:
        event_title_base = entry.category if entry.category else entry.description
        event_title = f"整備: {event_title_base[:15]}" + ("..." if len(event_title_base) > 15 else "")
        total_cost = entry.total_cost
        events.append({
            'title': event_title, 'start': entry.maintenance_date.isoformat(),
            'url': url_for('maintenance.edit_maintenance', entry_id=entry.id),
            'backgroundColor': '#ffc107', 'borderColor': '#ffc107', 'textColor': 'black',
            'extendedProps': { 'type': 'maintenance', 'motorcycleName': entry.motorcycle.name, 'odometer': entry.total_distance_at_maintenance,
                'description': entry.description, 'category': entry.category,
                'totalCost': math.ceil(total_cost) if total_cost is not None else None,
                'location': entry.location, 'notes': entry.notes }
        })
    return jsonify(events)

# --- (他のルートやエラーハンドラは省略) ---