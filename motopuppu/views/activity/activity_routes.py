# motopuppu/views/activity/activity_routes.py
import json
import math # 追加: RDPアルゴリズム用
import statistics # 追加: 統計計算用
from datetime import date
from decimal import Decimal
import uuid

from flask import (
    flash, redirect, render_template, request, url_for, abort, current_app, jsonify
)
from sqlalchemy.orm import joinedload, defer # 追加: deferをインポート
from sqlalchemy import func

# 分割したBlueprintとユーティリティをインポート
from . import activity_bp
from ...utils.lap_time_utils import calculate_lap_stats, parse_time_to_seconds, _calculate_and_set_best_lap, format_seconds_to_time
from ...constants import SETTING_KEY_MAP

from flask_login import login_required, current_user
from ...models import db, Motorcycle, ActivityLog, SessionLog, SettingSheet, User 
from ...forms import ActivityLogForm, SessionLogForm, LapTimeImportForm
from ... import limiter

# --- 追加: RDPアルゴリズム (session_routes.pyと循環参照を防ぐためここにも定義) ---
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
# -----------------------------------------------------------


def get_motorcycle_or_404(vehicle_id):
    """指定されたIDの車両を取得し、所有者でなければ404を返す"""
    return Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()


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
        
        # 2. ▼▼▼ 修正: 統計情報計算とヒートマップ用クラスの付与 ▼▼▼
        if lap_seconds_for_chart:
            # 中央値とワースト（最大値）を計算
            median_sec = statistics.median(lap_seconds_for_chart)
            worst_sec = max(lap_seconds_for_chart)
            
            # テンプレートや他で使うためにセッションオブジェクトにも保持
            session.median_lap_seconds = median_sec
            session.worst_lap_seconds = worst_sec
            
            # lap_details に表示用クラス (row_class) を付与
            if session.lap_details:
                for detail in session.lap_details:
                    sec = parse_time_to_seconds(detail['time_str'])
                    if sec:
                        sec = float(sec)
                        detail['seconds'] = sec
                        
                        if detail.get('is_best'):
                            detail['row_class'] = 'table-success fw-bold' # ベスト: 緑
                        elif sec == worst_sec:
                            detail['row_class'] = 'table-danger'          # ワースト: 赤
                        elif sec < median_sec:
                            detail['row_class'] = 'table-info'            # 中央値より速い: 青
                        else:
                            detail['row_class'] = 'table-warning'         # 中央値より遅い: 黄
                    else:
                        detail['row_class'] = ''

            # チャート用データ作成
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
        # ▲▲▲ 修正ここまで ▲▲▲
    
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
    # HTML表示に不要な重いカラムをdeferで除外
    session = db.session.query(SessionLog).filter_by(
        public_share_token=str(token), 
        is_public=True
    ).options(
        defer(SessionLog.gps_tracks), # 巨大なJSONは読み込まない
        defer(SessionLog.lap_times),  # HTMLでは使わない
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

    # 車両スペック情報の取得 (ギア計算用)
    motorcycle = session.activity.motorcycle
    setting_sheet = session.setting_sheet
    vehicle_specs = {
        'primary_ratio': float(motorcycle.primary_ratio) if motorcycle.primary_ratio else None,
        'gear_ratios': {k: float(v) for k, v in motorcycle.gear_ratios.items()} if motorcycle.gear_ratios else None,
        'front_sprocket': None,
        'rear_sprocket': None,
        'rear_tyre_size': None,
    }

    # セッティングシートからスプロケット設定などを上書き
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
    
    # RDPアルゴリズムによる地図用データの生成
    raw_laps = session.gps_tracks.get('laps', [])
    for lap in raw_laps:
        raw_track = lap.get('track', [])
        if len(raw_track) > 500:
            # ▼▼▼ 修正: 閾値を 0.000003 に変更 ▼▼▼
            simplified_track = _ramer_douglas_peucker(raw_track, 0.000003)
            # ▲▲▲ 修正ここまで ▲▲▲
        else:
            simplified_track = raw_track
            
        response_data['laps'].append({
            'lap_number': lap.get('lap_number'),
            'track': raw_track,
            'map_track': simplified_track
        })
    
    response = jsonify(response_data)
    
    # 強力なブラウザキャッシュ設定 (1年間)
    response.headers['Cache-Control'] = 'public, max-age=31536000'
    response.add_etag()
    
    return response