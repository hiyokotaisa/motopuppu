# motopuppu/views/main.py
from flask import (
    Blueprint, render_template, redirect, url_for, session, g, flash,
    current_app, jsonify, request
)
# datetime をインポートリストに追加
from datetime import date, timedelta, datetime
from dateutil.relativedelta import relativedelta
# zoneinfoを追加
from zoneinfo import ZoneInfo
from .auth import login_required_custom, get_current_user  # get_current_user はここでインポート
from ..models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, GeneralNote
from sqlalchemy.orm import joinedload
import math
import jpholiday  # 祝日ライブラリ
import json  # JSONライブラリ
import os  # os をインポート (お知らせファイルパス用)

# servicesモジュールをインポート
from .. import services

main_bp = Blueprint('main', __name__)

# --- ヘルパー関数 ---

def parse_period_from_request(req):
    """リクエストから期間パラメータを解析し、開始日と終了日のオブジェクトを返す"""
    period = req.args.get('period', 'all')
    custom_start_date_str = req.args.get('start_date', '')
    custom_end_date_str = req.args.get('end_date', '')

    end_date_obj = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    start_date_obj = None

    try:
        if period == '1m':
            start_date_obj = end_date_obj - relativedelta(months=1)
        elif period == '6m':
            start_date_obj = end_date_obj - relativedelta(months=6)
        elif period == '1y':
            start_date_obj = end_date_obj - relativedelta(years=1)
        elif period == 'custom' and custom_start_date_str and custom_end_date_str:
            start_date_obj = date.fromisoformat(custom_start_date_str)
            end_date_obj = date.fromisoformat(custom_end_date_str)
            if start_date_obj > end_date_obj:
                flash('開始日は終了日より前の日付を選択してください。', 'warning')
                # 日付を入れ替えて処理を継続
                start_date_obj, end_date_obj = end_date_obj, start_date_obj
    except (ValueError, TypeError):
        flash('無効な日付形式です。YYYY-MM-DD形式で入力してください。', 'danger')
        period = 'all'  # エラー時は全期間表示に戻す
        start_date_obj = None
        end_date_obj = datetime.now(ZoneInfo("Asia/Tokyo")).date()

    if start_date_obj:
        # betweenで使いやすくするため、終了日を1日進める
        end_date_obj = end_date_obj + timedelta(days=1)

    return period, start_date_obj, end_date_obj


# --- ルート定義 ---
@main_bp.route('/')
def index():
    if hasattr(g, 'user') and g.user:
        return redirect(url_for('main.dashboard'))

    announcements_for_modal = []
    important_notice_content = None
    try:
        announcement_file = os.path.join(
            current_app.root_path, '..', 'announcements.json')
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

            temp_modal_announcements.sort(
                key=lambda x: x.get('id', 0), reverse=True)
            announcements_for_modal = temp_modal_announcements
        else:
            current_app.logger.warning(
                f"announcements.json not found at {announcement_file}")
    except Exception as e:
        current_app.logger.error(
            f"An unexpected error occurred loading announcements: {e}", exc_info=True)

    return render_template('index.html', announcements=announcements_for_modal, important_notice=important_notice_content)


@main_bp.route('/dashboard')
@login_required_custom
def dashboard():
    # 1. リクエストの解析と基本データの準備
    period, start_date, end_date = parse_period_from_request(request)

    user_motorcycles_all = Motorcycle.query.filter_by(user_id=g.user.id).order_by(
        Motorcycle.is_default.desc(), Motorcycle.name).all()
    if not user_motorcycles_all:
        flash('ようこそ！最初に利用する車両を登録してください。', 'info')
        return redirect(url_for('vehicle.add_vehicle'))

    user_motorcycle_ids_all = [m.id for m in user_motorcycles_all]
    user_motorcycles_public = [m for m in user_motorcycles_all if not m.is_racer]
    user_motorcycle_ids_public = [m.id for m in user_motorcycles_public]

    selected_fuel_vehicle_id = request.args.get('fuel_vehicle_id', type=int)
    selected_maint_vehicle_id = request.args.get('maint_vehicle_id', type=int)
    selected_stats_vehicle_id = request.args.get('stats_vehicle_id', type=int)

    # 2. サービスを呼び出してビジネスロジックを実行
    upcoming_reminders = services.get_upcoming_reminders(user_motorcycles_all, g.user.id)

    # 燃費は全期間で計算するため、事前に各車両オブジェクトにセットしておく
    for m in user_motorcycles_all:
        m._average_kpl = services.calculate_average_kpl(m)

    target_vehicle_for_stats = next((m for m in user_motorcycles_all if m.id == selected_stats_vehicle_id), None)
    dashboard_stats = services.get_dashboard_stats(
        user_motorcycles_all=user_motorcycles_all,
        user_motorcycle_ids_public=user_motorcycle_ids_public,
        target_vehicle_for_stats=target_vehicle_for_stats,
        start_date=start_date,
        end_date=end_date
    )

    recent_fuel_entries = services.get_recent_logs(
        model=FuelEntry,
        vehicle_ids=user_motorcycle_ids_public,
        selected_vehicle_id=selected_fuel_vehicle_id,
        start_date=start_date, end_date=end_date,
        order_by_cols=[FuelEntry.entry_date.desc(), FuelEntry.total_distance.desc()]
    )
    
    # --- ▼▼▼ 変更点 ▼▼▼ ---
    # `services.get_recent_logs` に extra_filters を渡すように変更
    recent_maintenance_entries = services.get_recent_logs(
        model=MaintenanceEntry,
        vehicle_ids=user_motorcycle_ids_public,
        selected_vehicle_id=selected_maint_vehicle_id,
        start_date=start_date, end_date=end_date,
        order_by_cols=[MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.total_distance_at_maintenance.desc()],
        extra_filters=[MaintenanceEntry.category != '初期設定']
    )
    # --- ▲▲▲ 変更点 ▲▲▲ ---

    # 3. テンプレート表示用のその他のデータ準備
    holidays_json = '{}'
    try:
        today_for_holiday = date.today()
        years_to_fetch = [today_for_holiday.year - 1,
                          today_for_holiday.year, today_for_holiday.year + 1]
        holidays_dict = {}
        for year in years_to_fetch:
            try:
                holidays_raw = jpholiday.year_holidays(year)
                for holiday_date_obj, holiday_name in holidays_raw:
                    holidays_dict[holiday_date_obj.strftime(
                        '%Y-%m-%d')] = holiday_name
            except Exception as e:
                current_app.logger.error(
                    f"Error fetching holidays for year {year}: {e}")
        holidays_json = json.dumps(holidays_dict)
    except Exception as e:
        current_app.logger.error(f"Error processing holidays data: {e}")
        flash('祝日情報の取得または処理中にエラーが発生しました。', 'warning')

    # 4. テンプレートをレンダリング
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
        holidays_json=holidays_json,
        period=period,
        start_date_str=request.args.get('start_date', ''),
        end_date_str=request.args.get('end_date', ''),
        current_date_str=datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    )


@main_bp.route('/api/dashboard/events')
@login_required_custom
def dashboard_events_api():
    # このAPIはカレンダー用で全期間表示のため、期間フィルターは適用しない
    events = []
    if not g.user:
        return jsonify({'error': 'User not logged in'}), 401
    user_id = g.user.id
    user_motorcycle_ids_public = [m.id for m in Motorcycle.query.filter_by(
        user_id=user_id, is_racer=False).all()]

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
            'updatedAt': note.updated_at.strftime('%Y-%m-%d %H:%M'), 'editUrl': edit_url
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