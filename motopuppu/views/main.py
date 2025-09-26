# motopuppu/views/main.py
from flask import (
    Blueprint, render_template, redirect, url_for, g, flash,
    current_app, jsonify, request
)
from datetime import date, timedelta, datetime
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo
from ..models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, GeneralNote, ActivityLog
from sqlalchemy.orm import joinedload
from sqlalchemy import func
import math
import os
import json

from .. import services
# ▼▼▼ Flask-Login関連のインポートに切り替え ▼▼▼
from flask_login import login_required, current_user
# ▲▲▲ 変更ここまで ▲▲▲
from ..utils.lap_time_utils import format_seconds_to_time


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
    # ▼▼▼ g.userをcurrent_userに置き換え ▼▼▼
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    # ▲▲▲ 変更ここまで ▲▲▲

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
@login_required  # ▼▼▼ デコレータを@login_requiredに変更 ▼▼▼
def dashboard():
    # 1. リクエストの解析と基本データの準備
    period, start_date, end_date = parse_period_from_request(request)

    user_motorcycles_all = Motorcycle.query.filter_by(user_id=current_user.id).order_by(
        Motorcycle.is_default.desc(), Motorcycle.name).all()

    start_initial_tutorial = False
    if not current_user.completed_tutorials.get('initial_setup') and not user_motorcycles_all:
        start_initial_tutorial = True
    elif not user_motorcycles_all:
        flash('ようこそ！最初に利用する車両を登録してください。', 'info')
        return redirect(url_for('vehicle.add_vehicle'))

    # ▼▼▼【ここから変更】ダッシュボードツアー開始の判定を追加 ▼▼▼
    show_dashboard_tour = request.args.get('tutorial_completed') == '1' and not current_user.completed_tutorials.get('dashboard_tour')
    # ▲▲▲【変更はここまで】▲▲▲


    motorcycles_public = [m for m in user_motorcycles_all if not m.is_racer]
    user_motorcycle_ids_public = [m.id for m in motorcycles_public]
    
    selected_stats_vehicle_id = request.args.get('stats_vehicle_id', type=int)

    selected_timeline_vehicle_id = request.args.get('timeline_vehicle_id', 'all')
    
    timeline_target_ids = []
    if selected_timeline_vehicle_id == 'all':
        timeline_target_ids = user_motorcycle_ids_public
    else:
        try:
            vehicle_id_int = int(selected_timeline_vehicle_id)
            if vehicle_id_int in [m.id for m in motorcycles_public]:
                timeline_target_ids = [vehicle_id_int]
            else:
                flash('不正な車両が指定されました。', 'danger')
                selected_timeline_vehicle_id = 'all'
                timeline_target_ids = user_motorcycle_ids_public
        except (ValueError, TypeError):
            flash('不正な車両IDが指定されました。', 'danger')
            selected_timeline_vehicle_id = 'all'
            timeline_target_ids = user_motorcycle_ids_public

    # 2. サービスを呼び出してビジネスロジックを実行
    dashboard_layout = current_user.dashboard_layout
    if not dashboard_layout:
        dashboard_layout = ['reminders', 'stats', 'vehicles', 'timeline', 'calendar']

    upcoming_reminders = services.get_upcoming_reminders(user_motorcycles_all, current_user.id)

    target_vehicle_for_stats = next((m for m in user_motorcycles_all if m.id == selected_stats_vehicle_id), None)
    
    dashboard_stats = services.get_dashboard_stats(
        user_motorcycles_all=user_motorcycles_all,
        user_motorcycle_ids_public=user_motorcycle_ids_public,
        target_vehicle_for_stats=target_vehicle_for_stats,
        start_date=start_date,
        end_date=end_date,
        show_cost=current_user.show_cost_in_dashboard
    )

    timeline_events = services.get_timeline_events(
        motorcycle_ids=timeline_target_ids,
        start_date=start_date,
        end_date=end_date
    )

    holidays_json = services.get_holidays_json()
    if holidays_json == '{}':
        flash('祝日情報の取得または処理中にエラーが発生しました。', 'warning')

    circuit_stats = services.get_circuit_activity_for_dashboard(current_user.id)

    # 4. テンプレートをレンダリング
    return render_template(
        'dashboard.html',
        motorcycles=user_motorcycles_all,
        motorcycles_public=motorcycles_public,
        upcoming_reminders=upcoming_reminders,
        timeline_events=timeline_events,
        selected_timeline_vehicle_id=selected_timeline_vehicle_id,
        selected_stats_vehicle_id=selected_stats_vehicle_id,
        dashboard_stats=dashboard_stats,
        holidays_json=holidays_json,
        period=period,
        start_date_str=request.args.get('start_date', ''),
        end_date_str=request.args.get('end_date', ''),
        current_date_str=datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat(),
        dashboard_layout=dashboard_layout,
        circuit_stats=circuit_stats,
        format_seconds_to_time=format_seconds_to_time,
        start_initial_tutorial=start_initial_tutorial,
        show_dashboard_tour=show_dashboard_tour # ◀◀◀ テンプレートにフラグを渡す
    )


@main_bp.route('/api/dashboard/events')
@login_required
def dashboard_events_api():
    if not current_user.is_authenticated:
        return jsonify({'error': 'User not logged in'}), 401
    
    calendar_events = services.get_calendar_events_for_user(current_user)
    
    return jsonify(calendar_events)


@main_bp.route('/terms_of_service')
def terms_of_service():
    return render_template('legal/terms_of_service.html', title="利用規約")


@main_bp.route('/privacy_policy')
def privacy_policy():
    return render_template('legal/privacy_policy.html', title="プライバシーポリシー")


@main_bp.route('/misskey_redirect/<note_id>')
@login_required
def misskey_redirect(note_id):
    """Misskeyのノートへリダイレクトする"""
    misskey_instance_url = current_app.config.get('MISSKEY_INSTANCE_URL', 'https://misskey.io')
    return redirect(f"{misskey_instance_url}/notes/{note_id}")


@main_bp.route('/dashboard/toggle-cost-display', methods=['POST'])
@login_required
def toggle_dashboard_cost_display():
    """ダッシュボードのコスト表示設定を切り替える"""
    try:
        current_user.show_cost_in_dashboard = not current_user.show_cost_in_dashboard
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': 'Display setting updated.',
            'show_cost': current_user.show_cost_in_dashboard
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error toggling cost display for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Could not update setting'}), 500


@main_bp.route('/dashboard/save_layout', methods=['POST'])
@login_required
def save_dashboard_layout():
    """ダッシュボードのウィジェットの並び順を保存する"""
    new_layout = request.json.get('layout')

    if not isinstance(new_layout, list) or not all(isinstance(item, str) for item in new_layout):
        return jsonify({'status': 'error', 'message': 'Invalid layout data'}), 400

    try:
        current_user.dashboard_layout = new_layout
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Layout saved successfully'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error saving dashboard layout for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Could not save layout to the database'}), 500


@main_bp.route('/api/tutorial/complete', methods=['POST'])
@login_required
def complete_tutorial():
    """指定されたキーのチュートリアルを完了としてマークするAPI"""
    data = request.get_json()
    tutorial_key = data.get('key')

    if not tutorial_key:
        return jsonify({'status': 'error', 'message': 'Tutorial key is missing.'}), 400

    try:
        from sqlalchemy.orm.attributes import flag_modified
        
        completed = current_user.completed_tutorials or {}
        
        if completed.get(tutorial_key) is not True:
            completed[tutorial_key] = True
            
            current_user.completed_tutorials = completed
            flag_modified(current_user, "completed_tutorials")
            
            db.session.add(current_user)
            db.session.commit()
            
        return jsonify({'status': 'success', 'message': f"Tutorial '{tutorial_key}' marked as complete."})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error completing tutorial '{tutorial_key}' for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Could not update tutorial status.'}), 500