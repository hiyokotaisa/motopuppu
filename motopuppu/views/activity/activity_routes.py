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
from ...forms import ActivityLogForm, SessionLogForm, LapTimeImportForm
from ... import limiter

# --- RDPアルゴリズム (Douglas-Peucker) のヘルパー関数 ---
def _calculate_perpendicular_distance(point, start, end):
    """点と直線の距離を計算する (平面近似)"""
    if start == end:
        return math.sqrt((point['lat'] - start['lat'])**2 + (point['lng'] - start['lng'])**2)
    
    x0, y0 = point['lng'], point['lat']
    x1, y1 = start['lng'], start['lat']
    x2, y2 = end['lng'], end['lat']
    
    nom = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
    denom = math.sqrt((y2 - y1)**2 + (x2 - x1)**2)
    
    if denom == 0:
        return 0
    return nom / denom

def _ramer_douglas_peucker(points, epsilon):
    """RDPアルゴリズムによる点群の間引き"""
    if len(points) < 3:
        return points

    dmax = 0
    index = 0
    end = len(points) - 1

    for i in range(1, end):
        d = _calculate_perpendicular_distance(points[i], points[0], points[end])
        if d > dmax:
            index = i
            dmax = d

    if dmax > epsilon:
        rec_results1 = _ramer_douglas_peucker(points[:index+1], epsilon)
        rec_results2 = _ramer_douglas_peucker(points[index:], epsilon)
        return rec_results1[:-1] + rec_results2
    else:
        return [points[0], points[end]]

def get_motorcycle_or_404(vehicle_id):
    """指定されたIDの車両を取得し、所有者でなければ404を返す"""
    return Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()


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

    if not user_motorcycles:
        flash('ログを閲覧するには、まず車両を登録してください。', 'info')
        return redirect(url_for('vehicle.add_vehicle'))

    log_type = request.args.get('log_type', '')

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
    active_filters = {k: v for k, v in request.args.items() if k not in ['page', 'sort_by', 'order']}

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
        except ValueError:
            active_filters.pop('vehicle_id', None)

    if keyword:
        search_term = f'%{keyword}%'
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
    
    # ActivityLogを共通形式に変換
    for act in activities:
        # ベストラップ情報の取得（N+1回避のため簡易的に取得するか、必要なら別途クエリ）
        # ここではリスト表示用に代表的な情報だけ持たせる
        best_lap_str = None
        best_session = SessionLog.query.filter(
            SessionLog.activity_log_id == act.id,
            SessionLog.best_lap_seconds.isnot(None)
        ).order_by(SessionLog.best_lap_seconds.asc()).first()
        
        if best_session:
            best_lap_str = format_seconds_to_time(best_session.best_lap_seconds)

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
    class SimplePagination:
        def __init__(self, page, per_page, total):
            self.page = page
            self.per_page = per_page
            self.total = total
            self.items = paginated_logs
        
        @property
        def pages(self):
            if self.per_page == 0: return 0
            return math.ceil(self.total / self.per_page)
        
        @property
        def has_prev(self):
            return self.page > 1
        
        @property
        def has_next(self):
            return self.page < self.pages
        
        @property
        def prev_num(self):
            return self.page - 1
        
        @property
        def next_num(self):
            return self.page + 1

        def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
            last = 0
            for num in range(1, self.pages + 1):
                if num <= left_edge or \
                   (num > self.page - left_current - 1 and num < self.page + right_current) or \
                   num > self.pages - right_edge:
                    if last + 1 != num:
                        yield None
                    yield num
                    last = num

    pagination = SimplePagination(page, per_page, total_items)

    is_filter_active = bool(active_filters)

    return render_template('activity/activity_log.html',
                           logs=paginated_logs,
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
    form.motorcycle_id.choices = [(m.id, m.name) for m in user_motorcycles]

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

    return render_template('activity/activity_form.html',
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
    form.motorcycle_id.choices = [(m.id, m.name) for m in user_motorcycles]

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

    return render_template('activity/activity_form.html',
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
    is_team_member = False
    
    if not is_owner:
        owner_teams = set(team.id for team in activity.user.teams)
        current_user_teams = set(team.id for team in current_user.teams)
        if owner_teams.intersection(current_user_teams):
            is_team_member = True

    if not is_owner and not is_team_member:
        abort(403)
        
    motorcycle = activity.motorcycle
    sessions = SessionLog.query.filter_by(activity_log_id=activity.id).order_by(SessionLog.id.asc()).all()

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
            include_in_leaderboard=session_form.include_in_leaderboard.data
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

    return render_template('activity/detail_activity.html',
                           activity=activity,
                           sessions=sessions,
                           motorcycle=motorcycle,
                           session_form=session_form,
                           import_form=import_form,
                           setting_key_map=SETTING_KEY_MAP,
                           current_sort=sort_order,
                           is_owner=is_owner
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
        joinedload(SessionLog.activity).joinedload(ActivityLog.motorcycle),
        joinedload(SessionLog.setting_sheet)
    ).filter_by(
        public_share_token=str(token), 
        is_public=True
    ).first()

    if not session or not session.gps_tracks or not session.gps_tracks.get('laps'):
        return jsonify({'error': 'No GPS data available'}), 404

    motorcycle = session.activity.motorcycle
    setting_sheet = session.setting_sheet
    vehicle_specs = {
        'primary_ratio': float(motorcycle.primary_ratio) if motorcycle.primary_ratio else None,
        'gear_ratios': {k: float(v) for k, v in motorcycle.gear_ratios.items()} if motorcycle.gear_ratios else None,
        'front_sprocket': None,
        'rear_sprocket': None,
        'rear_tyre_size': None,
    }

    if setting_sheet and setting_sheet.details:
        sprocket_settings = setting_sheet.details.get('sprocket', {})
        tyre_settings = setting_sheet.details.get('tire_rear', {}) 
        try:
            front = sprocket_settings.get('front_teeth')
            if front: vehicle_specs['front_sprocket'] = int(front)
        except (ValueError, TypeError): pass
        try:
            rear = sprocket_settings.get('rear_teeth')
            if rear: vehicle_specs['rear_sprocket'] = int(rear)
        except (ValueError, TypeError): pass
        
        rear_size = tyre_settings.get('tire_size')
        if rear_size: vehicle_specs['rear_tyre_size'] = rear_size

    response_data = {
        'laps': [],
        'lap_times': session.lap_times or [],
        'vehicle_specs': vehicle_specs
    }
    
    raw_laps = session.gps_tracks.get('laps', [])
    for lap in raw_laps:
        raw_track = lap.get('track', [])
        if len(raw_track) > 500:
            simplified_track = _ramer_douglas_peucker(raw_track, 0.000003)
        else:
            simplified_track = raw_track
            
        response_data['laps'].append({
            'lap_number': lap.get('lap_number'),
            'track': raw_track,
            'map_track': simplified_track
        })
    
    response = jsonify(response_data)
    
    response.headers['Cache-Control'] = 'public, max-age=31536000'
    response.add_etag()
    
    return response