# motopuppu/views/main.py
from flask import (
    Blueprint, render_template, redirect, url_for, session, g, flash, current_app, jsonify, request
)
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from .auth import login_required_custom, get_current_user
from ..models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, MaintenanceReminder, GeneralNote
from sqlalchemy import func, select
import math
import jpholiday # 祝日ライブラリ
import json     # JSONライブラリ
from datetime import date

main_bp = Blueprint('main', __name__)

# --- ヘルパー関数 (変更なし) ---
def get_latest_total_distance(motorcycle_id, offset):
    """指定された車両IDの最新の総走行距離を取得"""
    latest_fuel_dist = db.session.query(db.func.max(FuelEntry.total_distance)).filter(FuelEntry.motorcycle_id == motorcycle_id).scalar() or 0
    latest_maint_dist = db.session.query(db.func.max(MaintenanceEntry.total_distance_at_maintenance)).filter(MaintenanceEntry.motorcycle_id == motorcycle_id).scalar() or 0
    return max(latest_fuel_dist, latest_maint_dist, offset or 0)

def calculate_average_kpl(motorcycle_id):
     """指定された車両IDの平均燃費を計算"""
     full_tank_entries = FuelEntry.query.filter(FuelEntry.motorcycle_id == motorcycle_id, FuelEntry.is_full_tank == True).order_by(FuelEntry.total_distance.asc()).all()
     if len(full_tank_entries) < 2: return None
     total_distance_traveled = full_tank_entries[-1].total_distance - full_tank_entries[0].total_distance
     # ★ 最初の満タン記録を除くエントリの給油量を合計 ★
     #   (以前は full_tank_entries[1:] を合計していたが、これだと区間内の非満タン給油が含まれない)
     #   区間内の全ての給油記録を取得して合計する方式に変更
     first_entry_dist = full_tank_entries[0].total_distance
     last_entry_dist = full_tank_entries[-1].total_distance
     entries_in_period = FuelEntry.query.filter(
            FuelEntry.motorcycle_id == motorcycle_id,
            FuelEntry.total_distance > first_entry_dist, # 最初の満タン記録より後
            FuelEntry.total_distance <= last_entry_dist # 最後の満タン記録まで
     ).all()
     total_fuel_consumed = sum(entry.fuel_volume for entry in entries_in_period if entry.fuel_volume is not None)

     if total_fuel_consumed > 0 and total_distance_traveled > 0:
         return round(total_distance_traveled / total_fuel_consumed, 2)
     return None

def get_upcoming_reminders(user_motorcycles, user_id):
    """ユーザーの車両に関連する警告リマインダーを取得"""
    upcoming_reminders = []
    today = date.today()
    KM_THRESHOLD_WARNING = current_app.config.get('REMINDER_KM_WARNING', 500); DAYS_THRESHOLD_WARNING = current_app.config.get('REMINDER_DAYS_WARNING', 14)
    KM_THRESHOLD_DANGER = current_app.config.get('REMINDER_KM_DANGER', 0); DAYS_THRESHOLD_DANGER = current_app.config.get('REMINDER_DAYS_DANGER', 0)
    current_distances = { m.id: get_latest_total_distance(m.id, m.odometer_offset) for m in user_motorcycles }
    all_reminders = MaintenanceReminder.query.options(db.joinedload(MaintenanceReminder.motorcycle)).join(Motorcycle).filter(Motorcycle.user_id == user_id).all()
    for reminder in all_reminders:
        motorcycle = reminder.motorcycle; current_km = current_distances.get(motorcycle.id, motorcycle.odometer_offset or 0)
        status = 'ok'; messages = []; due_info_parts = []; is_due = False
        # 距離ベースのリマインダーチェック
        if reminder.interval_km and reminder.last_done_km is not None:
            next_km_due = reminder.last_done_km + reminder.interval_km; remaining_km = next_km_due - current_km
            due_info_parts.append(f"{next_km_due:,} km")
            if remaining_km <= KM_THRESHOLD_DANGER: messages.append(f"距離超過 (現在 {current_km:,} km)"); status = 'danger'; is_due = True
            elif remaining_km <= KM_THRESHOLD_WARNING: messages.append(f"あと {remaining_km:,} km"); status = 'warning'; is_due = True
        # 期間ベースのリマインダーチェック
        if reminder.interval_months and reminder.last_done_date:
            try:
                next_date_due = reminder.last_done_date + relativedelta(months=reminder.interval_months); remaining_days = (next_date_due - today).days
                due_info_parts.append(f"{next_date_due.strftime('%Y-%m-%d')}")
                period_status = 'ok'; period_message = ''
                if remaining_days <= DAYS_THRESHOLD_DANGER: period_status = 'danger'; period_message = f"期限超過"
                elif remaining_days <= DAYS_THRESHOLD_WARNING: period_status = 'warning'; period_message = f"あと {remaining_days} 日"
                if period_status != 'ok':
                    is_due = True; messages.append(period_message)
                    # ステータスを更新 (danger > warning > ok)
                    if (period_status == 'danger') or (period_status == 'warning' and status != 'danger'): status = period_status
            except Exception as e: current_app.logger.error(f"Error calculating date reminder {reminder.id}: {e}"); messages.append("日付計算エラー"); status = 'warning'; is_due = True

        # 期限切れまたは警告期間の場合に追加
        if is_due:
            last_done_str = "未実施"
            if reminder.last_done_date: last_done_str = reminder.last_done_date.strftime('%Y-%m-%d');
            if reminder.last_done_km is not None: last_done_str += f" ({reminder.last_done_km:,} km)" if reminder.last_done_date else f"{reminder.last_done_km:,} km"
            upcoming_reminders.append({
                'reminder_id': reminder.id,
                'motorcycle_id': motorcycle.id,
                'motorcycle_name': motorcycle.name,
                'task': reminder.task_description,
                'status': status,
                'message': ", ".join(messages) if messages else "要確認",
                'due_info': " / ".join(due_info_parts) if due_info_parts else '未設定', # 目安情報
                'last_done': last_done_str # 最終実施情報
            })
    # ステータスでソート (danger > warning > ok)
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
    user_motorcycles = Motorcycle.query.filter_by(user_id=g.user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles:
        flash('ようこそ！最初に利用する車両を登録してください。', 'info'); return redirect(url_for('vehicle.add_vehicle'))
    user_motorcycle_ids = [m.id for m in user_motorcycles]

    # --- フィルター用車両ID取得 (変更なし) ---
    selected_fuel_vehicle_id_str = request.args.get('fuel_vehicle_id')
    selected_maint_vehicle_id_str = request.args.get('maint_vehicle_id')
    selected_stats_vehicle_id_str = request.args.get('stats_vehicle_id')

    selected_fuel_vehicle_id = None
    if selected_fuel_vehicle_id_str:
        try:
            temp_id = int(selected_fuel_vehicle_id_str)
            if temp_id in user_motorcycle_ids: selected_fuel_vehicle_id = temp_id
        except ValueError: pass

    selected_maint_vehicle_id = None
    if selected_maint_vehicle_id_str:
        try:
            temp_id = int(selected_maint_vehicle_id_str)
            if temp_id in user_motorcycle_ids: selected_maint_vehicle_id = temp_id
        except ValueError: pass

    selected_stats_vehicle_id = None
    target_vehicle_for_stats = None
    if selected_stats_vehicle_id_str:
        try:
            temp_id = int(selected_stats_vehicle_id_str)
            if temp_id in user_motorcycle_ids:
                selected_stats_vehicle_id = temp_id
                target_vehicle_for_stats = next((m for m in user_motorcycles if m.id == selected_stats_vehicle_id), None)
        except ValueError: pass

    # --- 直近の記録 (変更なし) ---
    fuel_query = FuelEntry.query.options(db.joinedload(FuelEntry.motorcycle)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids)) # motorcycleをプリロード
    if selected_fuel_vehicle_id:
        fuel_query = fuel_query.filter(FuelEntry.motorcycle_id == selected_fuel_vehicle_id)
    recent_fuel_entries = fuel_query.order_by(FuelEntry.entry_date.desc(), FuelEntry.total_distance.desc()).limit(5).all()

    maint_query = MaintenanceEntry.query.options(db.joinedload(MaintenanceEntry.motorcycle)).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids)) # motorcycleをプリロード
    if selected_maint_vehicle_id:
        maint_query = maint_query.filter(MaintenanceEntry.motorcycle_id == selected_maint_vehicle_id)
    recent_maintenance_entries = maint_query.order_by(MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.total_distance_at_maintenance.desc()).limit(5).all()

    # --- リマインダー通知取得 (変更なし) ---
    upcoming_reminders = get_upcoming_reminders(user_motorcycles, g.user.id)

    # --- 平均燃費計算 (変更なし) ---
    for m in user_motorcycles:
        m._average_kpl = calculate_average_kpl(m.id)

    # --- 統計情報サマリー計算 (変更なし) ---
    dashboard_stats = {
        'vehicle_name': None,
        'total_distance': 0,
        'average_kpl': None,
        'total_fuel_cost': 0,
        'total_maint_cost': 0,
        'is_specific_vehicle': False,
        'vehicle_name_for_cost': None # コスト用の車両名ラベル
    }
    if target_vehicle_for_stats:
        dashboard_stats['vehicle_name'] = target_vehicle_for_stats.name
        dashboard_stats['total_distance'] = get_latest_total_distance(target_vehicle_for_stats.id, target_vehicle_for_stats.odometer_offset)
        dashboard_stats['average_kpl'] = target_vehicle_for_stats._average_kpl
        fuel_cost_q = db.session.query(func.sum(FuelEntry.total_cost)).filter(FuelEntry.motorcycle_id == target_vehicle_for_stats.id).scalar()
        dashboard_stats['total_fuel_cost'] = fuel_cost_q or 0
        maint_cost_q = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))).filter(MaintenanceEntry.motorcycle_id == target_vehicle_for_stats.id).scalar()
        dashboard_stats['total_maint_cost'] = maint_cost_q or 0
        dashboard_stats['is_specific_vehicle'] = True
        dashboard_stats['vehicle_name_for_cost'] = target_vehicle_for_stats.name # コスト用ラベルも特定車両名
    else:
        default_vehicle = next((m for m in user_motorcycles if m.is_default), user_motorcycles[0] if user_motorcycles else None)
        if default_vehicle:
            dashboard_stats['vehicle_name'] = f"デフォルト ({default_vehicle.name})"
            dashboard_stats['total_distance'] = get_latest_total_distance(default_vehicle.id, default_vehicle.odometer_offset)
            dashboard_stats['average_kpl'] = default_vehicle._average_kpl
        else:
             dashboard_stats['vehicle_name'] = "車両未登録"
        # 全車両のコスト合計
        total_fuel_cost_query = db.session.query(func.sum(FuelEntry.total_cost)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids)).scalar()
        dashboard_stats['total_fuel_cost'] = total_fuel_cost_query or 0
        total_maint_cost_query = db.session.query(func.sum(func.coalesce(MaintenanceEntry.parts_cost, 0) + func.coalesce(MaintenanceEntry.labor_cost, 0))).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids)).scalar()
        dashboard_stats['total_maint_cost'] = total_maint_cost_query or 0
        dashboard_stats['is_specific_vehicle'] = False
        dashboard_stats['vehicle_name_for_cost'] = "すべての車両" # コスト用ラベルは「すべての車両」

    # <<< 祝日データを日付:祝日名の辞書で取得 (変更なし) >>>
    holidays_json = '{}' # デフォルトは空のオブジェクト '{}'
    try:
        today = date.today()
        years_to_fetch = [today.year - 1, today.year, today.year + 1]
        holidays_dict = {}
        for year in years_to_fetch:
            try:
                holidays_raw = jpholiday.year_holidays(year)
                for holiday_date, holiday_name in holidays_raw:
                    holidays_dict[holiday_date.strftime('%Y-%m-%d')] = holiday_name
            except Exception as e:
                 current_app.logger.error(f"Error fetching holidays for year {year}: {e}")
        holidays_json = json.dumps(holidays_dict)
    except Exception as e:
        current_app.logger.error(f"Error processing holidays data: {e}")
        flash('祝日情報の取得または処理中にエラーが発生しました。', 'warning')
    # <<< 祝日データ取得ここまで >>>

    # --- テンプレートへのデータ渡し ---
    return render_template(
        'dashboard.html',
        motorcycles=user_motorcycles,
        recent_fuel_entries=recent_fuel_entries,
        recent_maintenance_entries=recent_maintenance_entries,
        upcoming_reminders=upcoming_reminders,
        selected_fuel_vehicle_id=selected_fuel_vehicle_id,
        selected_maint_vehicle_id=selected_maint_vehicle_id,
        selected_stats_vehicle_id=selected_stats_vehicle_id,
        dashboard_stats=dashboard_stats,
        holidays_json=holidays_json # <<< 祝日辞書のJSONを渡す >>>
    )

# --- APIエンドポイント (ノート処理部分を修正) ---
@main_bp.route('/api/dashboard/events')
@login_required_custom
def dashboard_events_api():
    events = []
    if not g.user: return jsonify({'error': 'User not logged in'}), 401
    user_id = g.user.id
    user_motorcycle_ids = [m.id for m in Motorcycle.query.filter_by(user_id=user_id).all()]

    # --- ▼▼▼ 給油記録 (editUrl 追加) ▼▼▼ ---
    # options(db.joinedload(...)) で N+1 問題を軽減
    fuel_entries = FuelEntry.query.options(db.joinedload(FuelEntry.motorcycle)).filter(FuelEntry.motorcycle_id.in_(user_motorcycle_ids)).all()
    for entry in fuel_entries:
        kpl = entry.km_per_liter
        # 燃費が計算可能な場合のみ表示文字列を生成
        kpl_display = f"{kpl:.2f} km/L" if kpl is not None else None
        edit_url = url_for('fuel.edit_fuel', entry_id=entry.id) # 編集URL
        events.append({
            'id': f'fuel-{entry.id}',
            'title': f"⛽ 給油: {entry.motorcycle.name}", # プリロードされた motorcycle を使用
            'start': entry.entry_date.isoformat(),
            'allDay': True,
            'url': edit_url,
            'backgroundColor': '#198754',
            'borderColor': '#198754',
            'textColor': 'white',
            'extendedProps': {
                'type': 'fuel',
                'motorcycleName': entry.motorcycle.name, # プリロードされた motorcycle を使用
                'odometer': entry.odometer_reading,
                'fuelVolume': entry.fuel_volume,
                'kmPerLiter': kpl_display, # 計算結果または None
                'totalCost': math.ceil(entry.total_cost) if entry.total_cost is not None else None,
                'stationName': entry.station_name,
                'notes': entry.notes,
                'editUrl': edit_url # 編集URL
            }
        })
    # --- ▲▲▲ 給油記録ここまで ▲▲▲ ---

    # --- ▼▼▼ 整備記録 (editUrl 追加) ▼▼▼ ---
    # options(db.joinedload(...)) で N+1 問題を軽減
    maintenance_entries = MaintenanceEntry.query.options(db.joinedload(MaintenanceEntry.motorcycle)).filter(MaintenanceEntry.motorcycle_id.in_(user_motorcycle_ids)).all()
    for entry in maintenance_entries:
        event_title_base = entry.category if entry.category else entry.description
        # タイトルが長すぎる場合は省略
        event_title = f"🔧 整備: {event_title_base[:15]}" + ("..." if len(event_title_base) > 15 else "")
        total_cost = entry.total_cost
        edit_url = url_for('maintenance.edit_maintenance', entry_id=entry.id) # 編集URL
        events.append({
            'id': f'maint-{entry.id}',
            'title': event_title,
            'start': entry.maintenance_date.isoformat(),
            'allDay': True,
            'url': edit_url,
            'backgroundColor': '#ffc107',
            'borderColor': '#ffc107',
            'textColor': 'black',
            'extendedProps': {
                'type': 'maintenance',
                'motorcycleName': entry.motorcycle.name, # プリロードされた motorcycle を使用
                'odometer': entry.total_distance_at_maintenance,
                'description': entry.description,
                'category': entry.category,
                'totalCost': math.ceil(total_cost) if total_cost is not None else None,
                'location': entry.location,
                'notes': entry.notes,
                'editUrl': edit_url # 編集URL
            }
        })
    # --- ▲▲▲ 整備記録ここまで ▲▲▲ ---

    # --- ▼▼▼ 一般ノート (ここを修正) ▼▼▼ ---
    # options(db.joinedload(...)) で N+1 問題を軽減
    general_notes = GeneralNote.query.options(db.joinedload(GeneralNote.motorcycle)).filter_by(user_id=user_id).all()
    for note in general_notes:
        motorcycle_name = note.motorcycle.name if note.motorcycle else None
        # タイトルがない場合はカテゴリ名を表示
        note_title_display = note.title or ('タスク' if note.category == 'task' else 'メモ')

        # カテゴリに基づいてアイコンとタイトル接頭辞、イベントタイプを設定
        if note.category == 'task':
            icon = "✅" # チェックマークアイコン
            title_prefix = f"{icon} タスク: "
            event_type = 'task'
        else: # 'note' or other (デフォルトはノート扱い)
            icon = "📝" # メモアイコン
            title_prefix = f"{icon} メモ: "
            event_type = 'note'

        # タイトルが長すぎる場合は省略
        event_title = title_prefix + note_title_display[:15] + ("..." if len(note_title_display) > 15 else "")
        edit_url = url_for('notes.edit_note', note_id=note.id) # 編集URL

        # extendedProps を構築
        extended_props = {
            'type': event_type, # 'note' または 'task'
            'category': note.category, # カテゴリ ('note' or 'task')
            'title': note.title, # 元のタイトル (None の可能性あり)
            'motorcycleName': motorcycle_name, # 関連車両名 (None の可能性あり)
            'noteDate': note.note_date.strftime('%Y-%m-%d'), # ノートの日付
            'createdAt': note.created_at.strftime('%Y-%m-%d %H:%M'), # 作成日時
            'updatedAt': note.updated_at.strftime('%Y-%m-%d %H:%M'), # 更新日時
            'editUrl': edit_url # 編集URL
        }
        # タイプに応じて content または todos を追加
        if event_type == 'task':
            # todos が None の場合は空リスト [] を設定
            extended_props['todos'] = note.todos if note.todos is not None else []
        else:
            extended_props['content'] = note.content

        events.append({
            'id': f'note-{note.id}',
            'title': event_title, # アイコン付きタイトル
            'start': note.note_date.isoformat(), # ノートの日付をイベント日付に
            'allDay': True,
            'url': edit_url, # クリック時の遷移先 (フォールバック用)
            # 色はノートもタスクも同じ灰色
            'backgroundColor': '#6c757d',
            'borderColor': '#6c757d',
            'textColor': 'white',
            'extendedProps': extended_props # 更新された extendedProps
        })
    # --- ▲▲▲ 一般ノートここまで ▲▲▲ ---

    return jsonify(events)

# --- プライバシーポリシーページ ---
@main_bp.route('/privacy')
def privacy_policy():
    """プライバシーポリシーページを表示します。"""
    return render_template('privacy_policy.html')

@main_bp.route('/terms')
def terms_of_service():
    """利用規約ページを表示します。"""
    return render_template('terms_of_service.html')
