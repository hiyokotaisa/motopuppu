# motopuppu/views/main.py
from flask import (
    Blueprint, render_template, redirect, url_for, g, flash,
    current_app, jsonify, request
)
from datetime import date, timedelta, datetime, timezone
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo
from ..models import db, User, Motorcycle, FuelEntry, MaintenanceEntry, GeneralNote, ActivityLog, Event, EventParticipant, ParticipationStatus
from sqlalchemy.orm import joinedload
from sqlalchemy import func, or_, and_
import math
import os
import json

from .. import services
from flask_login import login_required, current_user
from ..utils.lap_time_utils import format_seconds_to_time


main_bp = Blueprint('main', __name__)

# --- 定数定義 ---
# 利用可能な全ウィジェットのIDリスト
ALL_AVAILABLE_WIDGETS = [
    'nyanpuppu',
    'reminders',
    'events',
    'stats',
    'vehicles',
    'timeline',
    'circuit',
    'calendar'
]

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
                # HTMXリクエストの場合はフラッシュメッセージを出さないなどの制御も可能だが今回はそのまま
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
    if current_user.is_authenticated:
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
@login_required
def dashboard():
    """
    メインのダッシュボードルート。
    重い処理（統計、車両詳細、タイムライン）はここでは行わず、HTMXによって後から読み込まれる。
    """
    # 1. 基本データの準備 (ナビゲーションバーなどで必要)
    user_motorcycles_all = Motorcycle.query.filter_by(user_id=current_user.id).order_by(
        Motorcycle.is_default.desc(), Motorcycle.name).all()

    start_initial_tutorial = False
    if not current_user.completed_tutorials.get('initial_setup') and not user_motorcycles_all:
        start_initial_tutorial = True
    elif not user_motorcycles_all:
        flash('ようこそ！最初に利用する車両を登録してください。', 'info')
        return redirect(url_for('vehicle.add_vehicle'))

    show_dashboard_tour = request.args.get('tutorial_completed') == '1' and not current_user.completed_tutorials.get('dashboard_tour')

    # 軽いデータのみ取得 (リマインダー、サーキットサマリー、祝日、にゃんぷっぷー)
    upcoming_reminders = services.get_upcoming_reminders(user_motorcycles_all, current_user.id)
    circuit_stats = services.get_circuit_activity_for_dashboard(current_user.id)
    nyanpuppu_advice = services.get_nyanpuppu_advice(current_user, user_motorcycles_all)
    holidays_json = services.get_holidays_json()

    # イベント情報の取得
    now_utc = datetime.now(timezone.utc)
    dashboard_events = Event.query.outerjoin(EventParticipant).filter(
        or_(
            Event.user_id == current_user.id,  # 主催
            and_(
                EventParticipant.user_id == current_user.id,  # 参加者として紐付いている
                EventParticipant.status.in_([ParticipationStatus.ATTENDING, ParticipationStatus.TENTATIVE]) # 参加 or 保留
            )
        ),
        Event.start_datetime >= now_utc
    ).order_by(Event.start_datetime.asc()).distinct().all()

    # --- レイアウト設定 ---
    dashboard_layout = current_user.dashboard_layout
    
    # 初回ユーザーまたはレイアウト未設定の場合のデフォルト
    # ▼▼▼ 修正: Noneの場合のみデフォルト適用（空リスト[]はユーザーの意図として尊重） ▼▼▼
    if dashboard_layout is None:
        dashboard_layout = ALL_AVAILABLE_WIDGETS.copy()
    # ▼▼▼ 修正: 強制的にウィジェットを追加するロジックを削除 ▼▼▼
    
    # 非表示(Inactive)ウィジェットの計算
    # DBにない未知のIDが含まれていた場合のエラー防止のため、ALL_AVAILABLE_WIDGETSに含まれるものだけを扱う
    active_widgets = [w for w in dashboard_layout if w in ALL_AVAILABLE_WIDGETS]
    inactive_widgets = [w for w in ALL_AVAILABLE_WIDGETS if w not in active_widgets]

    # パラメータの維持
    period = request.args.get('period', 'all')
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    
    motorcycles_public = [m for m in user_motorcycles_all if not m.is_racer]

    return render_template(
        'dashboard.html',
        motorcycles=user_motorcycles_all,
        motorcycles_public=motorcycles_public,
        upcoming_reminders=upcoming_reminders,
        dashboard_events=dashboard_events,
        selected_timeline_vehicle_id=request.args.get('timeline_vehicle_id', 'all'),
        selected_stats_vehicle_id=request.args.get('stats_vehicle_id', type=int),
        holidays_json=holidays_json,
        period=period,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        current_date_str=datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat(),
        dashboard_layout=active_widgets, # フィルタ済みのリストを渡す
        inactive_widgets=inactive_widgets,
        circuit_stats=circuit_stats,
        format_seconds_to_time=format_seconds_to_time,
        start_initial_tutorial=start_initial_tutorial,
        show_dashboard_tour=show_dashboard_tour,
        nyanpuppu_advice=nyanpuppu_advice
    )


# ▼▼▼ 統計ウィジェット専用ルート (HTMX用) ▼▼▼
@main_bp.route('/dashboard/widgets/stats')
@login_required
def dashboard_stats_widget():
    period, start_date, end_date = parse_period_from_request(request)
    selected_stats_vehicle_id = request.args.get('stats_vehicle_id', type=int)
    selected_timeline_vehicle_id = request.args.get('timeline_vehicle_id', 'all')

    # 必要なデータを再取得
    user_motorcycles_all = Motorcycle.query.filter_by(user_id=current_user.id).order_by(
        Motorcycle.is_default.desc(), Motorcycle.name).all()
    motorcycles_public = [m for m in user_motorcycles_all if not m.is_racer]
    user_motorcycle_ids_public = [m.id for m in motorcycles_public]

    target_vehicle_for_stats = next((m for m in user_motorcycles_all if m.id == selected_stats_vehicle_id), None)

    # 重い処理: 統計計算
    dashboard_stats = services.get_dashboard_stats(
        user_motorcycles_all=user_motorcycles_all,
        user_motorcycle_ids_public=user_motorcycle_ids_public,
        target_vehicle_for_stats=target_vehicle_for_stats,
        start_date=start_date,
        end_date=end_date,
        show_cost=current_user.show_cost_in_dashboard
    )

    return render_template(
        'dashboard/_stats_widget.html',
        dashboard_stats=dashboard_stats,
        motorcycles=user_motorcycles_all,
        selected_stats_vehicle_id=selected_stats_vehicle_id,
        selected_timeline_vehicle_id=selected_timeline_vehicle_id,
        period=period,
        start_date_str=request.args.get('start_date', ''),
        end_date_str=request.args.get('end_date', ''),
        current_date_str=datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    )


# ▼▼▼ タイムラインウィジェット専用ルート (HTMX用) ▼▼▼
@main_bp.route('/dashboard/widgets/timeline')
@login_required
def dashboard_timeline_widget():
    period, start_date, end_date = parse_period_from_request(request)
    selected_timeline_vehicle_id = request.args.get('timeline_vehicle_id', 'all')
    selected_stats_vehicle_id = request.args.get('stats_vehicle_id', '')

    user_motorcycles_all = Motorcycle.query.filter_by(user_id=current_user.id).order_by(
        Motorcycle.is_default.desc(), Motorcycle.name).all()
    motorcycles_public = [m for m in user_motorcycles_all if not m.is_racer]
    user_motorcycle_ids_public = [m.id for m in motorcycles_public]

    timeline_target_ids = []
    if selected_timeline_vehicle_id == 'all':
        timeline_target_ids = user_motorcycle_ids_public
    else:
        try:
            vehicle_id_int = int(selected_timeline_vehicle_id)
            if vehicle_id_int in user_motorcycle_ids_public:
                timeline_target_ids = [vehicle_id_int]
            else:
                timeline_target_ids = user_motorcycle_ids_public
                selected_timeline_vehicle_id = 'all'
        except (ValueError, TypeError):
            timeline_target_ids = user_motorcycle_ids_public
            selected_timeline_vehicle_id = 'all'

    # 重い処理: タイムライン取得
    timeline_events = services.get_timeline_events(
        motorcycle_ids=timeline_target_ids,
        start_date=start_date,
        end_date=end_date
    )

    return render_template(
        'dashboard/_timeline_widget.html',
        timeline_events=timeline_events,
        motorcycles_public=motorcycles_public,
        selected_timeline_vehicle_id=selected_timeline_vehicle_id,
        selected_stats_vehicle_id=selected_stats_vehicle_id,
        period=period,
        start_date_str=request.args.get('start_date', ''),
        end_date_str=request.args.get('end_date', '')
    )


# ▼▼▼ 車両リストウィジェット専用ルート (HTMX用) ▼▼▼
@main_bp.route('/dashboard/widgets/vehicles')
@login_required
def dashboard_vehicles_widget():
    # ウィジェット表示に必要なデータを再取得
    user_motorcycles_all = Motorcycle.query.filter_by(user_id=current_user.id).order_by(
        Motorcycle.is_default.desc(), Motorcycle.name).all()
    
    # 重い処理: 最新ログ情報の計算
    latest_log_info = services.get_latest_log_info_for_vehicles(user_motorcycles_all)

    return render_template(
        'dashboard/_vehicles_widget.html',
        motorcycles=user_motorcycles_all,
        latest_log_info=latest_log_info
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


@main_bp.route('/api/dashboard/nyanpuppu')
@login_required
def get_nyanpuppu_advice_api():
    """にゃんぷっぷーのアドバイスをJSONで返すAPI"""
    user_motorcycles_all = Motorcycle.query.filter_by(user_id=current_user.id).all()
    advice_data = services.get_nyanpuppu_advice(current_user, user_motorcycles_all)
    
    if advice_data:
        return jsonify(advice_data)
    else:
        return jsonify({'error': 'No advice available'}), 404


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