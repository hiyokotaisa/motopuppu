# motopuppu/views/activity/activity_routes.py
import json
import math
import statistics
from datetime import date
from decimal import Decimal
import uuid

from flask import (
    flash, redirect, render_template, request, url_for, abort, current_app, jsonify
)
from sqlalchemy.orm import joinedload, defer
from sqlalchemy import func

from . import activity_bp
from ...utils.lap_time_utils import calculate_lap_stats, parse_time_to_seconds, _calculate_and_set_best_lap, format_seconds_to_time
from ...constants import SETTING_KEY_MAP

from flask_login import login_required, current_user
from ...models import db, Motorcycle, ActivityLog, SessionLog, SettingSheet, User, TouringLog, TouringSpot, TouringScrapbookEntry 
from ...forms import ActivityLogForm, SessionLogForm, LapTimeImportForm, ActivityLapTimeImportForm
from ... import limiter
from ...utils.search_helpers import escape_like
from ...utils.view_helpers import get_motorcycle_or_404, safe_local_url
from ...utils.activity_helpers import can_view_activity, has_gps_tracks_expression

@activity_bp.route('/')
@login_required
def activity_log():
    """全車両の走行ログとツーリングログを統合して表示する"""
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    vehicle_id_str = request.args.get('vehicle_id')
    keyword = request.args.get('q', '').strip()
    sort_by = request.args.get('sort_by', 'date')
    order = request.args.get('order', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('ACTIVITIES_PER_PAGE', 20)

    # ユーザーの全車両を取得（フィルタ用）
    user_motorcycles = Motorcycle.query.filter_by(user_id=current_user.id).order_by(Motorcycle.is_default.desc(), Motorcycle.name).all()
    user_motorcycle_ids = [m.id for m in user_motorcycles]
    active_motorcycle_ids = [m.id for m in user_motorcycles if not m.is_archived]

    if not user_motorcycles:
        flash('ログを閲覧するには、まず車両を登録してください。', 'info')
        return redirect(url_for('vehicle.add_vehicle'))

    circuit_name = request.args.get('circuit_name', '').strip()
    log_type = 'activity' if circuit_name else request.args.get('log_type', '')

    # --- 1. ActivityLog (走行ログ) のクエリ構築 ---
    activity_query = None
    if not log_type or log_type == 'activity':
        activity_query = db.session.query(ActivityLog).options(
            joinedload(ActivityLog.motorcycle)
        ).filter(ActivityLog.user_id == current_user.id)

    # --- 2. TouringLog (ツーリングログ) のクエリ構築 ---
    touring_query = None
    if not log_type or log_type == 'touring':
        touring_query = db.session.query(TouringLog).options(
            joinedload(TouringLog.motorcycle),
            joinedload(TouringLog.spots),
            joinedload(TouringLog.scrapbook_entries)
        ).filter(TouringLog.user_id == current_user.id)

    # --- 3. フィルタリングの適用 ---
    filter_keys = {'start_date', 'end_date', 'vehicle_id', 'q', 'log_type', 'circuit_name'}
    active_filters = {k: v for k, v in request.args.items() if k in filter_keys and v}
    if circuit_name:
        active_filters['log_type'] = 'activity'
        activity_query = activity_query.filter(ActivityLog.circuit_name == circuit_name)

    try:
        if start_date_str:
            start_date = date.fromisoformat(start_date_str)
            if activity_query: activity_query = activity_query.filter(ActivityLog.activity_date >= start_date)
            if touring_query: touring_query = touring_query.filter(TouringLog.touring_date >= start_date)
        if end_date_str:
            end_date = date.fromisoformat(end_date_str)
            if activity_query: activity_query = activity_query.filter(ActivityLog.activity_date <= end_date)
            if touring_query: touring_query = touring_query.filter(TouringLog.touring_date <= end_date)
    except ValueError:
        flash('日付の形式が無効です。YYYY-MM-DD形式で入力してください。', 'warning')
        active_filters.pop('start_date', None)
        active_filters.pop('end_date', None)

    if vehicle_id_str:
        try:
            vehicle_id = int(vehicle_id_str)
            if vehicle_id in user_motorcycle_ids:
                if activity_query: activity_query = activity_query.filter(ActivityLog.motorcycle_id == vehicle_id)
                if touring_query: touring_query = touring_query.filter(TouringLog.motorcycle_id == vehicle_id)
            else:
                flash('選択された車両は有効ではありません。', 'warning')
                active_filters.pop('vehicle_id', None)
                if activity_query: activity_query = activity_query.filter(ActivityLog.motorcycle_id.in_(active_motorcycle_ids))
                if touring_query: touring_query = touring_query.filter(TouringLog.motorcycle_id.in_(active_motorcycle_ids))
        except ValueError:
            active_filters.pop('vehicle_id', None)
            if activity_query: activity_query = activity_query.filter(ActivityLog.motorcycle_id.in_(active_motorcycle_ids))
            if touring_query: touring_query = touring_query.filter(TouringLog.motorcycle_id.in_(active_motorcycle_ids))
    else:
        if activity_query: activity_query = activity_query.filter(ActivityLog.motorcycle_id.in_(active_motorcycle_ids))
        if touring_query: touring_query = touring_query.filter(TouringLog.motorcycle_id.in_(active_motorcycle_ids))

    if keyword:
        search_term = escape_like(keyword)
        # ActivityLog: タイトル、場所名、メモ、サーキット名
        if activity_query:
            activity_query = activity_query.filter(
                db.or_(
                    ActivityLog.activity_title.ilike(search_term),
                    ActivityLog.location_name.ilike(search_term),
                    ActivityLog.notes.ilike(search_term),
                    ActivityLog.circuit_name.ilike(search_term),
                    ActivityLog.custom_location.ilike(search_term)
                )
            )
        # TouringLog: タイトル、メモ
        if touring_query:
            touring_query = touring_query.filter(
                db.or_(
                    TouringLog.title.ilike(search_term),
                    TouringLog.memo.ilike(search_term)
                )
            )

    # --- 4. データ取得と統合 ---
    activities = activity_query.all() if activity_query else []
    tourings = touring_query.all() if touring_query else []

    combined_logs = []
    
    # ActivityLogのベストラップを一括で取得 (N+1対策)
    if activities:
        activity_ids = [act.id for act in activities]
        best_laps_query = db.session.query(
            SessionLog.activity_log_id,
            db.func.min(SessionLog.best_lap_seconds).label('best_lap')
        ).filter(
            SessionLog.activity_log_id.in_(activity_ids),
            SessionLog.best_lap_seconds.isnot(None)
        ).group_by(SessionLog.activity_log_id).all()
        
        best_laps_map = {row.activity_log_id: row.best_lap for row in best_laps_query}
    else:
        best_laps_map = {}

    # ActivityLogを共通形式に変換
    for act in activities:
        best_lap_str = None
        best_lap_seconds = best_laps_map.get(act.id)
        if best_lap_seconds is not None:
            best_lap_str = format_seconds_to_time(best_lap_seconds)

        combined_logs.append({
            'type': 'activity',
            'obj': act,
            'date': act.activity_date,
            'title': act.activity_title or act.location_name_display or '走行ログ',
            'vehicle': act.motorcycle,
            'details': {
                'location': act.location_name_display,
                'best_lap': best_lap_str,
                'weather': act.weather
            }
        })

    # TouringLogを共通形式に変換
    for tour in tourings:
        combined_logs.append({
            'type': 'touring',
            'obj': tour,
            'date': tour.touring_date,
            'title': tour.title,
            'vehicle': tour.motorcycle,
            'details': {
                'spot_count': len(tour.spots),
                'scrapbook_count': len(tour.scrapbook_entries)
            }
        })

    # --- 5. ソートとページネーション (Python側で処理) ---
    # デフォルトは日付降順
    reverse_sort = True if order == 'desc' else False
    
    if sort_by == 'date':
        combined_logs.sort(key=lambda x: x['date'], reverse=reverse_sort)
    elif sort_by == 'vehicle':
        combined_logs.sort(key=lambda x: x['vehicle'].name, reverse=reverse_sort)
    
    # 統計情報の計算
    summary_stats = {
        'total_count': len(combined_logs),
        'activity_count': len(activities),
        'touring_count': len(tourings)
    }

    # ページネーション
    total_items = len(combined_logs)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_logs = combined_logs[start_idx:end_idx]

    # 簡易的なページネーションオブジェクトを作成（テンプレート互換用）
    from ...utils.pagination import SimplePagination
    pagination = SimplePagination(page, per_page, total_items, paginated_logs)

    def activity_filter_url(**changes):
        params = dict(active_filters, sort_by=sort_by, order=order)
        if 'log_type' in changes and changes['log_type'] != 'activity':
            params.pop('circuit_name', None)
        params.update(changes)
        return url_for('activity.activity_log', **{key: value for key, value in params.items() if value})

    circuit_names = [row[0] for row in db.session.query(ActivityLog.circuit_name).filter(
        ActivityLog.user_id == current_user.id,
        ActivityLog.circuit_name.isnot(None), ActivityLog.circuit_name != '',
    ).distinct().order_by(ActivityLog.circuit_name).all()]
    list_url = url_for('activity.activity_log', page=page, sort_by=sort_by, order=order, **active_filters)

    is_filter_active = bool(active_filters)

    template_name = 'beta/activity_log_beta.html' if current_user.use_beta_ui else 'activity/activity_log.html'

    return render_template(template_name,
                           logs=paginated_logs,
                           activity_filter_url=activity_filter_url,
                           current_list_url=list_url,
                           circuit_names=circuit_names,
                           pagination=pagination,
                           motorcycles=user_motorcycles,
                           request_args=active_filters,
                           current_sort_by=sort_by,
                           current_order=order,
                           is_filter_active=is_filter_active,
                           summary_stats=summary_stats)


@activity_bp.route('/<int:vehicle_id>')
@login_required
def list_activities(vehicle_id):
    """指定された車両の活動ログ一覧を表示する"""
    motorcycle = get_motorcycle_or_404(vehicle_id)

    # Beta UIユーザーは走行ログ+ツーリングログの統合画面へ
    if current_user.use_beta_ui:
        return redirect(url_for('activity.activity_log', vehicle_id=motorcycle.id))

    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('ACTIVITIES_PER_PAGE', 10)
    
    best_lap_subquery = db.session.query(
        SessionLog.activity_log_id,
        func.min(SessionLog.best_lap_seconds).label('overall_best_lap_seconds')
    ).filter(SessionLog.best_lap_seconds.isnot(None)).group_by(SessionLog.activity_log_id).subquery()

    query = db.session.query(
            ActivityLog, 
            best_lap_subquery.c.overall_best_lap_seconds
        ).outerjoin(
            best_lap_subquery, ActivityLog.id == best_lap_subquery.c.activity_log_id
        ).filter(
            ActivityLog.motorcycle_id == motorcycle.id
        ).order_by(
            ActivityLog.activity_date.desc()
        )
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    activities_for_template = []
    for activity, best_lap_seconds in pagination.items:
        formatted_lap = format_seconds_to_time(best_lap_seconds) if best_lap_seconds else ''
        activities_for_template.append({
            'activity': activity, 
            'best_lap_formatted': formatted_lap
        })
    
    return render_template('activity/list_activities.html',
                           motorcycle=motorcycle,
                           activities=activities_for_template,
                           pagination=pagination)

@activity_bp.route('/<int:vehicle_id>/add', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required
def add_activity(vehicle_id):
    """新しい活動ログを作成する"""
    motorcycle = get_motorcycle_or_404(vehicle_id)
    event_id = request.form.get('event_id', type=int) if request.method == 'POST' else request.args.get('event_id', type=int)

    form = ActivityLogForm(request.form)
    
    user_motorcycles = Motorcycle.query.filter_by(user_id=current_user.id).order_by(Motorcycle.name).all()
    form.motorcycle_id.choices = [(m.id, f"{m.name} (アーカイブ)" if m.is_archived else m.name) for m in user_motorcycles]

    if request.method == 'POST':
        form.motorcycle_id.data = vehicle_id
        if form.validate_on_submit():
            new_activity = ActivityLog(
                motorcycle_id=vehicle_id, 
                user_id=current_user.id,
                event_id=event_id,
                activity_date=form.activity_date.data,
                activity_title=form.activity_title.data,
                location_type=form.location_type.data,
                circuit_name=form.circuit_name.data if form.location_type.data == 'circuit' else None,
                custom_location=form.custom_location.data if form.location_type.data == 'custom' else None,
                weather=form.weather.data,
                temperature=form.temperature.data,
                notes=form.notes.data
            )
            try:
                db.session.add(new_activity)
                db.session.commit()

                # ▼▼▼ 実績評価トリガー ▼▼▼
                from ...achievement_evaluator import check_achievements_for_event, EVENT_ADD_ACTIVITY_LOG
                check_achievements_for_event(current_user, EVENT_ADD_ACTIVITY_LOG, {'motorcycle_id': vehicle_id})
                # ▲▲▲ トリガーここまで ▲▲▲

                flash('新しい活動記録を作成しました。走行セッションを記録してください。', 'success')
                return redirect(url_for('activity.detail_activity', activity_id=new_activity.id))
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error adding new activity log: {e}", exc_info=True)
                flash('活動記録の保存中にエラーが発生しました。', 'danger')

    if request.method == 'GET':
        form.motorcycle_id.data = vehicle_id
        form.activity_title.data = request.args.get('activity_title', '')
        
        activity_date_str = request.args.get('activity_date')
        if activity_date_str:
            try:
                form.activity_date.data = date.fromisoformat(activity_date_str)
            except (ValueError, TypeError):
                form.activity_date.data = date.today()
        
        # ▼▼▼ 追加: URLパラメータからサーキット情報を取得してセット ▼▼▼
        location_type = request.args.get('location_type')
        if location_type == 'circuit':
            form.location_type.data = 'circuit'
            circuit_name = request.args.get('circuit_name')
            if circuit_name:
                form.circuit_name.data = circuit_name
        # ▲▲▲ 追加ここまで ▲▲▲
        
        custom_location = request.args.get('custom_location')
        if custom_location:
            form.location_type.data = 'custom'
            form.custom_location.data = custom_location

    template_name = 'beta/activity_form_beta.html' if current_user.use_beta_ui else 'activity/activity_form.html'

    return render_template(template_name,
                           form=form,
                           motorcycle=motorcycle,
                           event_id=event_id,
                           form_action='add')

@activity_bp.route('/<int:activity_id>/edit', methods=['GET', 'POST'])
@limiter.limit("30 per hour")
@login_required
def edit_activity(activity_id):
    """活動ログを編集する"""
    activity = ActivityLog.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()
    motorcycle = activity.motorcycle
    form = ActivityLogForm(obj=activity)

    user_motorcycles = Motorcycle.query.filter_by(user_id=current_user.id).order_by(Motorcycle.name).all()
    form.motorcycle_id.choices = [(m.id, f"{m.name} (アーカイブ)" if m.is_archived else m.name) for m in user_motorcycles]

    if form.validate_on_submit():
        original_motorcycle_id = activity.motorcycle_id
        new_motorcycle_id = form.motorcycle_id.data

        if original_motorcycle_id != new_motorcycle_id:
            sessions_to_reset = SessionLog.query.filter_by(activity_log_id=activity.id).all()
            if sessions_to_reset:
                for session in sessions_to_reset:
                    session.setting_sheet_id = None
                flash('車両を変更したため、関連する全セッションのセッティングシート紐付けが解除されました。', 'info')
            
            activity.motorcycle_id = new_motorcycle_id

        activity.activity_date = form.activity_date.data
        activity.activity_title = form.activity_title.data
        activity.location_type = form.location_type.data
        activity.circuit_name = form.circuit_name.data if form.location_type.data == 'circuit' else None
        activity.custom_location = form.custom_location.data if form.location_type.data == 'custom' else None
        activity.weather = form.weather.data
        activity.temperature = form.temperature.data
        activity.notes = form.notes.data
        try:
            db.session.commit()
            flash('活動ログを更新しました。', 'success')
            return redirect(url_for('activity.detail_activity', activity_id=activity.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editing activity log {activity_id}: {e}", exc_info=True)
            flash('活動ログの更新中にエラーが発生しました。', 'danger')
    
    if request.method == 'GET':
        form.motorcycle_id.data = activity.motorcycle_id
        form.location_type.data = activity.location_type or 'circuit'
        form.circuit_name.data = activity.circuit_name
        form.custom_location.data = activity.custom_location

    template_name = 'beta/activity_form_beta.html' if current_user.use_beta_ui else 'activity/activity_form.html'

    return render_template(template_name,
                           form=form,
                           motorcycle=motorcycle,
                           activity=activity,
                           form_action='edit')

@activity_bp.route('/<int:activity_id>/delete', methods=['POST'])
@limiter.limit("30 per hour")
@login_required
def delete_activity(activity_id):
    """活動ログを削除する"""
    activity = ActivityLog.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()
    vehicle_id = activity.motorcycle_id
    try:
        db.session.delete(activity)
        db.session.commit()
        flash('活動ログを削除しました。', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting activity log {activity_id}: {e}", exc_info=True)
        flash('活動ログの削除中にエラーが発生しました。', 'danger')
    return redirect(url_for('activity.list_activities', vehicle_id=vehicle_id))


@activity_bp.route('/<int:activity_id>/detail', methods=['GET', 'POST'])
@limiter.limit("30 per hour", methods=["POST"])
@login_required
def detail_activity(activity_id):
    """活動ログの詳細とセッションの追加/一覧表示"""
    activity = ActivityLog.query.options(
        joinedload(ActivityLog.motorcycle),
        joinedload(ActivityLog.user) 
    ).filter_by(id=activity_id).first_or_404()

    is_owner = (activity.user_id == current_user.id)
    if not can_view_activity(activity, current_user):
        abort(403)
        
    motorcycle = activity.motorcycle
    session_rows = db.session.query(
        SessionLog, has_gps_tracks_expression().label('has_gps_tracks')
    ).options(
        defer(SessionLog.gps_tracks, raiseload=True),
        joinedload(SessionLog.setting_sheet),
    ).filter(SessionLog.activity_log_id == activity.id).order_by(SessionLog.id.asc()).all()
    sessions = []
    for session, has_gps in session_rows:
        session.has_gps_tracks = has_gps
        sessions.append(session)

    default_back_url = url_for('activity.activity_log')
    if request.referrer and '/teams' in request.referrer:
        default_back_url = safe_local_url(request.referrer, default_back_url)
    back_url = safe_local_url(request.args.get('return_to'), default_back_url)
    selected_session_id = request.args.get('session_id', type=int)
    if selected_session_id not in {session.id for session in sessions}:
        selected_session_id = sessions[-1].id if sessions else None

    sort_order = request.args.get('sort', 'record_asc')

    for session in sessions:
        # 1. 既存のラップ統計計算
        session.best_lap, session.average_lap, session.lap_details = calculate_lap_stats(session.lap_times, sort_by=sort_order)
        
        lap_seconds_for_chart = []
        if session.lap_times and isinstance(session.lap_times, list):
            for lap_str in session.lap_times:
                sec = parse_time_to_seconds(lap_str)
                if sec is not None and sec > 0:
                    lap_seconds_for_chart.append(float(sec))
        
        # 2. 統計情報計算とヒートマップ用クラスの付与
        if lap_seconds_for_chart:
            median_sec = statistics.median(lap_seconds_for_chart)
            worst_sec = max(lap_seconds_for_chart)
            
            session.median_lap_seconds = median_sec
            session.worst_lap_seconds = worst_sec
            
            if session.lap_details:
                for detail in session.lap_details:
                    sec = parse_time_to_seconds(detail['time_str'])
                    if sec:
                        sec = float(sec)
                        detail['seconds'] = sec
                        
                        if detail.get('is_best'):
                            detail['row_class'] = 'table-success fw-bold' 
                        elif sec == worst_sec:
                            detail['row_class'] = 'table-danger'          
                        elif sec < median_sec:
                            detail['row_class'] = 'table-info'            
                        else:
                            detail['row_class'] = 'table-warning'         
                    else:
                        detail['row_class'] = ''

            best_lap_seconds = min(lap_seconds_for_chart)
            lap_percentages = [(best_lap_seconds / sec) * 100 for sec in lap_seconds_for_chart]
            session.lap_chart_dict = {
                'labels': list(range(1, len(lap_seconds_for_chart) + 1)),
                'percentages': lap_percentages,
                'raw_times': lap_seconds_for_chart
            }
        else:
            session.lap_chart_dict = None
            session.median_lap_seconds = None
            session.worst_lap_seconds = None
    
    session_form = SessionLogForm()
    import_form = LapTimeImportForm()
    activity_import_form = ActivityLapTimeImportForm()
    activity_import_form.target_session.choices = [('new', '新しいセッションを作成')] + [
        (str(session.id), session.session_name) for session in sessions
    ]
    activity_import_form.new_session_name.data = f'Session {len(sessions) + 1}'

    # GETリクエスト時は、既存のセッション数に基づいて連番のデフォルト名をセットする
    # POSTリクエスト時はユーザーが入力した値をそのまま保持するため、条件分岐で制御する
    if request.method == 'GET':
        next_session_number = len(sessions) + 1
        session_form.session_name.data = f"Session {next_session_number}"
        # ユーザーの既定設定に応じてMisskey投稿許可の初期チェック状態を決める
        session_form.allow_misskey_post.data = not current_user.disallow_misskey_post_by_default

    setting_sheets = SettingSheet.query.filter_by(motorcycle_id=motorcycle.id, is_archived=False).order_by(SettingSheet.sheet_name).all()
    session_form.setting_sheet_id.choices = [(s.id, s.sheet_name) for s in setting_sheets]
    session_form.setting_sheet_id.choices.insert(0, (0, '--- セッティングなし ---'))

    if is_owner and session_form.validate_on_submit():
        lap_times_list = json.loads(session_form.lap_times_json.data) if session_form.lap_times_json.data else []
        
        new_session = SessionLog(
            activity_log_id=activity.id,
            session_name=session_form.session_name.data,
            setting_sheet_id=session_form.setting_sheet_id.data if session_form.setting_sheet_id.data != 0 else None,
            rider_feel=session_form.rider_feel.data,
            lap_times=lap_times_list,
            include_in_leaderboard=session_form.include_in_leaderboard.data,
            allow_misskey_post=session_form.allow_misskey_post.data
        )

        _calculate_and_set_best_lap(new_session, lap_times_list)

        if motorcycle.is_racer:
            duration = session_form.session_duration_hours.data
            if duration is not None:
                new_session.session_duration_hours = duration
                current_hours = motorcycle.total_operating_hours or Decimal('0.0')
                motorcycle.total_operating_hours = current_hours + duration
        else:
            distance = session_form.session_distance.data
            if distance is not None:
                new_session.session_distance = distance

        try:
            db.session.add(new_session)
            db.session.commit()
            flash('新しいセッションを記録しました。', 'success')
            return redirect(url_for('activity.detail_activity', activity_id=activity.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error adding new session log: {e}", exc_info=True)
            flash('セッションの保存中にエラーが発生しました。', 'danger')

    # ▼▼▼【追加】サーキットPBタイムを取得（セッションランク計算用） ▼▼▼
    circuit_pb_seconds = None
    if activity.location_type == 'circuit' and activity.circuit_name:
        pb_result = db.session.query(func.min(SessionLog.best_lap_seconds)).join(
            ActivityLog, SessionLog.activity_log_id == ActivityLog.id
        ).filter(
            ActivityLog.user_id == activity.user_id,
            ActivityLog.circuit_name == activity.circuit_name,
            SessionLog.best_lap_seconds.isnot(None)
        ).scalar()
        if pb_result:
            circuit_pb_seconds = float(pb_result)
    # ▲▲▲【追加】ここまで ▲▲▲

    template_name = 'beta/activity_detail_beta.html' if current_user.use_beta_ui else 'activity/detail_activity.html'

    return render_template(template_name,
                           activity=activity,
                           sessions=sessions,
                           motorcycle=motorcycle,
                           session_form=session_form,
                           import_form=import_form,
                           activity_import_form=activity_import_form,
                           selected_session_id=selected_session_id,
                           back_url=back_url,
                           setting_key_map=SETTING_KEY_MAP,
                           current_sort=sort_order,
                           is_owner=is_owner,
                           circuit_pb_seconds=circuit_pb_seconds
                           )

@activity_bp.route('/<int:activity_id>/toggle_team_share', methods=['POST'])
@login_required
def toggle_team_share(activity_id):
    """活動ログのチーム共有設定を切り替えるAPI"""
    activity = ActivityLog.query.filter_by(
        id=activity_id, 
        user_id=current_user.id
    ).first_or_404()

    try:
        activity.share_with_teams = not activity.share_with_teams
        db.session.commit()
        return jsonify({
            'success': True,
            'share_with_teams': activity.share_with_teams
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error toggling team share for activity {activity_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'サーバーエラーが発生しました。'}), 500


# --- Public Routes (No Login Required) ---

@activity_bp.route('/share/session/<uuid:token>')
def public_session_view(token):
    """【公開】トークンを使って共有セッションページを表示する"""
    session = db.session.query(SessionLog).filter_by(
        public_share_token=str(token), 
        is_public=True
    ).options(
        defer(SessionLog.gps_tracks), 
        defer(SessionLog.lap_times), 
        joinedload(SessionLog.activity).joinedload(ActivityLog.motorcycle),
        joinedload(SessionLog.activity).joinedload(ActivityLog.user)
    ).first()

    if not session:
        abort(404)

    return render_template('activity/public_session.html', session=session)


@activity_bp.route('/share/session/<uuid:token>/gps_data')
def public_gps_data(token):
    """【公開】共有セッションのGPSデータをJSONで返す"""
    session = SessionLog.query.options(
        defer(SessionLog.gps_tracks, raiseload=True),
        joinedload(SessionLog.activity).joinedload(ActivityLog.motorcycle),
        joinedload(SessionLog.setting_sheet),
    ).filter_by(public_share_token=str(token), is_public=True).first()
    if not session:
        return jsonify({'error': 'No GPS data available'}), 404
    from .session_routes import _build_gps_response
    return _build_gps_response(session)
