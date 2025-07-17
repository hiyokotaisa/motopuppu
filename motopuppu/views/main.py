# motopuppu/views/main.py
from flask import (
    Blueprint, render_template, redirect, url_for, session, g, flash,
    current_app, jsonify, request
)
from datetime import date, timedelta, datetime
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo
from ..models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, GeneralNote, ActivityLog
from sqlalchemy.orm import joinedload
import math
import os
import json

from .. import services
from .auth import login_required_custom, get_current_user


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
                start_date_obj, end_date_obj = end_date_obj, start_date_obj
    except (ValueError, TypeError):
        flash('無効な日付形式です。YYYY-MM-DD形式で入力してください。', 'danger')
        period = 'all'
        start_date_obj = None
        end_date_obj = datetime.now(ZoneInfo("Asia/Tokyo")).date()

    if start_date_obj:
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

    user_motorcycle_ids_public = [m.id for m in user_motorcycles_all if not m.is_racer]
    selected_fuel_vehicle_id = request.args.get('fuel_vehicle_id', type=int)
    selected_maint_vehicle_id = request.args.get('maint_vehicle_id', type=int)
    selected_stats_vehicle_id = request.args.get('stats_vehicle_id', type=int)

    # 2. サービスを呼び出してビジネスロジックを実行
    upcoming_reminders = services.get_upcoming_reminders(user_motorcycles_all, g.user.id)

    for m in user_motorcycles_all:
        if not m.is_racer:
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
    
    recent_maintenance_entries = services.get_recent_logs(
        model=MaintenanceEntry,
        vehicle_ids=user_motorcycle_ids_public,
        selected_vehicle_id=selected_maint_vehicle_id,
        start_date=start_date, end_date=end_date,
        order_by_cols=[MaintenanceEntry.maintenance_date.desc(), MaintenanceEntry.total_distance_at_maintenance.desc()],
        extra_filters=[MaintenanceEntry.category != '初期設定']
    )

    holidays_json = services.get_holidays_json()
    if holidays_json == '{}':
        flash('祝日情報の取得または処理中にエラーが発生しました。', 'warning')

    # 4. テンプレートをレンダリング
    return render_template(
        'dashboard.html',
        motorcycles=user_motorcycles_all,
        motorcycles_public=[m for m in user_motorcycles_all if not m.is_racer],
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
    if not g.user:
        return jsonify({'error': 'User not logged in'}), 401
    
    calendar_events = services.get_calendar_events_for_user(g.user)
    
    return jsonify(calendar_events)


@main_bp.route('/terms_of_service')
def terms_of_service():
    return render_template('legal/terms_of_service.html', title="利用規約")


@main_bp.route('/privacy_policy')
def privacy_policy():
    return render_template('legal/privacy_policy.html', title="プライバシーポリシー")

# ▼▼▼ 以下をファイルの末尾に追記 ▼▼▼
@main_bp.route('/misskey_redirect/<note_id>')
@login_required_custom
def misskey_redirect(note_id):
    """Misskeyのノートへリダイレクトする"""
    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    return redirect(f"{misskey_instance_url}/notes/{note_id}")
# ▲▲▲ 追記ここまで ▲▲▲

@main_bp.before_app_request
def load_logged_in_user():
    g.user = get_current_user()


@main_bp.app_context_processor
def inject_user():
    return dict(g=g if hasattr(g, 'user') else None)