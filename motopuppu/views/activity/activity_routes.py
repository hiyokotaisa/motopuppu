# motopuppu/views/activity/activity_routes.py
import json
from datetime import date
from decimal import Decimal

from flask import (
    flash, redirect, render_template, request, url_for, abort, current_app
)
from sqlalchemy.orm import joinedload
from sqlalchemy import func

# 分割したBlueprintとユーティリティをインポート
from . import activity_bp
from ...utils.lap_time_utils import calculate_lap_stats, parse_time_to_seconds, _calculate_and_set_best_lap, format_seconds_to_time
from ...constants import SETTING_KEY_MAP

# ▼▼▼ インポート文を修正 ▼▼▼
from flask_login import login_required, current_user
# ▲▲▲ 変更ここまで ▲▲▲
from ...models import db, Motorcycle, ActivityLog, SessionLog, SettingSheet
from ...forms import ActivityLogForm, SessionLogForm, LapTimeImportForm
from ... import limiter


def get_motorcycle_or_404(vehicle_id):
    """指定されたIDの車両を取得し、所有者でなければ404を返す"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    return Motorcycle.query.filter_by(id=vehicle_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲


@activity_bp.route('/<int:vehicle_id>')
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
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
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def add_activity(vehicle_id):
    """新しい活動ログを作成する"""
    motorcycle = get_motorcycle_or_404(vehicle_id)
    if request.method == 'POST':
        event_id = request.form.get('event_id', type=int)
    else:
        event_id = request.args.get('event_id', type=int)

    form = ActivityLogForm(request.form)
    
    if form.validate_on_submit():
        new_activity = ActivityLog(
            motorcycle_id=motorcycle.id,
            # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
            user_id=current_user.id,
            # ▲▲▲ 変更ここまで ▲▲▲
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
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def edit_activity(activity_id):
    """活動ログを編集する"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    activity = ActivityLog.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
    motorcycle = activity.motorcycle
    form = ActivityLogForm(obj=activity)

    if form.validate_on_submit():
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
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def delete_activity(activity_id):
    """活動ログを削除する"""
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    activity = ActivityLog.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()
    # ▲▲▲ 変更ここまで ▲▲▲
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
@login_required # ▼▼▼ デコレータを修正 ▼▼▼
def detail_activity(activity_id):
    """活動ログの詳細とセッションの追加/一覧表示"""
    activity = ActivityLog.query.options(joinedload(ActivityLog.motorcycle))\
                               .filter_by(id=activity_id)\
                               .first_or_404()
    # ▼▼▼ g.user.id を current_user.id に変更 ▼▼▼
    if activity.user_id != current_user.id:
        abort(403)
    # ▲▲▲ 変更ここまで ▲▲▲
        
    motorcycle = activity.motorcycle
    sessions = SessionLog.query.filter_by(activity_log_id=activity.id).order_by(SessionLog.id.asc()).all()

    # --- ▼▼▼ ここからが修正箇所 ▼▼▼ ---

    # 1. URLのクエリパラメータからソート順を取得
    sort_order = request.args.get('sort', 'record_asc')

    for session in sessions:
        # 2. `calculate_lap_stats` にソート順を渡す
        session.best_lap, session.average_lap, session.lap_details = calculate_lap_stats(session.lap_times, sort_by=sort_order)
        
        # グラフデータの生成ロジックは既存のものを維持
        lap_seconds_for_chart = []
        if session.lap_times and isinstance(session.lap_times, list):
            for lap_str in session.lap_times:
                sec = parse_time_to_seconds(lap_str)
                if sec is not None and sec > 0:
                    lap_seconds_for_chart.append(float(sec))
        
        if lap_seconds_for_chart:
            best_lap_seconds = min(lap_seconds_for_chart)
            lap_percentages = [(best_lap_seconds / sec) * 100 for sec in lap_seconds_for_chart]
            session.lap_chart_dict = {
                'labels': list(range(1, len(lap_seconds_for_chart) + 1)),
                'percentages': lap_percentages,
                'raw_times': lap_seconds_for_chart
            }
        else:
            session.lap_chart_dict = None
    
    session_form = SessionLogForm()
    import_form = LapTimeImportForm()

    setting_sheets = SettingSheet.query.filter_by(motorcycle_id=motorcycle.id, is_archived=False).order_by(SettingSheet.sheet_name).all()
    session_form.setting_sheet_id.choices = [(s.id, s.sheet_name) for s in setting_sheets]
    session_form.setting_sheet_id.choices.insert(0, (0, '--- セッティングなし ---'))

    if session_form.validate_on_submit():
        # POST時の処理 (セッション追加) は変更なし
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
            # POST後にリダイレクトする際は、ソートパラメータは不要
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
                           # 3. テンプレートに現在のソート順を渡す
                           current_sort=sort_order)
    # --- ▲▲▲ 変更ここまで ▲▲▲ ---